"""
E-mail payment verification (FamPay / bank "payment received" mails in Gmail).

How it works
  1. The invoice shows a QR for the plain story price (no extra paise). The user pays and taps "Submit UTR".
  2. The user sends the 12-digit UTR (transaction ID) of the payment.
  3. The bot reads the admin's Gmail over IMAP (read-only) and looks for a "payment received" mail that
       - contains this exact UTR,
       - contains the exact order amount,
       - arrived AFTER the invoice was created (older mails are ignored).
  4. When such a mail is found the order is completed and the UTR is saved, so it can never be used again
     (shared with the manual-approval UTR guard). One mail can also complete only one order.

Notes
  - Needs a Google APP PASSWORD (16 characters). The normal Gmail password does not work for IMAP any more.
  - Only read access is used. Nothing is ever deleted or sent.
  - There is no sender name / sender filter any more: any "payment received" mail with the right UTR + amount counts.
"""
import asyncio
import email
import html as _html
import imaplib
import re
import time
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

from database.db import (
    get_setting,
    set_setting,
    save_email_credit,
    get_recent_email_credits,
    get_utr_doc,
    claim_utr,
)

ORDER_TTL = 30 * 60          # a payment mail must arrive within 30 minutes after the invoice
CLOCK_SLACK = 60             # small allowance for clock differences between Gmail and this server
MAX_SCAN = 30                # most mails looked at in one check

_LOCK = None

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
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _get_lock() -> "asyncio.Lock":
    global _LOCK
    if _LOCK is None:
        _LOCK = asyncio.Lock()
    return _LOCK


# ------------------------------- configuration -------------------------------
async def get_email_cfg() -> dict:
    raw = ((await get_setting("gateway_config", {}) or {}).get("email")) or {}
    return {
        "email": (raw.get("email") or "").strip().lower(),
        "app_password": re.sub(r"\s+", "", raw.get("app_password") or ""),
    }


def cfg_ready(cfg: dict) -> bool:
    return bool(cfg.get("email") and cfg.get("app_password"))


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


def extract_utrs(text: str) -> set:
    """Every UTR-like number in the mail (a mail can contain more than one number)."""
    found = {m.group(1).upper() for m in _UTR_LABELED.finditer(text)}
    found.update(m.group(1) for m in _UTR_PLAIN.finditer(text))
    return found


def is_credit_mail(subject: str, body: str) -> bool:
    """True for 'money received' mails. An outgoing-payment mail is not a credit."""
    subj, text = subject.lower(), body.lower()
    credit_subject = any(w in subj for w in _CREDIT_WORDS)
    credit_body = any(w in text for w in _CREDIT_WORDS)
    debit = any(w in subj or w in text for w in _DEBIT_WORDS)
    if credit_subject:
        return True
    return credit_body and not debit


def parse_email(raw: bytes, internal_ts=None) -> dict:
    """internal_ts = the time Gmail itself received the mail (more reliable than the Date header)."""
    msg = email.message_from_bytes(raw)
    subject = _decode(msg.get("Subject"))
    sender = _decode(msg.get("From"))
    body = _body_text(msg)
    date_ts = internal_ts
    if date_ts is None:
        try:
            date_ts = parsedate_to_datetime(msg.get("Date")).timestamp()
        except Exception:
            date_ts = None
    text = subject + "\n" + body
    msg_key = (msg.get("Message-ID") or "").strip() or f"nokey:{abs(hash((subject, date_ts, body[:200])))}"
    return {
        "msg_key": msg_key[:200],
        "subject": subject,
        "date_ts": date_ts,
        "is_credit": is_credit_mail(subject, body),
        "amounts": extract_amounts(text),
        "utr": extract_utr(body) or extract_utr(subject),
        "utrs": extract_utrs(text),
    }


def mail_matches_order(info: dict, utr: str, amount: float, created: float) -> bool:
    """True only when the mail is a 'payment received' mail with this UTR and this exact amount, after the invoice."""
    if not info.get("is_credit") or utr not in info.get("utrs", ()):
        return False
    if not any(abs(a - float(amount)) < 0.005 for a in info.get("amounts", [])):
        return False
    ts = info.get("date_ts")
    if ts is None:
        return False
    return created - CLOCK_SLACK <= ts <= created + ORDER_TTL + CLOCK_SLACK


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


def _imap_date(ts: float) -> str:
    t = time.gmtime(ts)
    return f"{t.tm_mday:02d}-{_MONTHS[t.tm_mon - 1]}-{t.tm_year}"


def _fetch_raw(M, uid: int):
    """Returns (raw_mail_bytes, internal_date_timestamp_or_None)."""
    typ, md = M.uid("FETCH", str(uid), "(INTERNALDATE BODY.PEEK[])")
    for part in md or []:
        if isinstance(part, tuple):
            ts = None
            try:
                tt = imaplib.Internaldate2tuple(part[0])
                ts = time.mktime(tt) if tt else None
            except Exception:
                ts = None
            return part[1], ts
    return None, None


def _fetch_candidates(cfg: dict, utr: str, since_ts: float) -> list:
    """Mails since `since_ts` that contain the UTR (falls back to the newest mails). Returns [(uid, raw, ts)]."""
    M = _imap_session(cfg)
    try:
        since = _imap_date(since_ts)
        _, data = M.uid("SEARCH", None, "SINCE", since, "TEXT", utr)
        uids = _uids(data)
        if not uids:                       # Gmail's text search can miss numbers: look at the newest mails instead
            _, data = M.uid("SEARCH", None, "SINCE", since)
            uids = _uids(data)
        out = []
        for u in uids[-MAX_SCAN:]:
            raw, ts = _fetch_raw(M, u)
            if raw:
                out.append((u, raw, ts))
        return out
    finally:
        try:
            M.logout()
        except Exception:
            pass


