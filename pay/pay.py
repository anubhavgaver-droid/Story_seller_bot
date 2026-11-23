"""
PAY WITH ANY UPI APP  (folder: pay/)

An extra button under "Verify payment" on the QR invoice (automatic UPI payments):

    📲 Pay with any UPI app   ->  opens a checkout page in CHROME (not in Telegram's small browser)

The checkout page shows the story, the price, the order id and a countdown, then 4 popular UPI app buttons + "Other UPI app".
A tap opens that app with the payee, the amount and the order id already filled in. When the user comes back from the
UPI app the page checks the payment by itself. A Verify button (with a moving moon 🌑🌒🌓🌔🌕🌖🌗🌘 on it) is on the page too.
When the payment is verified the page shows "Return to the bot".

How it works
  * The button in the bot is a Telegram Mini App button for /payopen. That tiny page calls
    Telegram.WebApp.openLink(url, {try_browser: "chrome"}) and the checkout page (/pay) opens in the browser.
  * Everything on /pay is authorised by a signed, expiring link token (order id + user id). Nothing else is needed,
    the browser has no Telegram login.
  * Verification uses exactly the same code as the Verify button of the bot (same gateway check, same UTR logic,
    same fulfill_order, so the user gets the same congratulations card in the bot).

Routes (registered by setup_pay_routes)
  GET  /payopen          launcher (runs inside Telegram)
  GET  /pay              checkout page (runs in Chrome)
  POST /api/pay/order    {k}        order details for the page
  POST /api/pay/verify   {k}        check the payment
  POST /api/pay/utr      {k, utr}   send the UTR (only when the bot asks for it) and check
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

from aiohttp import web

from config import BOT_TOKEN, WEB_APP_URL
from database.db import get_payment_order, set_order_utr

PAY_DIR = os.path.dirname(os.path.abspath(__file__))
_KEY = hashlib.sha256(("pay-v1|" + str(BOT_TOKEN)).encode()).digest()
EXTRA_TTL = 15 * 60                 # the link works this long after the order itself expires
MIN_GAP = 3.0                       # seconds between two real checks of one order (the page may retry by itself)
UPI_PROVIDERS = ("email", "demotry")  # the automatic payments that show a UPI QR code

_PAGES = {}
_LAST = {}                          # order_id -> (time, result)
_LOCKS = {}
_BOT = {"username": None, "t": 0.0}


# ------------------------------- link token -------------------------------
def make_token(order_id: str, user_id: int, ttl: int) -> str:
    payload = {"o": str(order_id), "u": int(user_id), "e": int(time.time() + ttl)}
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=")
    return raw.decode() + "." + hmac.new(_KEY, raw, hashlib.sha256).hexdigest()[:32]


def read_token(token: str):
    try:
        raw, sig = (token or "").rsplit(".", 1)
        if not hmac.compare_digest(hmac.new(_KEY, raw.encode(), hashlib.sha256).hexdigest()[:32], sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        return payload if int(payload["e"]) >= time.time() else None
    except Exception:
        return None


def order_ttl(order: dict) -> int:
    """How long an order stays payable (the time limit printed on the invoice)."""
    if order.get("provider") == "email":
        try:
            import emailpay
            return int(emailpay.ORDER_TTL)
        except Exception:
            return 1800
    if order.get("provider") == "demotry":
        return 600
    return 1800


def supports(order: dict) -> bool:
    return bool(order) and order.get("provider") in UPI_PROVIDERS and order.get("kind") in ("STORY", "WALLET") and order.get("status") != "PAID"


def checkout_url(order: dict) -> str:
    token = make_token(order["order_id"], order["user_id"], order_ttl(order) + EXTRA_TTL)
    return f"{WEB_APP_URL.rstrip('/')}/payopen?k={token}"


def checkout_button(order: dict, label: str):
    """The inline button for the invoice (a Mini App button that opens Chrome). None when it does not apply."""
    try:
        if not supports(order) or not WEB_APP_URL:
            return None
        from pyrogram import enums
        from pyrogram.types import InlineKeyboardButton, WebAppInfo
        try:
            return InlineKeyboardButton(label, web_app=WebAppInfo(url=checkout_url(order)), style=enums.ButtonStyle.PRIMARY)
        except TypeError:
            return InlineKeyboardButton(label, web_app=WebAppInfo(url=checkout_url(order)))
    except Exception as e:
        print(f"[pay] checkout button error: {type(e).__name__}: {e}")
        return None


# ------------------------------- the UPI link the apps open -------------------------------
async def upi_link(order: dict) -> str:
    """upi://pay?... with payee, amount, currency and the order id as the note."""
    link = str(order.get("pay_url") or "")
    amount = f"{float(order.get('amount') or 0):.2f}"
    order_id = order["order_id"]
    if not link.startswith("upi://"):
        link = ""
        try:
            from gateway import extract_upi_payload
            if str(order.get("pay_url") or "").startswith("http"):
                link = await extract_upi_payload(order["pay_url"]) or ""
        except Exception:
            link = ""
        if not link.startswith("upi://"):
            try:
                from gateway import get_upi_id
                link = f"upi://pay?pa={await get_upi_id()}&pn=StorySeller&am={amount}&cu=INR"
            except Exception:
                return ""
    parts = urlsplit(link)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["am"] = amount
    query.setdefault("pn", "StorySeller")
    query["cu"] = "INR"
    query["tn"] = order_id
    if order.get("provider") == "demotry":
        query.setdefault("tr", order_id)
    return "upi://pay?" + urlencode(query)


