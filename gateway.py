"""
Payment gateways: Demotry.shop, Razorpay, Cashfree.

Keys Render env me nahi, bot ke andar /setup se set hoti hain (database me save).
Env variables (API_KEY_VALUE, API_SECRET_VALUE, UPI_ID) sirf fallback hain.

Har order ke saath uska provider DB me save hota hai (payment_orders.provider), isliye gateway
badalne ke baad bhi purane orders apne hi gateway se verify hote hain.

NOTE: Razorpay / Cashfree ka code unke official docs ke hisaab se likha hai, lekin live account par
abhi test nahi hua. Pehle /setup me "Test" dabayein aur chhoti (Rs 1-10) khareed karke dekhein.
"""
import re
import json
import time
import asyncio
import secrets
import aiohttp

from config import (
    BOT_USERNAME, WEB_APP_URL, UPI_ID as ENV_UPI_ID, CREATE_ORDER_URL, CHECK_STATUS_URL,
    API_KEY_VALUE, API_SECRET_VALUE, PAYMENT_CALLBACK_URL
)
from database.db import get_setting, get_payment_order
import emailpay

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# In HTTP codes par dobara try karna bekaar hai (key/request galat ya limit)
_NO_RETRY_STATUS = {400, 401, 403, 404, 422, 429}

CASHFREE_API_VERSION = "2025-01-01"

# /setup panel is dict se banta hai: har gateway ke fields (name, label, secret?, min_len, choices)
GATEWAYS = {
    "demotry": {
        "title": "Demotry.shop",
        "fields": [
            {"name": "api_key", "label": "API Key (X-API-Key)", "secret": False, "min": 10},
            {"name": "api_secret", "label": "API Secret (X-API-Secret)", "secret": True, "min": 10},
        ],
        "note": "The callback URL is set automatically: <code>{web}/paytm</code>",
    },
    "razorpay": {
        "title": "Razorpay",
        "fields": [
            {"name": "key_id", "label": "Key ID (rzp_live_...)", "secret": False, "min": 8, "prefix": "rzp_"},
            {"name": "key_secret", "label": "Key Secret", "secret": True, "min": 10},
        ],
        "note": (
            "For automatic verification (optional): in the Razorpay Dashboard open Settings → Webhooks, add "
            "<code>{web}/webhook/razorpay</code> and select the event <b>payment_link.paid</b>. "
            "Without a webhook, users can still press Verify Payment."
        ),
    },
    "email": {
        "title": "FamPay (Gmail)",
        "fields": [
            {"name": "email", "label": "Gmail address", "secret": False, "show": True, "min": 6,
             "regex": r"^[^@\s]+@[^@\s]+\.[^@\s]+$", "regex_error": "That does not look like an email address."},
            {"name": "app_password", "label": "Gmail App Password", "secret": True, "min": 12},
            {"name": "sender", "label": "Sender of the payment mails", "secret": False, "show": True, "min": 3},
            {"name": "auth", "label": "Sender check", "secret": False, "show": True, "min": 1,
             "choices": ["on", "off"], "optional": True},
        ],
        "note": (
            "The bot reads the payment-received emails in this Gmail and matches each payment by its exact amount "
            "(price plus a few paise) and its UTR.\n"
            "1. Google Account → Security → turn ON 2-Step Verification.\n"
            "2. Security → App passwords → create one → paste the 16 characters here (not your normal password).\n"
            "3. Gmail → Settings → Forwarding and POP/IMAP → turn ON IMAP.\n"
            "4. <b>Sender</b> = text from the payment mails' From address, for example <code>fampay</code> or the full address.\n"
            "5. Also set your FamPay UPI ID (main panel → Change UPI ID).\n"
            "<i>Tip: use a separate Gmail that only receives forwarded payment mails. Keep <b>Sender check</b> ON: it "
            "stops forged \"payment received\" emails.</i>"
        ),
    },
    "cashfree": {
        "title": "Cashfree",
        "fields": [
            {"name": "client_id", "label": "App ID (x-client-id)", "secret": False, "min": 6},
            {"name": "client_secret", "label": "Secret Key (x-client-secret)", "secret": True, "min": 10},
            {"name": "env", "label": "Mode", "secret": False, "min": 1, "choices": ["prod", "sandbox"], "optional": True},
        ],
        "note": "The webhook URL (notify_url) is set automatically: <code>{web}/webhook/cashfree</code>",
    },
}


