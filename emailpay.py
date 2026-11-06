"""
E-mail payment verification (FamPay / bank "payment received" mails in Gmail).

How it works
  1. For every order the bot reserves a UNIQUE amount: price + 1..99 paise (for example Rs 100.37). The invoice shows a QR
     for exactly that amount and tells the user to pay it unchanged.
  2. The bot reads the admin's Gmail over IMAP (read-only) and looks only at mails from the configured sender.
  3. From each mail it extracts the amount(s) and the UTR, and stores the mail so it is never processed twice.
  4. A credit whose amount equals an open order's unique amount belongs to that order. The order is completed
     automatically (a background check every ~40 seconds, or immediately when the user taps Verify).
  5. A UTR can be used only once (shared with the manual-approval UTR guard).

Safety
  - Needs a Google APP PASSWORD (16 characters). The normal Gmail password does not work for IMAP any more.
  - Mails count only if the sender matches the configured text AND Gmail's own DKIM/SPF check passed for that
    sender's domain (so a forged "payment received" mail cannot unlock a story). It can be switched off, not recommended.
  - Only read access is used. Nothing is ever deleted or sent.
  - The first run records the newest existing mail as the starting point, so old mails are never replayed.
"""
import asyncio
import email
import html as _html
import imaplib
import random
import re
import time
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

from config import ADMIN_ID
from database.db import (
    get_setting,
    set_setting,
    get_open_email_payables,
    find_open_email_orders,
    save_email_credit,
    update_email_credit,
    claim_email_credit,
    release_email_credit,
    get_unmatched_email_credits,
    get_recent_email_credits,
    utr_exists,
    claim_utr,
)
from fulfill import fulfill_order

ORDER_TTL = 30 * 60          # an e-mail order can be matched for 30 minutes
CLOCK_SLACK = 5 * 60         # mail clocks differ a little from ours
POLL_SECONDS = 40
MAX_BATCH = 30

_LOCK = None
_ALERT = {"t": 0.0}

_CREDIT_WORDS = ("received", "credited", "credit of", "paid you", "sent you", "deposited", "money in", "payment from")
_DEBIT_WORDS = ("debited", "you paid", "you sent", "paid to", "sent to", "payment to", "withdrawn")

_AMOUNT_RES = (
    re.compile(r"(?:₹|Rs\.?|INR)\s*([0-9]{1,3}(?:,[0-9]{2,3})+(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)", re.I),
    re.compile(r"([0-9]{1,3}(?:,[0-9]{2,3})+(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)\s*(?:INR|rupees)\b", re.I),
)
_UTR_LABELED = re.compile(
    r"(?:UTR|UPI\s*Ref(?:erence)?(?:\s*(?:No\.?|Number|ID))?|Ref(?:erence)?\s*(?:No\.?|Number|ID)|RRN|Txn\s*ID|Transaction\s*ID)"
    r"\s*[:#\-]?\s*([A-Za-z0-9]{9,22})", re.I)
_UTR_PLAIN = re.compile(r"(?<!\d)(\d{12})(?!\d)")


def _get_lock() -> "asyncio.Lock":
    global _LOCK
    if _LOCK is None:
        _LOCK = asyncio.Lock()
    return _LOCK


# ------------------------------- configuration -------------------------------
def _clean_sender(value: str) -> str:
    return re.sub(r"[^a-z0-9@._\-]", "", (value or "").strip().lower())


async def get_email_cfg() -> dict:
    raw = ((await get_setting("gateway_config", {}) or {}).get("email")) or {}
    return {
        "email": (raw.get("email") or "").strip().lower(),
        "app_password": re.sub(r"\s+", "", raw.get("app_password") or ""),
        "sender": _clean_sender(raw.get("sender")),
        "auth": (raw.get("auth") or "on").strip().lower(),
    }


def cfg_ready(cfg: dict) -> bool:
    return bool(cfg.get("email") and cfg.get("app_password") and cfg.get("sender"))