def _fetch_latest(cfg: dict, count: int):
    M = _imap_session(cfg)
    try:
        _, data = M.uid("SEARCH", None, "ALL")
        uids = _uids(data)
        out = []
        for u in uids[-count:]:
            raw, ts = _fetch_raw(M, u)
            if raw:
                out.append((u, raw, ts))
        return out, len(uids)
    finally:
        try:
            M.logout()
        except Exception:
            pass


# ------------------------------- verification -------------------------------
async def _record_status(error=None, fetched=0):
    await set_setting("email_status", {"t": time.time(), "error": error, "fetched": fetched})


def _explain_error(e: Exception) -> str:
    msg = str(e)
    low = msg.lower()
    if isinstance(e, imaplib.IMAP4.error) or "authenticationfailed" in low or "invalid credentials" in low:
        return ("Gmail login failed. Use a Google APP PASSWORD (not your normal password), make sure 2-Step Verification "
                "is on and IMAP is enabled in Gmail settings.")
    return f"{type(e).__name__}: {msg[:150]}"


async def verify_order_utr(order: dict):
    """
    Checks the UTR the user submitted for this order.
    Returns (status, base_amount) with status:
      "paid"   a matching payment mail was found and the UTR is now locked to this order
      "no_utr" the user has not submitted a UTR yet
      "used"   this UTR (or this payment mail) was already used
      "wait"   no matching mail yet (not arrived, wrong UTR, wrong amount or older than the invoice)
      "error"  the mailbox could not be read right now
    """
    if not order or order.get("provider") != "email":
        return "wait", 0.0
    utr = (order.get("submitted_utr") or "").strip()
    if not utr:
        return "no_utr", 0.0
    order_id = order["order_id"]
    amount = float(order.get("amount") or 0)
    created = float(order.get("created_at") or 0)

    existing = await get_utr_doc(utr)
    if existing:
        # Already locked to THIS order (the delivery failed earlier and the user taps Verify again) -> still paid.
        if existing.get("order_id") == order_id:
            return "paid", amount
        return "used", 0.0

    async with _get_lock():
        cfg = await get_email_cfg()
        if not cfg_ready(cfg):
            return "error", 0.0
        try:
            batch = await asyncio.to_thread(_fetch_candidates, cfg, utr, created - 86400)
        except Exception as e:
            reason = _explain_error(e)
            await _record_status(error=reason)
            print(f"[emailpay] {reason}")
            return "error", 0.0
        await _record_status(error=None, fetched=len(batch))

        for uid, raw, ts in batch:
            try:
                info = parse_email(raw, ts)
            except Exception as e:
                print(f"[emailpay] mail {uid} parse error: {type(e).__name__}: {e}")
                continue
            if not mail_matches_order(info, utr, amount, created):
                continue
            # One payment mail completes only one order.
            doc = {
                "msg_key": info["msg_key"], "uid": uid, "subject": info["subject"][:150], "amounts": info["amounts"],
                "utr": utr, "received_at": info["date_ts"], "created_at": time.time(),
                "status": "MATCHED", "reason": None, "order_id": order_id, "matched_at": time.time(),
            }
            if not await save_email_credit(doc):
                return "used", 0.0
            # The UTR is locked to this order BEFORE anything is delivered.
            if not await claim_utr(utr, order["user_id"], order_id):
                return "used", 0.0
            return "paid", amount
    return "wait", 0.0


async def check_for_order(order: dict):
    """Used by the Verify button. Returns (found, base_amount)."""
    status, amount = await verify_order_utr(order)
    return status == "paid", (amount if status == "paid" else 0.0)


async def poll_loop(client):
    """Not needed any more: payments are checked when the user submits the UTR (or taps Verify)."""
    return


# ------------------------------- admin helpers -------------------------------
async def status_lines() -> str:
    """Lines for the /setup gateway page (rendered as a table in rich messages)."""
    st = await get_setting("email_status") or {}
    credits = await get_recent_email_credits(100)
    matched = sum(1 for c in credits if c.get("status") == "MATCHED")
    if st.get("t"):
        secs = int(time.time() - st["t"])
        ago = f"{secs} seconds ago" if secs < 120 else f"{secs // 60} minutes ago"
    else:
        ago = "not yet"
    state = f"❌ {_html.escape(str(st['error']))[:120]}" if st.get("error") else ("✅ working" if st.get("t") else "—")
    return (
        f"📡 <b>Last check:</b> {ago}\n"
        f"🩺 <b>Status:</b> {state}\n"
        f"✅ <b>Payments verified:</b> {matched}"
    )


async def run_test(cfg: dict):
    """Logs in and shows how the newest mails are understood. Returns (ok, text)."""
    if not cfg_ready(cfg):
        return False, "Save the Gmail address and the app password first."
    try:
        batch, total = await asyncio.to_thread(_fetch_latest, cfg, 3)
    except Exception as e:
        return False, _explain_error(e)

    if not batch:
        return True, "Login works. The inbox has no mail yet. Make a small payment and test again."
    lines = [f"Login works. {total} mails in the inbox. Newest {len(batch)}:"]
    for uid, raw, ts in reversed(batch):
        info = parse_email(raw, ts)
        amounts = ", ".join(f"₹{a:g}" for a in info["amounts"][:4]) or "none"
        lines.append(
            f"\n• <b>{_html.escape(info['subject'][:60])}</b>\n"
            f"  Payment received mail: {'yes' if info['is_credit'] else 'no'}\n"
            f"  Amounts found: {amounts}\n"
            f"  UTR found: {info['utr'] or 'none'}"
        )
    return True, "\n".join(lines)