# ----------------------------- config (DB + env fallback) -----------------------------
async def load_config() -> dict:
    raw = await get_setting("gateway_config", {}) or {}
    demotry = raw.get("demotry") or {}
    razorpay = raw.get("razorpay") or {}
    cashfree = raw.get("cashfree") or {}
    mail = raw.get("email") or {}
    return {
        "active": raw.get("active") or "demotry",
        "upi_id": raw.get("upi_id") or ENV_UPI_ID,
        "upi_saved": bool(raw.get("upi_id")),      # the e-mail gateway must not fall back to the default env UPI ID
        "email": {
            "email": (mail.get("email") or "").strip().lower(),
            "app_password": re.sub(r"\s+", "", mail.get("app_password") or ""),
            "sender": (mail.get("sender") or "").strip().lower(),
            "auth": (mail.get("auth") or "on").strip().lower(),
        },
        "demotry": {
            "api_key": (demotry.get("api_key") or API_KEY_VALUE or "").strip(),
            "api_secret": (demotry.get("api_secret") or API_SECRET_VALUE or "").strip(),
        },
        "razorpay": {
            "key_id": (razorpay.get("key_id") or "").strip(),
            "key_secret": (razorpay.get("key_secret") or "").strip(),
        },
        "cashfree": {
            "client_id": (cashfree.get("client_id") or "").strip(),
            "client_secret": (cashfree.get("client_secret") or "").strip(),
            "env": (cashfree.get("env") or "prod").strip(),
        },
    }


async def get_upi_id() -> str:
    return (await load_config())["upi_id"]


def is_configured(gw: str, cfg: dict) -> bool:
    spec = GATEWAYS.get(gw)
    if not spec:
        return False
    for f in spec["fields"]:
        if f.get("optional"):
            continue
        if not (cfg.get(gw, {}).get(f["name"]) or "").strip():
            return False
    if gw == "email" and not cfg.get("upi_saved"):
        return False
    return True


def mask(value: str) -> str:
    value = value or ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}…{value[-4:]}"


# ----------------------------- small helpers -----------------------------
def _short(body: str, limit: int = 160) -> str:
    """HTML error page ko chhote saaf text me badalta hai (logs me poora HTML na aaye)."""
    body = body or ""
    if "<" in body and ">" in body:
        m = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
        text = m.group(1) if m else re.sub(r"<[^>]+>", " ", body)
        text = "HTML page: " + text
    else:
        text = body
    return re.sub(r"\s+", " ", text).strip()[:limit]


def is_quota_error(err) -> bool:
    """Gateway ki monthly order limit / plan limit wala error?"""
    e = str(err or "").lower()
    return ("429" in e) or ("limit" in e) or ("upgrade" in e)


def is_blocked_error(err) -> bool:
    """Gateway ki bot-protection / firewall ne request roki (403, 'Bot Verification', Cloudflare)?"""
    e = str(err or "").lower()
    return ("403" in e) or ("bot verification" in e) or ("cloudflare" in e) or ("just a moment" in e)


def new_order_id(user_id: int) -> str:
    """Hamesha unique: user + time + random. callback_data me bhi chhota rehta hai."""
    return f"ORD_{user_id}_{int(time.time())}_{secrets.token_hex(3)}"


def _json(body: str) -> dict:
    try:
        data = json.loads(body)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def _http(method: str, url: str, headers=None, json_body=None, auth=None, timeout: int = 20):
    t = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=t) as session:
        async with session.request(method, url, headers=headers, json=json_body, auth=auth) as resp:
            body = await resp.text()
            return resp.status, body


def _error_text(status: int, body: str) -> str:
    data = _json(body)
    err = data.get("error")
    if isinstance(err, dict):
        msg = err.get("description") or err.get("message") or err.get("code")
    else:
        msg = err or data.get("message") or data.get("details")
    return f"HTTP {status}: {msg if msg else _short(body)}"


# ----------------------------- DEMOTRY -----------------------------
def _demotry_headers(c: dict) -> dict:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": _BROWSER_UA,
        "X-API-Key": c["api_key"],
        "X-API-Secret": c["api_secret"],
    }


def _pick_url(data) -> str:
    if not isinstance(data, dict):
        return None
    keys = ("payment_url", "url", "payment_link", "link", "checkout_url")
    inner = data.get("data")
    if isinstance(inner, dict):
        for k in keys:
            if inner.get(k):
                return inner[k]
    for k in keys:
        if data.get(k):
            return data[k]
    return None