# ------------------------------- unique amount -------------------------------
async def unique_payable(base: float):
    """base + 1..99 paise that no other open e-mail order is using. None if all 99 are taken right now."""
    taken = await get_open_email_payables(time.time() - ORDER_TTL)
    base_paise = int(round(float(base) * 100))
    offsets = list(range(1, 100))
    random.shuffle(offsets)
    for off in offsets:
        if base_paise + off not in taken:
            return (base_paise + off) / 100.0
    return None


# ------------------------------- parsing (pure functions) -------------------------------
def _decode(value) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _html_to_text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style).*?</\1>", " ", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</div>|</li>|</h\d>", "\n", markup)
    markup = re.sub(r"(?i)</t[dh]>", " ", markup)
    text = re.sub(r"<[^>]+>", " ", markup)
    text = _html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def _body_text(msg) -> str:
    plain, html_part = [], []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html") or part.get_content_disposition() == "attachment":
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        (plain if ctype == "text/plain" else html_part).append(text)
    # Use BOTH parts: some mails carry only a short placeholder as plain text and the real details in the HTML part.
    pieces = ["\n".join(plain).strip()]
    if html_part:
        pieces.append(_html_to_text("\n".join(html_part)))
    return "\n".join(x for x in pieces if x)[:100_000]


def extract_amounts(text: str) -> list:
    """Candidate amounts. Lines that talk about receiving money win; otherwise every amount in the mail."""
    def amounts_in(chunk: str) -> list:
        found = []
        for rx in _AMOUNT_RES:
            for m in rx.finditer(chunk):
                try:
                    value = round(float(m.group(1).replace(",", "")), 2)
                except ValueError:
                    continue
                if value > 0 and value not in found:
                    found.append(value)
        return found

    preferred = []
    for line in re.split(r"[\n.](?!\d)", text):
        low = line.lower()
        if any(w in low for w in _CREDIT_WORDS):
            for a in amounts_in(line):
                if a not in preferred:
                    preferred.append(a)
    return preferred or amounts_in(text)


def extract_utr(text: str):
    m = _UTR_LABELED.search(text)
    if m:
        value = m.group(1)
        if value.isdigit() or len(value) >= 10:
            return value
    m = _UTR_PLAIN.search(text)
    return m.group(1) if m else None


def is_credit_mail(subject: str, body: str) -> bool:
    """True for 'money received' mails. An outgoing-payment mail is not a credit."""
    subj, text = subject.lower(), body.lower()
    credit_subject = any(w in subj for w in _CREDIT_WORDS)
    credit_body = any(w in text for w in _CREDIT_WORDS)
    debit = any(w in subj or w in text for w in _DEBIT_WORDS)
    if credit_subject:
        return True
    return credit_body and not debit


def _domain_of(value: str) -> str:
    """'@famapp.in', 'bounce@x.famapp.in' or 'famapp.in' -> the domain part, lower-case."""
    return value.strip().strip("<>@").split("@")[-1].lower()


def check_auth(msg, sender: str, required: bool = True):
    """
    Gmail writes an 'Authentication-Results' header for every mail it receives. The mail is trusted only when one of
    these passed AND is tied to the configured sender's domain (an attacker's own domain passing DKIM is not enough):
      - dmarc=pass with header.from = the sender's domain   (the strongest signal: the From address itself is authentic)
      - dkim=pass with header.d or header.i (Gmail usually writes header.i=@domain) = the sender's domain
      - spf=pass with smtp.mailfrom = the sender's domain
    Returns (ok, detail).
    """
    if not required:
        return True, "check disabled"
    results = " ".join(str(h) for h in (msg.get_all("Authentication-Results") or [])).lower()
    if not results:
        return False, "no Authentication-Results header"
    key = _domain_of(sender)
    for m in re.finditer(r"dmarc=pass[^;]*?header\.from=([\w.\-]+)", results):
        if key in _domain_of(m.group(1)):
            return True, f"dmarc=pass from={m.group(1)}"
    for m in re.finditer(r"dkim=pass[^;]*?header\.(?:d|i)=([\w.\-+@]+)", results):
        if key in _domain_of(m.group(1)):
            return True, f"dkim=pass {m.group(1)}"
    for m in re.finditer(r"spf=pass[^;]*?smtp\.mailfrom=([\w.\-+@]+)", results):
        if key in _domain_of(m.group(1)):
            return True, f"spf=pass {m.group(1)}"
    return False, "DMARC/DKIM/SPF did not pass for the sender's domain"


