"""
Free story claim + optional Ad (URL shortener) gate.

Flow (ads ON):
  user "Claim Free" dabata hai
    -> bot ek ek-baar-wala token banata hai
    -> https://t.me/<bot>?start=verify_<token> ko shortener se chhota karta hai
    -> user short link kholta hai (ads / steps poore karta hai) -> bot par wapas aata hai
    -> bot token check karta hai (user same, pehle use nahi hua, kam se kam N second guzre) -> story unlock

Flow (ads OFF ya shortener set nahi): seedha unlock.

NOTE: shortener ka "bypass" pooree tarah roka nahi ja sakta (user direct t.me link bana sakta hai agar use token
pata ho). Isliye token sirf us user ke liye, ek baar, aur minimum wait time ke saath chalta hai.
"""
import json
import time
import aiohttp
from urllib.parse import quote

from pyrogram import enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import BOT_USERNAME
from database.db import (
    get_setting,
    create_claim_token,
    set_claim_short_url,
    get_claim_token,
    use_claim_token,
    add_user_purchase,
    is_story_unlocked,
    get_story_by_key,
    delivery_link,
    send_log,
)

DEFAULT_ADS = {"enabled": False, "api_url": "", "api_key": "", "min_seconds": 15}
TOKEN_MAX_AGE = 24 * 3600


async def get_ads_config() -> dict:
    raw = await get_setting("ads_config", {}) or {}
    cfg = dict(DEFAULT_ADS)
    cfg.update({k: v for k, v in raw.items() if v is not None})
    try:
        cfg["min_seconds"] = int(cfg["min_seconds"])
    except (TypeError, ValueError):
        cfg["min_seconds"] = DEFAULT_ADS["min_seconds"]
    return cfg


def ads_ready(cfg: dict) -> bool:
    return bool(cfg.get("enabled") and (cfg.get("api_url") or "").startswith("http") and cfg.get("api_key"))


async def shorten_url(cfg: dict, target: str):
    """
    Returns (short_url, error). Common shortener API: GET <api_url>?api=<key>&url=<link>
    JSON ({"status":"success","shortenedUrl":"..."}) aur plain-text dono samajhta hai.
    """
    base = cfg["api_url"].strip()
    sep = "&" if "?" in base else "?"
    url = f"{base}{sep}api={quote(cfg['api_key'], safe='')}&url={quote(target, safe='')}"
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
                body = (await resp.text()).strip()
                if resp.status != 200:
                    return None, f"HTTP {resp.status}: {body[:120]}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

    try:
        data = json.loads(body)
    except Exception:
        data = None

    if isinstance(data, dict):
        status = str(data.get("status", "")).lower()
        if status in ("error", "fail", "failed"):
            return None, str(data.get("message") or data.get("msg") or body)[:150]
        for k in ("shortenedUrl", "shortened_url", "short_url", "shorturl", "result_url", "url", "link"):
            val = data.get(k)
            if isinstance(val, str) and val.startswith("http"):
                return val, None
        return None, f"short link nahi mila: {body[:120]}"

    if body.startswith("http") and " " not in body and "\n" not in body:
        return body, None
    return None, f"samajh nahi aaya: {body[:120]}"


# ------------------------------- helpers -------------------------------
def _clean_title(story) -> str:
    return story["title"].strip().split("\n")[0]


async def _send_access(client, user_id: int, story, text: str):
    link = delivery_link(story.get("story_id")) if story.get("story_id") else None
    markup = None
    if link:
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (Unlocked)", style=enums.ButtonStyle.PRIMARY, url=link)
        ]])
    await client.send_message(user_id, text, reply_markup=markup)


async def _grant(client, user_id: int, story, via: str = "FREE"):
    clean_title = _clean_title(story)
    await add_user_purchase(user_id, clean_title, story_id=story.get("story_id"))
    await _send_access(
        client, user_id, story,
        f"🎉 <b>ᴄʟᴀɪᴍᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n📖 <b>Story:</b> {clean_title}\n\nNeeche button se files le lein:"
    )
    try:
        await send_log(client, f"🎁 <b>[{via}] Free story claimed</b>\n\n👤 <code>{user_id}</code>\n📖 {clean_title}")
    except Exception:
        pass