async def _create_demotry(cfg, order_id, name, amount):
    c = cfg["demotry"]
    payload = {
        "amount": f"{float(amount):.2f}",   # docs: amount string, jaise "100.00"
        "order_id": order_id,
        "customer_name": name or "Telegram User",
        "customer_mobile": "9999999999",
        "redirect_url": f"https://t.me/{BOT_USERNAME}",
        "callback_url": PAYMENT_CALLBACK_URL,
    }
    status, body = await _http("POST", CREATE_ORDER_URL, headers=_demotry_headers(c), json_body=payload)
    if status in (200, 201):
        pay_url = _pick_url(_json(body))
        if pay_url:
            return pay_url, order_id, None, False
        return None, None, f"HTTP {status} but no payment url in reply: {_short(body)}", False
    return None, None, f"HTTP {status}: {_short(body)}", status in _NO_RETRY_STATUS


async def _check_demotry(cfg, order_id, ref):
    status, body = await _http("POST", CHECK_STATUS_URL, headers=_demotry_headers(cfg["demotry"]),
                               json_body={"order_id": ref}, timeout=10)
    if status != 200:
        return False, 0.0, f"Server Error (HTTP {status}): {_short(body)}"
    data = _json(body)
    res = data.get("data", {}) if isinstance(data.get("data"), dict) else data
    st = str(res.get("payment_status") or res.get("status") or data.get("status") or "").upper()
    try:
        paid_amt = float(res.get("amount", 0) or data.get("amount", 0) or 0)
    except (TypeError, ValueError):
        paid_amt = 0.0
    if st in ("SUCCESS", "PAID", "COMPLETED"):
        return True, paid_amt, "Payment Verified Successfully"
    return False, 0.0, f"Status: {st if st else 'PENDING'}"


# ----------------------------- RAZORPAY (Payment Links API) -----------------------------
def _rzp_auth(cfg):
    return aiohttp.BasicAuth(cfg["razorpay"]["key_id"], cfg["razorpay"]["key_secret"])


async def _create_razorpay(cfg, order_id, name, amount):
    payload = {
        "amount": int(round(float(amount) * 100)),      # paise (minimum 100)
        "currency": "INR",
        "accept_partial": False,
        "reference_id": order_id,                        # unique, max 40 chars
        "description": f"Order {order_id}"[:200],
        "customer": {"name": name or "Telegram User"},
        "notify": {"sms": False, "email": False},
        "reminder_enable": False,
        "callback_url": f"https://t.me/{BOT_USERNAME}",
        "callback_method": "get",
    }
    status, body = await _http("POST", "https://api.razorpay.com/v1/payment_links",
                               headers={"Content-Type": "application/json"},
                               json_body=payload, auth=_rzp_auth(cfg))
    if status in (200, 201):
        data = _json(body)
        if data.get("short_url"):
            return data["short_url"], data.get("id"), None, False
        return None, None, f"HTTP {status} but no short_url: {_short(body)}", False
    return None, None, _error_text(status, body), status in _NO_RETRY_STATUS


async def _check_razorpay(cfg, order_id, ref):
    auth = _rzp_auth(cfg)
    if ref and str(ref).startswith("plink_"):
        status, body = await _http("GET", f"https://api.razorpay.com/v1/payment_links/{ref}", auth=auth, timeout=10)
        data = _json(body)
    else:
        status, body = await _http("GET", f"https://api.razorpay.com/v1/payment_links?reference_id={order_id}",
                                   auth=auth, timeout=10)
        links = _json(body).get("payment_links") or []
        data = links[0] if links else {}
    if status != 200:
        return False, 0.0, _error_text(status, body)
    st = str(data.get("status") or "").lower()
    if st == "paid":
        return True, float(data.get("amount_paid", 0) or 0) / 100.0, "Payment Verified Successfully"
    return False, 0.0, f"Status: {st.upper() if st else 'PENDING'}"


# ----------------------------- CASHFREE (Payment Links API) -----------------------------
def _cf_base(cfg) -> str:
    return "https://sandbox.cashfree.com/pg" if cfg["cashfree"]["env"] == "sandbox" else "https://api.cashfree.com/pg"


def _cf_headers(cfg) -> dict:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-api-version": CASHFREE_API_VERSION,
        "x-client-id": cfg["cashfree"]["client_id"],
        "x-client-secret": cfg["cashfree"]["client_secret"],
    }