def parse_email(raw: bytes, cfg: dict) -> dict:
    msg = email.message_from_bytes(raw)
    subject = _decode(msg.get("Subject"))
    sender = _decode(msg.get("From"))
    body = _body_text(msg)
    try:
        date_ts = parsedate_to_datetime(msg.get("Date")).timestamp()
    except Exception:
        date_ts = time.time()
    auth_ok, auth_detail = check_auth(msg, cfg["sender"], cfg.get("auth", "on") != "off")
    sender_ok = cfg["sender"] in sender.lower()
    msg_key = (msg.get("Message-ID") or "").strip() or f"nokey:{abs(hash((subject, date_ts, body[:200])))}"
    return {
        "msg_key": msg_key[:200],
        "from": sender,
        "subject": subject,
        "date_ts": date_ts,
        "is_credit": is_credit_mail(subject, body),
        "amounts": extract_amounts(subject + "\n" + body),
        "utr": extract_utr(body) or extract_utr(subject),
        "sender_ok": sender_ok,
        "auth_ok": auth_ok,
        "auth_detail": auth_detail,
    }


# ------------------------------- IMAP (blocking, run in a thread) -------------------------------
def _imap_session(cfg: dict):
    try:
        M = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=30)
    except TypeError:  # very old Python: no timeout argument
        M = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    M.login(cfg["email"], cfg["app_password"])
    M.select("INBOX", readonly=True)
    return M


def _uids(data) -> list:
    return sorted(int(x) for x in (data[0] or b"").split())


def _fetch_raw(M, uid: int):
    typ, md = M.uid("FETCH", str(uid), "(BODY.PEEK[])")
    for part in md or []:
        if isinstance(part, tuple):
            return part[1]
    return None


def _fetch_new(cfg: dict, last_uid, limit: int):
    """Returns ([(uid, raw)], newest_uid_seen). With last_uid=None it only records a starting point."""
    M = _imap_session(cfg)
    try:
        if last_uid is None:
            _, data = M.uid("SEARCH", None, "ALL")
            uids = _uids(data)
            return [], (uids[-1] if uids else 0)
        _, data = M.uid("SEARCH", None, "UID", f"{last_uid + 1}:*", "FROM", f'"{cfg["sender"]}"')
        uids = [u for u in _uids(data) if u > last_uid][:limit]
        out = []
        for u in uids:
            raw = _fetch_raw(M, u)
            if raw:
                out.append((u, raw))
        return out, (uids[-1] if uids else last_uid)
    finally:
        try:
            M.logout()
        except Exception:
            pass


def _fetch_latest(cfg: dict, count: int):
    M = _imap_session(cfg)
    try:
        _, data = M.uid("SEARCH", None, "FROM", f'"{cfg["sender"]}"')
        uids = _uids(data)
        out = []
        for u in uids[-count:]:
            raw = _fetch_raw(M, u)
            if raw:
                out.append((u, raw))
        return out, len(uids)
    finally:
        try:
            M.logout()
        except Exception:
            pass


# ------------------------------- processing -------------------------------
async def _record_status(error=None, fetched=0):
    await set_setting("email_status", {"t": time.time(), "error": error, "fetched": fetched})


async def _alert_admin(client, text: str):
    if client is None or time.time() - _ALERT["t"] < 3600:
        return
    _ALERT["t"] = time.time()
    try:
        await client.send_message(ADMIN_ID, text)
    except Exception:
        pass