async def bot_username(bot):
    if _BOT["username"] and time.time() - _BOT["t"] < 6 * 3600:
        return _BOT["username"]
    try:
        me = await asyncio.wait_for(bot.get_me(), 8)
        _BOT.update(username=me.username, t=time.time())
    except Exception:
        pass
    return _BOT["username"]


# ------------------------------- checking the payment -------------------------------
_MESSAGES = {
    "wait": "Payment not found yet.",
    "used": "This UTR was already used.",
    "error": "The payment could not be checked right now. Please try again in a minute.",
}


async def _check(bot, order: dict) -> dict:
    """The same check as the bot's Verify button. Returns {"status": paid | wait | no_utr | used | error | update_failed}."""
    if order.get("status") == "PAID":
        return {"status": "paid"}
    import emailpay
    from fulfill import fulfill_order
    from gateway import check_order_status

    if order.get("provider") == "email":
        status, amount = await emailpay.verify_order_utr(order)
        if status == "no_utr":
            return {"status": "no_utr"}
        valid = status == "paid"
        reason = status
    else:
        valid, amount, _msg = await check_order_status(order["order_id"])
        reason = "wait"

    if not valid:
        return {"status": reason if reason in _MESSAGES else "wait"}

    result = await fulfill_order(bot, order, amount, "WEB VERIFY")
    try:                                              # the bot keeps a note of the open payment of a user
        import importlib
        importlib.import_module("plugins.payment").ACTIVE_PAYMENTS.pop(order["user_id"], None)
    except Exception:
        pass
    return {"status": "paid" if result in ("done", "already") else "update_failed"}


async def verify_order(bot, order_id: str, force: bool = False) -> dict:
    lock = _LOCKS.setdefault(order_id, asyncio.Lock())
    async with lock:
        hit = _LAST.get(order_id)
        if hit and not force and time.time() - hit[0] < MIN_GAP and hit[1]["status"] != "paid":
            return hit[1]
        order = await get_payment_order(order_id)
        if not order:
            return {"status": "missing"}
        try:
            result = await _check(bot, order)
        except Exception as e:
            print(f"[pay] check error: {type(e).__name__}: {e}")
            result = {"status": "error"}
        _LAST[order_id] = (time.time(), result)
        if len(_LAST) > 5000:
            cutoff = time.time() - 3600
            for k in [k for k, v in _LAST.items() if v[0] < cutoff]:
                _LAST.pop(k, None)
                _LOCKS.pop(k, None)
        return result