async def _create_cashfree(cfg, order_id, name, amount):
    payload = {
        "link_id": order_id,                              # unique, max 50 chars
        "link_amount": round(float(amount), 2),
        "link_currency": "INR",
        "link_purpose": f"Order {order_id}"[:500],
        "customer_details": {"customer_phone": "9999999999", "customer_name": name or "Telegram User"},
        "link_notify": {"send_sms": False, "send_email": False},
        "link_auto_reminders": False,
        "link_meta": {
            "notify_url": f"{WEB_APP_URL.rstrip('/')}/webhook/cashfree",
            "return_url": f"https://t.me/{BOT_USERNAME}",
        },
    }
    status, body = await _http("POST", f"{_cf_base(cfg)}/links", headers=_cf_headers(cfg), json_body=payload)
    if status in (200, 201):
        data = _json(body)
        if data.get("link_url"):
            return data["link_url"], data.get("link_id") or order_id, None, False
        return None, None, f"HTTP {status} but no link_url: {_short(body)}", False
    return None, None, _error_text(status, body), status in _NO_RETRY_STATUS


async def _check_cashfree(cfg, order_id, ref):
    status, body = await _http("GET", f"{_cf_base(cfg)}/links/{ref or order_id}", headers=_cf_headers(cfg), timeout=10)
    if status != 200:
        return False, 0.0, _error_text(status, body)
    data = _json(body)
    st = str(data.get("link_status") or "").upper()
    if st == "PAID":
        try:
            amt = float(data.get("link_amount_paid") or data.get("link_amount") or 0)
        except (TypeError, ValueError):
            amt = 0.0
        return True, amt, "Payment Verified Successfully"
    return False, 0.0, f"Status: {st if st else 'PENDING'}"


# ----------------------------- FAMPAY via GMAIL (exact-amount matching) -----------------------------
async def _create_email(cfg, order_id, name, amount):
    payable = await emailpay.unique_payable(float(amount))
    if payable is None:
        return None, None, "All payment slots are busy right now. Please try again in a minute.", True   # retrying instantly cannot help
    upi_uri = f"upi://pay?pa={cfg['upi_id']}&pn=StorySeller&am={payable:.2f}&cu=INR&tn={order_id}"
    return upi_uri, {"payable_amount": payable}, None, False


async def _check_email(cfg, order_id, ref):
    order = await get_payment_order(order_id)
    found, base_amount = await emailpay.check_for_order(order)
    if found:
        return True, base_amount, "Payment found in the bank email"
    return False, 0.0, "Status: PENDING (waiting for the bank email)"


_CREATORS = {"demotry": _create_demotry, "razorpay": _create_razorpay, "cashfree": _create_cashfree, "email": _create_email}
_CHECKERS = {"demotry": _check_demotry, "razorpay": _check_razorpay, "cashfree": _check_cashfree, "email": _check_email}


# ----------------------------- PUBLIC API -----------------------------
async def create_order(user_id: int, user_name: str, amount: float, attempts: int = 2):
    """
    Returns (pay_url, order_id, error_text, meta). meta = {"provider": ..., "provider_ref": ...}.
    pay_url None ho to error_text me wajah hoti hai (logs me bhi print hota hai).
    """
    cfg = await load_config()
    gw = cfg["active"] if cfg["active"] in _CREATORS else "demotry"
    meta = {"provider": gw, "provider_ref": None}
    order_id = new_order_id(user_id)

    if not is_configured(gw, cfg):
        err = f"{GATEWAYS[gw]['title']} API keys are not saved (open /setup)"
        print(f"❌ create_order: {err}")
        return None, order_id, err, meta

    last_err = "unknown error"
    for attempt in range(1, attempts + 1):
        order_id = new_order_id(user_id)  # har attempt par naya id: timeout ke baad duplicate-order error nahi aayega
        try:
            pay_url, ref, err, final = await _CREATORS[gw](cfg, order_id, user_name, amount)
            if pay_url:
                if isinstance(ref, dict):      # the e-mail gateway returns {"payable_amount": ...}
                    meta.update(ref)
                else:
                    meta["provider_ref"] = ref
                return pay_url, order_id, None, meta
            last_err = err or "unknown error"
            if final:
                print(f"❌ create_order[{gw}] failed (no retry): {last_err}")
                return None, order_id, last_err, meta
        except asyncio.TimeoutError:
            last_err = "gateway timeout"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"

        print(f"⚠ create_order[{gw}] attempt {attempt}/{attempts} failed -> {last_err}")
        if attempt < attempts:
            await asyncio.sleep(1.5 * attempt)

    print(f"❌ create_order[{gw}] gave up: {last_err}")
    return None, order_id, last_err, meta