def _explain_error(e: Exception) -> str:
    msg = str(e)
    low = msg.lower()
    if isinstance(e, imaplib.IMAP4.error) or "authenticationfailed" in low or "invalid credentials" in low:
        return ("Gmail login failed. Use a Google APP PASSWORD (not your normal password), make sure 2-Step Verification "
                "is on and IMAP is enabled in Gmail settings.")
    return f"{type(e).__name__}: {msg[:150]}"


async def _find_order(credit: dict):
    now = time.time()
    for amount in credit["amounts"]:
        for order in await find_open_email_orders(amount, now - ORDER_TTL - CLOCK_SLACK):
            created = order.get("created_at", 0)
            if created - CLOCK_SLACK <= credit["received_at"] <= created + ORDER_TTL + CLOCK_SLACK:
                return order
    return None


async def _try_match(client, credit: dict, auto: bool) -> str:
    key = credit["msg_key"]
    if credit.get("utr") and await utr_exists(credit["utr"]):
        await update_email_credit(key, {"status": "IGNORED", "reason": "UTR already used"})
        return "duplicate"
    if not auto:                      # user pressed Verify: the order itself will be completed by the caller
        await update_email_credit(key, {"status": "UNMATCHED"})
        return "stored"
    order = await _find_order(credit)
    if not order:
        await update_email_credit(key, {"status": "UNMATCHED"})
        return "unmatched"
    if not await claim_email_credit(key, order["order_id"]):
        return "taken"
    result = await fulfill_order(client, order, float(order["amount"]), "EMAIL")
    if result in ("done", "already"):
        if credit.get("utr"):
            await claim_utr(credit["utr"], order["user_id"])
        return "matched"
    await release_email_credit(key)
    return "error"


async def _handle_email(client, uid: int, info: dict, auto: bool) -> str:
    doc = {
        "msg_key": info["msg_key"], "uid": uid, "subject": info["subject"][:150], "sender": info["from"][:120],
        "amounts": info["amounts"], "utr": info["utr"], "received_at": info["date_ts"], "created_at": time.time(),
        "status": "NEW", "reason": None, "auth": info["auth_detail"][:120],
    }
    if not info["sender_ok"]:
        doc.update(status="IGNORED", reason="sender does not match")
    elif not info["is_credit"]:
        doc.update(status="IGNORED", reason="not a payment-received mail")
    elif not info["auth_ok"]:
        doc.update(status="IGNORED", reason=f"sender not verified: {info['auth_detail']}")
    elif not info["amounts"]:
        doc.update(status="IGNORED", reason="no amount found")

    if not await save_email_credit(doc):
        return "seen"
    if doc["status"] != "NEW":
        return "ignored"
    return await _try_match(client, doc, auto)


async def process_new_mail(client, auto: bool = True) -> dict:
    """
    Reads new mails once. auto=True completes matching orders (background loop).
    auto=False only stores the credits (used when a user taps Verify, the caller completes the order itself).
    """
    summary = {"fetched": 0, "matched": 0}
    async with _get_lock():
        cfg = await get_email_cfg()
        if not cfg_ready(cfg):
            return summary
        last = await get_setting("email_last_uid")
        try:
            batch, newest = await asyncio.to_thread(_fetch_new, cfg, last, MAX_BATCH)
        except Exception as e:
            reason = _explain_error(e)
            await _record_status(error=reason)
            print(f"[emailpay] {reason}")
            await _alert_admin(client, f"⚠️ <b>Gmail payment check failed</b>\n\n{_html.escape(reason)}")
            return summary

        if last is None:
            await set_setting("email_last_uid", newest)       # starting point: old mails are never replayed
            await _record_status(error=None, fetched=0)
            return summary

        for uid, raw in batch:
            try:
                outcome = await _handle_email(client, uid, parse_email(raw, cfg), auto)
                if outcome == "matched":
                    summary["matched"] += 1
            except Exception as e:
                print(f"[emailpay] mail {uid} error: {type(e).__name__}: {e}")
        if newest != last:
            await set_setting("email_last_uid", newest)
        summary["fetched"] = len(batch)
        await _record_status(error=None, fetched=len(batch))
    return summary