# ------------------------------- HTTP -------------------------------
def _json(data, status=200):
    return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})


def _page(name: str):
    if name not in _PAGES:
        path = os.path.join(PAY_DIR, name)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            _PAGES[name] = f.read()
    return _PAGES[name]


async def handle_launcher(request):
    html = _page("open.html")
    if html is None:
        return web.Response(text="pay/open.html not found", status=404)
    return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-cache"})


async def handle_page(request):
    html = _page("pay.html")
    if html is None:
        return web.Response(text="pay/pay.html not found", status=404)
    return web.Response(text=html, content_type="text/html",
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex"})


async def _read(request):
    try:
        body = await request.json()
    except Exception:
        return None, None, _json({"error": "bad_request"}, 400)
    tok = read_token(str(body.get("k") or ""))
    if not tok:
        return None, None, _json({"error": "expired"}, 401)
    return body, tok, None


async def handle_order(request):
    body, tok, err = await _read(request)
    if err:
        return err
    order = await get_payment_order(tok["o"])
    if not order or int(order["user_id"]) != int(tok["u"]):
        return _json({"error": "not_found"}, 404)
    bot = request.app.get("pay_bot_getter", lambda: None)()
    ttl = order_ttl(order)
    title = (order.get("title") or ("Wallet top-up" if order.get("kind") == "WALLET" else "Payment")).strip().split("\n")[0]
    username = await bot_username(bot) if bot is not None else _BOT["username"]
    upi = await upi_link(order)
    query = dict(parse_qsl(urlsplit(upi).query)) if upi else {}
    return _json({
        "order_id": order["order_id"], "title": title, "amount": f"{float(order.get('amount') or 0):.2f}",
        "kind": order.get("kind"), "status": "paid" if order.get("status") == "PAID" else "open",
        "created_at": order.get("created_at"), "expires_at": float(order.get("created_at") or time.time()) + ttl,
        "now": time.time(), "upi": upi, "payee": query.get("pa", ""), "payee_name": query.get("pn", ""),
        "bot_url": f"https://t.me/{username}" if username else "",
        "supported": order.get("provider") in UPI_PROVIDERS,
    })


async def handle_verify(request):
    body, tok, err = await _read(request)
    if err:
        return err
    order = await get_payment_order(tok["o"])
    if not order or int(order["user_id"]) != int(tok["u"]):
        return _json({"error": "not_found"}, 404)
    bot = request.app.get("pay_bot_getter", lambda: None)()
    if bot is None:
        return _json({"status": "error", "message": "The bot is starting. Try again in a few seconds."})
    result = await verify_order(bot, order["order_id"])
    result["message"] = _MESSAGES.get(result["status"], "")
    return _json(result)


async def handle_utr(request):
    body, tok, err = await _read(request)
    if err:
        return err
    utr = re.sub(r"\s+", "", str(body.get("utr") or ""))
    if not re.fullmatch(r"\d{12}", utr):
        return _json({"status": "bad_utr", "message": "The UTR is exactly 12 digits."})
    order = await get_payment_order(tok["o"])
    if not order or int(order["user_id"]) != int(tok["u"]) or order.get("provider") != "email":
        return _json({"error": "not_found"}, 404)
    bot = request.app.get("pay_bot_getter", lambda: None)()
    if bot is None:
        return _json({"status": "error", "message": "The bot is starting. Try again in a few seconds."})
    await set_order_utr(order["order_id"], utr)
    result = await verify_order(bot, order["order_id"], force=True)
    result["message"] = _MESSAGES.get(result["status"], "")
    return _json(result)


def setup_pay_routes(app, get_bot):
    """Call once from main.py: setup_pay_routes(app_web, lambda: bot_instance)."""
    app["pay_bot_getter"] = get_bot
    app.router.add_get("/payopen", handle_launcher)
    app.router.add_get("/pay", handle_page)
    app.router.add_post("/api/pay/order", handle_order)
    app.router.add_post("/api/pay/verify", handle_verify)
    app.router.add_post("/api/pay/utr", handle_utr)