# ------------------------------- public API -------------------------------
async def start_free_claim(client, user_id: int, story) -> str:
    """Returns 'already' | 'paid' | 'ad' | 'granted'."""
    clean_title = _clean_title(story)
    story_id = story.get("story_id")

    if await is_story_unlocked(user_id, clean_title, story_id):
        await _send_access(client, user_id, story, f"✅ <b>{clean_title}</b> aapke paas pehle se unlocked hai.")
        return "already"

    try:
        price = float(story.get("price", 0) or 0)
    except (TypeError, ValueError):
        price = 0.0
    if price > 0:
        await client.send_message(
            user_id,
            f"💎 <b>{clean_title}</b> free nahi hai (₹{price:g}).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 ʙᴜʏ ɴᴏᴡ", callback_data=f"buy:{story_id}")]])
        )
        return "paid"

    cfg = await get_ads_config()
    if ads_ready(cfg):
        token = await create_claim_token(user_id, story_id)
        target = f"https://t.me/{BOT_USERNAME}?start=verify_{token}"
        short_url, err = await shorten_url(cfg, target)
        if short_url:
            await set_claim_short_url(token, short_url)
            await client.send_message(
                user_id,
                f"🎁 <b>ғʀᴇᴇ sᴛᴏʀʏ:</b> {clean_title}\n\n"
                f"1️⃣ Neeche <b>Ad Link</b> kholein aur steps poore karein.\n"
                f"2️⃣ Aakhir me <b>Telegram / Bot</b> par wapas aayein, story apne aap unlock ho jayegi.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔗 ᴏᴘᴇɴ ᴀᴅ ʟɪɴᴋ", style=enums.ButtonStyle.PRIMARY, url=short_url)
                ]])
            )
            return "ad"

        # Shortener fail: user ko rokna nahi, seedha free (admin ko batao)
        print(f"⚠ Shortener failed: {err}")
        try:
            await send_log(client, f"⚠️ <b>Shortener fail hua, free story seedha unlock hui</b>\n\n<code>{err}</code>")
        except Exception:
            pass

    await _grant(client, user_id, story, "FREE")
    return "granted"


async def handle_free_deeplink(client, message, param: str):
    """/start free_<key>  ya  /start verify_<token>"""
    user = message.from_user

    # ---- free_<story key> ----
    if param.startswith("free_"):
        story = await get_story_by_key(param[len("free_"):])
        if not story:
            return await message.reply_text("❌ <b>sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ!</b>")
        await start_free_claim(client, user.id, story)
        return

    # ---- verify_<token> ----
    token = param[len("verify_"):]
    doc = await get_claim_token(token)
    if not doc:
        return await message.reply_text("❌ <b>Ye verify link galat ya purana hai.</b> Story page se dobara 'Claim Free' dabayein.")

    if doc["user_id"] != user.id:
        return await message.reply_text("❌ <b>Ye link kisi aur user ke liye bana tha.</b> Apne account se 'Claim Free' dabayein.")

    story = await get_story_by_key(doc["story_id"])
    if not story:
        return await message.reply_text("❌ <b>Story ab available nahi hai.</b>")

    if doc.get("used"):
        if await is_story_unlocked(user.id, _clean_title(story), story.get("story_id")):
            return await _send_access(client, user.id, story, "✅ <b>Ye story pehle hi claim ho chuki hai.</b>")
        return await message.reply_text("⚠️ <b>Ye link pehle use ho chuka hai.</b> Dobara 'Claim Free' dabayein.")

    age = time.time() - doc["created_at"]
    if age > TOKEN_MAX_AGE:
        return await message.reply_text("⌛ <b>Ye link expire ho gaya.</b> Dobara 'Claim Free' dabayein.")

    cfg = await get_ads_config()
    if age < cfg["min_seconds"]:
        markup = None
        if doc.get("short_url"):
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 ᴏᴘᴇɴ ᴀᴅ ʟɪɴᴋ", url=doc["short_url"])]])
        return await message.reply_text(
            "⏳ <b>Pehle ad ke steps poore karein.</b>\nAd link kholkar sab steps khatam karne ke baad hi story unlock hogi.",
            reply_markup=markup
        )

    claimed = await use_claim_token(token)
    if not claimed:
        return await message.reply_text("⚠️ <b>Ye link pehle use ho chuka hai.</b>")

    await _grant(client, user.id, story, "AD")


# ------------------------------- UI helpers (start.py / search.py use these) -------------------------------
def price_label(price) -> str:
    try:
        p = float(price or 0)
    except (TypeError, ValueError):
        p = 0.0
    return "FREE 🎁" if p <= 0 else f"₹{p:g}"


def buy_rows(encoded_title: str, price, wallet_bal) -> list:
    """Story page ke buttons: free ho to 'Claim Free', warna Direct Pay + Wallet Pay."""
    try:
        p = float(price or 0)
    except (TypeError, ValueError):
        p = 0.0
    if p <= 0:
        return [[InlineKeyboardButton("🎁 ᴄʟᴀɪᴍ ғʀᴇᴇ", style=enums.ButtonStyle.PRIMARY, callback_data=f"claim:{encoded_title}")]]
    return [
        [InlineKeyboardButton(f"💳 ᴅɪʀᴇᴄᴛ ᴘᴀʏ (₹{p:g})", style=enums.ButtonStyle.PRIMARY, callback_data=f"buy:{encoded_title}")],
        [InlineKeyboardButton(f"👛 ᴘᴀʏ ᴠɪᴀ ᴡᴀʟʟᴇᴛ (Bal: ₹{wallet_bal})", style=enums.ButtonStyle.PRIMARY, callback_data=f"walletpay:{encoded_title}")],
    ]
