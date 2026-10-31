"""
demotry.shop payment gateway helpers (payment.py aur main.py dono yahin se use karte hain).

Pehle ki dikkatein jo yahan theek ki gayi hain:
  * order banne me fail hone par bot chupchaap ek nakli QR bhej deta tha (jo kabhi verify nahi hota)
  * koi retry nahi tha, aur gateway ka asli jawab / error kabhi log nahi hota tha
  * order_id sirf user_id + second se banta tha -> ek hi second me do click par duplicate
"""
import re
import json
import time
import asyncio
import secrets
import aiohttp

from config import (
    BOT_USERNAME, UPI_ID, CREATE_ORDER_URL, CHECK_STATUS_URL,
    API_KEY_VALUE, API_SECRET_VALUE, PAYMENT_CALLBACK_URL
)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# In HTTP codes par dobara try karna bekaar hai (key/request galat hai)
_NO_RETRY_STATUS = {400, 401, 403, 404, 422}


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY_VALUE.strip(),
        "X-API-Secret": API_SECRET_VALUE.strip(),
    }


def new_order_id(user_id: int) -> str:
    """Hamesha unique: user + time + random. callback_data me bhi chhota rehta hai."""
    return f"ORD_{user_id}_{int(time.time())}_{secrets.token_hex(3)}"


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


async def create_order(user_id: int, user_name: str, amount: float, attempts: int = 3):
    """
    Returns (pay_url, order_id, error_text).
    pay_url None ho to error_text me wajah hoti hai (logs me bhi print hota hai).
    """
    last_err = "unknown error"
    order_id = new_order_id(user_id)

    for attempt in range(1, attempts + 1):
        order_id = new_order_id(user_id)  # har attempt par naya id: timeout ke baad duplicate-order error nahi aayega
        payload = {
            "amount": float(amount),
            "order_id": order_id,
            "customer_name": user_name or "Telegram User",
            "customer_mobile": "9999999999",
            "redirect_url": f"https://t.me/{BOT_USERNAME}",
            "callback_url": PAYMENT_CALLBACK_URL,
        }
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(CREATE_ORDER_URL, json=payload, headers=_headers()) as resp:
                    body = await resp.text()

                    if resp.status in (200, 201):
                        try:
                            data = json.loads(body)
                        except Exception:
                            data = {}
                        pay_url = _pick_url(data)
                        if pay_url:
                            return pay_url, order_id, None
                        last_err = f"HTTP {resp.status} but no payment url in reply: {body[:300]}"
                    else:
                        last_err = f"HTTP {resp.status}: {body[:300]}"
                        if resp.status in _NO_RETRY_STATUS:
                            print(f"❌ create_order failed (no retry): {last_err}")
                            return None, order_id, last_err
        except asyncio.TimeoutError:
            last_err = "gateway timeout"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"

        print(f"⚠ create_order attempt {attempt}/{attempts} failed -> {last_err}")
        if attempt < attempts:
            await asyncio.sleep(1.5 * attempt)

    print(f"❌ create_order gave up: {last_err}")
    return None, order_id, last_err


async def check_order_status(order_id: str, attempts: int = 2):
    """Returns (is_paid, paid_amount, message)."""
    payload = {"order_id": order_id}
    last_msg = "Connection Error"

    for attempt in range(1, attempts + 1):
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(CHECK_STATUS_URL, json=payload, headers=_headers()) as resp:
                    body = await resp.text()
                    if resp.status == 200:
                        try:
                            data = json.loads(body)
                        except Exception:
                            data = {}
                        res_data = data.get("data", {}) if isinstance(data.get("data"), dict) else data

                        status = str(
                            res_data.get("payment_status") or res_data.get("status") or data.get("status") or ""
                        ).upper()
                        try:
                            paid_amt = float(res_data.get("amount", 0) or data.get("amount", 0) or 0)
                        except (TypeError, ValueError):
                            paid_amt = 0.0

                        if status in ("SUCCESS", "PAID", "COMPLETED"):
                            return True, paid_amt, "Payment Verified Successfully"
                        return False, 0.0, f"Status: {status if status else 'PENDING'}"

                    last_msg = f"Server Error (HTTP {resp.status}): {body[:200]}"
        except Exception as e:
            last_msg = f"Connection Error: {type(e).__name__}: {e}"

        if attempt < attempts:
            await asyncio.sleep(1.5)

    print(f"⚠ check_order_status({order_id}) -> {last_msg}")
    return False, 0.0, last_msg


async def extract_upi_payload(payment_url: str):
    """Gateway ke payment page se asli UPI payload (upi://pay?...) nikalta hai."""
    headers = {"User-Agent": _BROWSER_UA}

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

                        vpa = vpa_match.group(1) if vpa_match else UPI_ID
                        amt = amount_match.group(1) if amount_match else None
                        oid = order_match.group(1) if order_match else None

                        if amt and oid:
                            return f"upi://pay?pa={vpa}&pn=StorySeller&am={amt}&cu=INR&tr={oid}&tn={oid}"
                        return None  # page mila par UPI data nahi -> retry se kuch nahi badlega
        except Exception as e:
            print(f"⚠ extract_upi_payload attempt {attempt} failed: {type(e).__name__}: {e}")
        await asyncio.sleep(1)
    return None