async def check_for_order(order: dict):
    """
    Used by the Verify button. Reads new mail, then looks for a stored, unused credit with this order's unique amount.
    Returns (found, base_amount).
    """
    if not order or order.get("provider") != "email":
        return False, 0.0
    await process_new_mail(None, auto=False)
    payable = order.get("payable_amount")
    if payable is None:
        return False, 0.0
    created = order.get("created_at", 0)
    for credit in await get_unmatched_email_credits(created - CLOCK_SLACK):
        if not any(abs(a - payable) < 0.005 for a in credit.get("amounts", [])):
            continue
        if credit["received_at"] > created + ORDER_TTL + CLOCK_SLACK:
            continue
        if credit.get("utr") and await utr_exists(credit["utr"]):
            continue
        if await claim_email_credit(credit["msg_key"], order["order_id"]):
            if credit.get("utr"):
                await claim_utr(credit["utr"], order["user_id"])
            return True, float(order["amount"])
    return False, 0.0


async def _email_active() -> bool:
    return ((await get_setting("gateway_config", {}) or {}).get("active")) == "email"


async def poll_loop(client):
    """Background task: while the e-mail gateway is the active one, check the mailbox every ~40 seconds."""
    await asyncio.sleep(20)
    while True:
        try:
            if await _email_active():
                await process_new_mail(client, auto=True)
        except Exception as e:
            print(f"[emailpay] loop error: {type(e).__name__}: {e}")
        await asyncio.sleep(POLL_SECONDS + random.randint(0, 8))


# ------------------------------- admin helpers -------------------------------
async def status_lines() -> str:
    """Lines for the /setup gateway page (rendered as a table in rich messages)."""
    st = await get_setting("email_status") or {}
    credits = await get_recent_email_credits(100)
    matched = sum(1 for c in credits if c.get("status") == "MATCHED")
    unmatched = sum(1 for c in credits if c.get("status") == "UNMATCHED")
    if st.get("t"):
        secs = int(time.time() - st["t"])
        ago = f"{secs} seconds ago" if secs < 120 else f"{secs // 60} minutes ago"
    else:
        ago = "not yet"
    state = f"❌ {_html.escape(str(st['error']))[:120]}" if st.get("error") else ("✅ working" if st.get("t") else "—")
    return (
        f"📡 <b>Last check:</b> {ago}\n"
        f"🩺 <b>Status:</b> {state}\n"
        f"✅ <b>Payments matched:</b> {matched}\n"
        f"⏳ <b>Unmatched credits:</b> {unmatched}"
    )


async def run_test(cfg: dict):
    """Logs in and shows how the newest mails from the sender are understood. Returns (ok, text)."""
    if not cfg_ready(cfg):
        return False, "Save the Gmail address, the app password and the sender first."
    try:
        batch, total = await asyncio.to_thread(_fetch_latest, cfg, 3)
    except Exception as e:
        return False, _explain_error(e)

    if not batch:
        return True, (f"Login works. No mail from “{cfg['sender']}” was found yet. Check the sender text, or make a "
                      "small payment and test again.")
    lines = [f"Login works. {total} mails from “{cfg['sender']}”. Newest {len(batch)}:"]
    for uid, raw in reversed(batch):
        info = parse_email(raw, cfg)
        amounts = ", ".join(f"₹{a:g}" for a in info["amounts"][:4]) or "none"
        lines.append(
            f"\n• <b>{_html.escape(info['subject'][:60])}</b>\n"
            f"  Payment received mail: {'yes' if info['is_credit'] else 'no'}\n"
            f"  Amounts found: {amounts}\n"
            f"  UTR found: {info['utr'] or 'none'}\n"
            f"  Sender check: {'passed' if info['auth_ok'] else 'FAILED'} ({_html.escape(info['auth_detail'])})"
        )
    return True, "\n".join(lines)