async def check_order_status(order_id: str, attempts: int = 2):
    """Returns (is_paid, paid_amount, message). Order ke apne provider se check hota hai."""
    order = await get_payment_order(order_id) or {}
    gw = order.get("provider") or "demotry"
    ref = order.get("provider_ref") or order_id
    cfg = await load_config()

    if gw not in _CHECKERS or not is_configured(gw, cfg):
        return False, 0.0, "Gateway keys are not saved"

    last_msg = "Connection Error"
    for attempt in range(1, attempts + 1):
        try:
            paid, amt, msg = await _CHECKERS[gw](cfg, order_id, ref)
            if paid or "HTTP" not in msg:
                return paid, amt, msg
            last_msg = msg
            if any(f"HTTP {c}" in msg for c in _NO_RETRY_STATUS):
                break
        except Exception as e:
            last_msg = f"Connection Error: {type(e).__name__}: {e}"
        if attempt < attempts:
            await asyncio.sleep(1.5)

    print(f"⚠ check_order_status[{gw}]({order_id}) -> {last_msg}")
    return False, 0.0, last_msg


async def test_gateway(gw: str):
    """
    Keys sahi hain ya nahi, bina koi order banaye (limit nahi khati). Returns (ok, message).
    """
    cfg = await load_config()
    if gw not in GATEWAYS:
        return False, "Unknown gateway"
    if gw != "email" and not is_configured(gw, cfg):
        return False, "Save all the keys first"

    try:
        if gw == "demotry":
            status, body = await _http("POST", CHECK_STATUS_URL, headers=_demotry_headers(cfg["demotry"]),
                                       json_body={"order_id": "TEST_PING_000"}, timeout=12)
            if status == 401:
                return False, "Wrong API key or secret (HTTP 401)"
            if status == 403:
                return False, f"The gateway blocked the bot (HTTP 403): {_short(body, 80)}"
            if status == 429:
                return False, "Order or request limit reached (HTTP 429)"
            if status >= 500:
                return False, f"Gateway server error (HTTP {status})"
            return True, f"Keys accepted (HTTP {status})"

        if gw == "email":
            ok, text = await emailpay.run_test(await emailpay.get_email_cfg())
            if ok and not cfg.get("upi_saved"):
                text += "\n\n⚠️ Your FamPay UPI ID is not saved yet (main panel → Change UPI ID)."
            return ok, text

        if gw == "razorpay":
            status, body = await _http("GET", "https://api.razorpay.com/v1/payment_links?count=1",
                                       auth=_rzp_auth(cfg), timeout=12)
            if status == 200:
                return True, "Razorpay keys are valid"
            return False, _error_text(status, body)

        if gw == "cashfree":
            status, body = await _http("GET", f"{_cf_base(cfg)}/links/test_ping_000",
                                       headers=_cf_headers(cfg), timeout=12)
            if status in (404, 400, 200):
                return True, f"Cashfree keys accepted (HTTP {status})"
            return False, _error_text(status, body)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    return False, "Unknown gateway"


async def extract_upi_payload(payment_url: str):
    """Demotry ke payment page se asli UPI payload (upi://pay?...) nikalta hai (sirf Demotry ke liye)."""
    headers = {"User-Agent": _BROWSER_UA}
    upi_id = await get_upi_id()

    for attempt in range(1, 3):
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(payment_url, headers=headers) as resp:
                    if resp.status == 200:
                        html_content = await resp.text()

                        upi_match = re.search(r'upi://pay\?[^\s"\'<>]+', html_content)
                        if upi_match:
                            return upi_match.group(0)

                        amount_match = re.search(r'am=([0-9.]+)', html_content)
                        order_match = re.search(r'tr=([a-zA-Z0-9_\-]+)', html_content)
                        vpa_match = re.search(r'pa=([a-zA-Z0-9.\-_]+@[a-zA-Z0-9]+)', html_content)

                        vpa = vpa_match.group(1) if vpa_match else upi_id
                        amt = amount_match.group(1) if amount_match else None
                        oid = order_match.group(1) if order_match else None

                        if amt and oid:
                            return f"upi://pay?pa={vpa}&pn=StorySeller&am={amt}&cu=INR&tr={oid}&tn={oid}"
                        return None  # page mila par UPI data nahi -> retry se kuch nahi badlega
        except Exception as e:
            print(f"⚠ extract_upi_payload attempt {attempt} failed: {type(e).__name__}: {e}")
        await asyncio.sleep(1)
    return None
