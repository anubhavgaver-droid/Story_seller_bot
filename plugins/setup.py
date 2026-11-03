"""
/setup (or /payments) - Payment, ads and bonus setup panel for the admin.

Everything is configured from inside the bot (no Render variable edits needed):
  - Payment gateway: Demotry.shop / Razorpay / Cashfree  (API key, secret, mode, test, activate)
  - Manual-payment UPI ID
  - Auto Pay ON / Maintenance
  - Free-story ads (URL shortener): ON/OFF, API URL, API key, minimum wait, test
  - Wallet top-up bonus: ON/OFF, minimum amount, percent

How input works:
  - The pending step is stored in the DATABASE, so it survives restarts and Render sleep.
  - Values are cleaned tolerantly (spaces, line breaks, "X-API-Key: ...", quotes, pasted headers, extra words).
  - If a value is rejected, the bot says exactly why.
  - Alternative: /setkey <target> <field> <value>
A secret you send is deleted from the chat as soon as it is saved.

IMPORTANT (Pyrogram): message.stop_propagation() raises an exception immediately, so it must be the very
LAST thing a handler does. Calling it first (as v1.0.22 did) silently skipped the saving and the reply.
"""
import re
import time

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply

from config import ADMIN_ID, WEB_APP_URL, BOT_USERNAME
from database.db import get_setting, set_setting, settings_col
from gateway import GATEWAYS, load_config, is_configured, mask, test_gateway
from freeflow import get_ads_config, ads_ready, shorten_url
from bonus import get_bonus_config
from style import sc

PROMPT_MARK = "⌨️"          # every input prompt starts with this (used to detect an expired session)
STATE_TTL = 30 * 60         # 30 minutes

UPI_RE = re.compile(r"[A-Za-z0-9.\-_]{2,}@[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s`'\"<>]+")

ADS_FIELDS = {
    "api_url": {"label": "Shortener API URL",
                "hint": "Example: <code>https://gplinks.in/api</code>\nThe bot adds <code>?api=KEY&amp;url=LINK</code> by itself."},
    "api_key": {"label": "Shortener API Key", "hint": "The API key / token from your shortener account."},
    "min_seconds": {"label": "Minimum wait (seconds)",
                    "hint": "A user must stay at least this long on the ad link before the claim is accepted (for example 15)."},
}

BONUS_FIELDS = {
    "min_amount": {"label": "Minimum top-up (₹)", "hint": "The smallest top-up that earns a bonus (for example 100)."},
    "percent": {"label": "Bonus percent", "hint": "Extra percent credited on top of the top-up (for example 10)."},
}


def _btn(text, data):
    return InlineKeyboardButton(text, callback_data=data)


# ------------------------------- DB-backed input state -------------------------------
async def _get_state(admin_id: int):
    s = await get_setting(f"setup_state_{admin_id}")
    if s and (time.time() - s.get("t", 0)) < STATE_TTL:
        return s
    return None


async def _set_state(admin_id: int, data: dict):
    data = dict(data)
    data["t"] = time.time()
    await set_setting(f"setup_state_{admin_id}", data)


async def _clear_state(admin_id: int):
    await set_setting(f"setup_state_{admin_id}", None)


async def _save(path: str, value, root: str = "gateway_config"):
    await settings_col.update_one({"key": root}, {"$set": {f"value.{path}": value}}, upsert=True)


# ------------------------------- value cleaning / validation -------------------------------
def _clean_value(raw: str, field: str = "") -> str:
    """
    Cleans what the admin pasted:
      "X-API-Key: pi_live_abc"         -> pi_live_abc
      "api_key=abc"                    -> abc
      "pi_live_abcX-API-Secret: sk_.." -> the right half for the field (the docs show both headers joined)
      `quotes`, spaces, line breaks    -> removed
    """
    v = (raw or "").strip()

    low = v.lower()
    if "x-api-secret" in low:
        i = low.index("x-api-secret")
        left, right = v[:i], v[i + len("x-api-secret"):]
        v = right if field in ("api_secret", "key_secret", "client_secret") else left
        v = re.sub(r"^\s*[:=]\s*", "", v)

    m = re.match(r"^\s*[A-Za-z][A-Za-z0-9_\- ]{1,40}\s*[:=]\s*(\S.*)$", v, re.S)
    if m and not v.lower().startswith(("http://", "https://")):
        v = m.group(1)

    v = v.strip().strip("`'\"“”‘’ ")
    return re.sub(r"\s+", "", v)


def _validate_gateway_value(gw: str, field: str, value: str):
    """Returns (ok, error_text)."""
    spec = next((f for f in GATEWAYS[gw]["fields"] if f["name"] == field), None)
    if not spec:
        return False, "Unknown field."
    if not value:
        return False, "The value is empty."
    need = spec.get("min", 1)
    if len(value) < need:
        return False, f"That value is too short ({len(value)} characters, at least {need} needed)."
    if spec.get("prefix") and not value.startswith(spec["prefix"]):
        return False, f"It must start with <code>{spec['prefix']}</code> (you sent <code>{value[:6]}…</code>)."
    if spec.get("choices") and value not in spec["choices"]:
        return False, f"Only these values are allowed: {', '.join(spec['choices'])}."
    return True, ""


def _extract_upi(raw: str):
    m = UPI_RE.search(raw or "")
    return m.group(0) if m else None


def _validate_ads_value(field: str, raw: str):
    """Returns (ok, value_or_error)."""
    if field == "api_url":
        m = URL_RE.search(raw or "")
        if not m:
            return False, "The API URL must start with <code>https://</code>."
        return True, m.group(0).rstrip(".,;)")
    v = _clean_value(raw, field)
    if field == "api_key":
        if len(v) < 4:
            return False, "That API key is too short."
        return True, v
    if field == "min_seconds":
        if not v.isdigit() or not (0 <= int(v) <= 600):
            return False, "Send a whole number between 0 and 600."
        return True, int(v)
    return False, "Unknown field."


def _validate_bonus_value(field: str, raw: str):
    v = _clean_value(raw, field).replace(",", "")
    try:
        num = float(v)
    except ValueError:
        return False, "Send a number, for example <code>100</code>."
    if field == "min_amount":
        if not (1 <= num <= 100000):
            return False, "The minimum top-up must be between 1 and 100000."
        return True, num
    if field == "percent":
        if not (0 < num <= 100):
            return False, "The percent must be above 0 and at most 100."
        return True, num
    return False, "Unknown field."


# ------------------------------- PANELS -------------------------------
async def _home_panel():
    cfg = await load_config()
    ads = await get_ads_config()
    bonus = await get_bonus_config()
    maintenance = await get_setting("auto_pay_maintenance", True)
    active = cfg["active"]
    spec = GATEWAYS.get(active, GATEWAYS["demotry"])
    ready = "keys saved ✅" if is_configured(active, cfg) else "keys missing ❌"
    auto = "🛠 Under maintenance (OFF)" if maintenance else "✅ ON"
    ads_state = "✅ ON" if ads_ready(ads) else ("⚠️ ON, setup incomplete" if ads.get("enabled") else "❌ OFF")
    bonus_state = f"✅ {bonus['percent']:g}% from ₹{bonus['min_amount']:g}" if bonus.get("enabled") else "❌ OFF"

    text = (
        f"⚙️ <b>{sc('Payment & Ads Setup')}</b>\n\n"
        f"💳 <b>{sc('Active gateway')}:</b> {spec['title']} ({ready})\n"
        f"⚡ <b>{sc('Auto pay')}:</b> {auto}\n"
        f"🏦 <b>{sc('Manual UPI ID')}:</b> <code>{cfg['upi_id']}</code>\n"
        f"🎁 <b>{sc('Free story ads')}:</b> {ads_state}\n"
        f"💰 <b>{sc('Top-up bonus')}:</b> {bonus_state}\n\n"
        "<i>Everything is set from here. No need to edit Render variables.</i>"
    )
    toggle_label = "🛠 Put Auto Pay under maintenance" if not maintenance else "✅ Turn Auto Pay ON"
    rows = [
        [_btn(f"💳 {sc('Payment gateway')}", "st:gws")],
        [_btn(f"🏦 {sc('Change UPI ID')}", "st:upi")],
        [_btn(sc(toggle_label), "st:toggle")],
        [_btn(f"🎁 {sc('Free story ads')}", "st:ads"), _btn(f"💰 {sc('Top-up bonus')}", "st:bonus")],
        [_btn(f"🔌 {sc('Test active gateway')}", "st:test")],
        [_btn(f"🏠 {sc('Admin panel')}", "ap:home"), _btn(f"❌ {sc('Close')}", "st:close")],
    ]
    return text, InlineKeyboardMarkup(rows)


async def _gateways_panel():
    cfg = await load_config()
    rows = []
    for gw, spec in GATEWAYS.items():
        status = "✅" if is_configured(gw, cfg) else "⚠️"
        active = " 🟢 ACTIVE" if cfg["active"] == gw else ""
        rows.append([_btn(f"{status} {spec['title']}{active}", f"st:gw:{gw}")])
    rows.append([_btn(f"⬅️ {sc('Back')}", "st:home")])
    text = (
        f"💳 <b>{sc('Payment gateway')}</b>\n\n"
        "Tap a gateway, enter its keys, then press <b>Make active</b>.\n"
        "✅ = keys saved   ⚠️ = keys missing"
    )
    return text, InlineKeyboardMarkup(rows)


async def _gateway_panel(gw: str):
    cfg = await load_config()
    spec = GATEWAYS[gw]
    is_active = cfg["active"] == gw
    lines = [f"💳 <b>{spec['title']}</b>{' 🟢 ACTIVE' if is_active else ''}\n"]
    rows = []

    for f in spec["fields"]:
        val = cfg[gw].get(f["name"]) or ""
        if f.get("choices"):
            lines.append(f"• <b>{f['label']}:</b> <code>{val or f['choices'][0]}</code>")
            rows.append([
                _btn(("✓ " if (val or f["choices"][0]) == c else "") + c, f"st:v:{gw}:{f['name']}:{c}")
                for c in f["choices"]
            ])
        else:
            shown = f"✅ <code>{mask(val)}</code>" if val else "❌ not set"
            lines.append(f"• <b>{f['label']}:</b> {shown}")
            rows.append([_btn(f"✏️ {f['label']}", f"st:f:{gw}:{f['name']}")])

    lines.append("\n" + spec["note"].format(web=WEB_APP_URL.rstrip("/")))
    lines.append(f"\n<i>If a value is not accepted, use: <code>/setkey {gw} &lt;field&gt; &lt;value&gt;</code></i>")

    action_row = []
    if is_configured(gw, cfg) and not is_active:
        action_row.append(_btn(f"🟢 {sc('Make active')}", f"st:act:{gw}"))
    action_row.append(_btn(f"🔌 {sc('Test')}", f"st:tg:{gw}"))
    rows.append(action_row)
    rows.append([_btn(f"🗑 {sc('Remove keys')}", f"st:clr:{gw}")])
    rows.append([_btn(f"⬅️ {sc('Back')}", "st:gws")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _ads_panel():
    ads = await get_ads_config()
    state = "✅ ON" if ads.get("enabled") else "❌ OFF"
    ready = "ready ✅" if ads_ready(ads) else "URL / key missing ⚠️"
    key = f"✅ <code>{mask(ads['api_key'])}</code>" if ads.get("api_key") else "❌ not set"
    text = (
        f"🎁 <b>{sc('Free story ads (shortener)')}</b>\n\n"
        f"• <b>Status:</b> {state}  ({ready})\n"
        f"• <b>API URL:</b> <code>{ads.get('api_url') or '—'}</code>\n"
        f"• <b>API key:</b> {key}\n"
        f"• <b>Minimum wait:</b> {ads.get('min_seconds')} seconds\n\n"
        "<b>How it works:</b> the user taps Claim Free, the bot sends a shortener ad link, the user completes the "
        "ad steps and returns to the bot, and the story unlocks.\n"
        "If ads are OFF, Claim Free unlocks the story directly. If the shortener fails, the user is not blocked "
        "(the story unlocks and you get a log message).\n\n"
        "<i>To make a story free, set its price to <code>0</code> in /addstory.</i>"
    )
    rows = [
        [_btn(f"🔴 {sc('Turn ads OFF')}" if ads.get("enabled") else f"🟢 {sc('Turn ads ON')}", "st:adtog")],
        [_btn(f"✏️ {sc('Shortener API URL')}", "st:adf:api_url")],
        [_btn(f"✏️ {sc('Shortener API key')}", "st:adf:api_key")],
        [_btn(f"✏️ {sc('Minimum wait')}", "st:adf:min_seconds")],
        [_btn(f"🔌 {sc('Test shortener')}", "st:adtest")],
        [_btn(f"⬅️ {sc('Back')}", "st:home")],
    ]
    return text, InlineKeyboardMarkup(rows)


async def _bonus_panel():
    b = await get_bonus_config()
    state = "✅ ON" if b.get("enabled") else "❌ OFF"
    text = (
        f"💰 <b>{sc('Wallet top-up bonus')}</b>\n\n"
        f"• <b>Status:</b> {state}\n"
        f"• <b>Minimum top-up:</b> ₹{b['min_amount']:g}\n"
        f"• <b>Bonus:</b> {b['percent']:g}%\n\n"
        f"Example: a ₹{b['min_amount']:g} top-up credits ₹{b['min_amount'] * (1 + b['percent'] / 100):g} to the wallet.\n"
        "The bonus is added automatically for gateway payments and for manually approved top-ups."
    )
    rows = [
        [_btn(f"🔴 {sc('Turn bonus OFF')}" if b.get("enabled") else f"🟢 {sc('Turn bonus ON')}", "st:bntog")],
        [_btn(f"✏️ {sc('Minimum top-up')}", "st:bnf:min_amount")],
        [_btn(f"✏️ {sc('Bonus percent')}", "st:bnf:percent")],
        [_btn(f"⬅️ {sc('Back')}", "st:home")],
    ]
    return text, InlineKeyboardMarkup(rows)


async def _show(callback, text, markup):
    try:
        await callback.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except MessageNotModified:
        pass
    except Exception:
        await callback.message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)


# ------------------------------- COMMANDS -------------------------------
@Client.on_message(filters.command(["setup", "payments"]) & filters.user(ADMIN_ID) & filters.private, group=1)
async def setup_command(client, message):
    await _clear_state(message.from_user.id)
    text, markup = await _home_panel()
    await message.reply_text(text, reply_markup=markup)


SETKEY_USAGE = (
    f"ℹ️ <b>{sc('Usage')}</b>\n"
    "<code>/setkey demotry api_key VALUE</code>\n"
    "<code>/setkey demotry api_secret VALUE</code>\n"
    "<code>/setkey razorpay key_id VALUE</code>\n"
    "<code>/setkey razorpay key_secret VALUE</code>\n"
    "<code>/setkey cashfree client_id VALUE</code>\n"
    "<code>/setkey cashfree client_secret VALUE</code>\n"
    "<code>/setkey upi yourname@bank</code>\n"
    "<code>/setkey ads api_url VALUE</code>  (also api_key, min_seconds)\n"
    "<code>/setkey bonus percent 10</code>  (also min_amount)\n\n"
    "<i>Your message is deleted right after it is saved.</i>"
)


@Client.on_message(filters.command("setkey") & filters.user(ADMIN_ID) & filters.private, group=1)
async def setkey_command(client, message):
    """Always-works alternative to the buttons: /setkey <target> <field> <value>"""
    parts = message.text.split(maxsplit=3)
    if len(parts) < 3:
        return await message.reply_text(SETKEY_USAGE)

    target = parts[1].lower()

    async def done(text):
        try:
            await message.delete()
        except Exception:
            pass
        await client.send_message(message.chat.id, text)

    if target == "upi":
        upi = _extract_upi(parts[2] + (" " + parts[3] if len(parts) > 3 else ""))
        if not upi:
            return await message.reply_text("❌ That does not look like a UPI ID. Example: <code>yourname@bank</code>")
        await _save("upi_id", upi)
        return await done(f"✅ <b>UPI ID saved:</b> <code>{upi}</code>")

    if len(parts) < 4:
        return await message.reply_text(SETKEY_USAGE)
    field, raw = parts[2], parts[3]

    if target == "ads":
        if field not in ADS_FIELDS:
            return await message.reply_text("❌ Ads fields: api_url, api_key, min_seconds")
        ok, value_or_err = _validate_ads_value(field, raw)
        if not ok:
            return await message.reply_text(f"❌ {value_or_err}")
        await _save(field, value_or_err, root="ads_config")
        return await done(f"✅ <b>{ADS_FIELDS[field]['label']}</b> saved.")

    if target == "bonus":
        if field not in BONUS_FIELDS:
            return await message.reply_text("❌ Bonus fields: min_amount, percent")
        ok, value_or_err = _validate_bonus_value(field, raw)
        if not ok:
            return await message.reply_text(f"❌ {value_or_err}")
        await _save(field, value_or_err, root="bonus_config")
        return await done(f"✅ <b>{BONUS_FIELDS[field]['label']}</b> saved.")

    if target not in GATEWAYS:
        return await message.reply_text("❌ Targets: demotry, razorpay, cashfree, upi, ads, bonus")
    value = _clean_value(raw, field)
    ok, err = _validate_gateway_value(target, field, value)
    if not ok:
        return await message.reply_text(f"❌ {err}")
    await _save(f"{target}.{field}", value)
    await done(f"✅ <b>{GATEWAYS[target]['title']} → {field}</b> saved (<code>{mask(value)}</code>).\nOpen /setup to activate it.")


# /cancel: stop a pending input (the /cancel in admin.py does its own job separately)
@Client.on_message(filters.command("cancel") & filters.user(ADMIN_ID) & filters.private, group=-1)
async def setup_cancel(client, message):
    if await _get_state(message.from_user.id):
        await _clear_state(message.from_user.id)
        await message.reply_text(f"❌ <b>{sc('Setup input cancelled')}</b>")


# ------------------------------- CALLBACKS -------------------------------
async def _ask(callback, admin_id, state, title, hint):
    await _set_state(admin_id, state)
    await callback.message.reply_text(
        f"{PROMPT_MARK} <b>{title}</b>\n\n{hint}\n\n"
        "<i>Send the value now. Your message is deleted as soon as it is saved. Send /cancel to stop.</i>",
        reply_markup=ForceReply(True)
    )
    await callback.answer()


@Client.on_callback_query(filters.regex(r"^st:") & filters.user(ADMIN_ID))
async def setup_callbacks(client, callback):
    parts = callback.data.split(":")
    action = parts[1]
    admin_id = callback.from_user.id

    if action == "home":
        await _clear_state(admin_id)
        text, markup = await _home_panel()
        return await _show(callback, text, markup)

    if action == "close":
        await _clear_state(admin_id)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return await callback.answer()

    if action == "gws":
        await _clear_state(admin_id)
        text, markup = await _gateways_panel()
        return await _show(callback, text, markup)

    if action == "gw":
        await _clear_state(admin_id)
        text, markup = await _gateway_panel(parts[2])
        return await _show(callback, text, markup)

    # ---- ask for one gateway field ----
    if action == "f":
        gw, field = parts[2], parts[3]
        spec = next((f for f in GATEWAYS[gw]["fields"] if f["name"] == field), None)
        if not spec:
            return await callback.answer("Field not found.", show_alert=True)
        return await _ask(
            callback, admin_id, {"kind": "field", "gw": gw, "field": field},
            f"{GATEWAYS[gw]['title']} → {spec['label']}", "Paste the value here exactly as shown in your dashboard."
        )

    # ---- fixed choices (for example Cashfree prod / sandbox) ----
    if action == "v":
        gw, field, value = parts[2], parts[3], parts[4]
        await _save(f"{gw}.{field}", value)
        await callback.answer(f"{value} selected")
        text, markup = await _gateway_panel(gw)
        return await _show(callback, text, markup)

    # ---- make a gateway active ----
    if action == "act":
        gw = parts[2]
        cfg = await load_config()
        if not is_configured(gw, cfg):
            return await callback.answer("Please save all the keys first.", show_alert=True)
        await _save("active", gw)
        maintenance = await get_setting("auto_pay_maintenance", True)
        hint = "\n\nAuto Pay is still under maintenance. Turn it ON from the main panel." if maintenance else ""
        await callback.answer(f"{GATEWAYS[gw]['title']} is now active.{hint}", show_alert=True)
        text, markup = await _gateway_panel(gw)
        return await _show(callback, text, markup)

    # ---- remove keys ----
    if action == "clr":
        gw = parts[2]
        await settings_col.update_one({"key": "gateway_config"}, {"$unset": {f"value.{gw}": ""}}, upsert=True)
        await callback.answer("Keys removed.", show_alert=True)
        text, markup = await _gateway_panel(gw)
        return await _show(callback, text, markup)

    # ---- gateway test ----
    if action in ("tg", "test"):
        cfg = await load_config()
        gw = parts[2] if action == "tg" else cfg["active"]
        await callback.answer("Testing the connection...")
        ok, msg = await test_gateway(gw)
        return await callback.message.reply_text(f"{'✅' if ok else '❌'} <b>{GATEWAYS[gw]['title']} test:</b> {msg}")

    # ---- UPI ID ----
    if action == "upi":
        return await _ask(
            callback, admin_id, {"kind": "upi"},
            "Manual payment UPI ID", "Example: <code>yourname@bank</code>"
        )

    # ---- Auto Pay ON / maintenance ----
    if action == "toggle":
        maintenance = await get_setting("auto_pay_maintenance", True)
        if maintenance:
            cfg = await load_config()
            if not is_configured(cfg["active"], cfg):
                return await callback.answer(
                    f"The {GATEWAYS[cfg['active']]['title']} keys are not saved yet. Add the keys first.",
                    show_alert=True
                )
            await set_setting("auto_pay_maintenance", False)
            await callback.answer("Auto Pay is now ON.", show_alert=True)
        else:
            await set_setting("auto_pay_maintenance", True)
            await callback.answer("Maintenance mode is ON. Users will see a popup.", show_alert=True)
        text, markup = await _home_panel()
        return await _show(callback, text, markup)

    # ================= FREE STORY ADS =================
    if action == "ads":
        await _clear_state(admin_id)
        text, markup = await _ads_panel()
        return await _show(callback, text, markup)

    if action == "adtog":
        ads = await get_ads_config()
        new_state = not ads.get("enabled")
        if new_state and not (ads.get("api_url") and ads.get("api_key")):
            return await callback.answer("Please save the shortener API URL and key first.", show_alert=True)
        await _save("enabled", new_state, root="ads_config")
        await callback.answer("Ads are ON." if new_state else "Ads are OFF.")
        text, markup = await _ads_panel()
        return await _show(callback, text, markup)

    if action == "adf":
        field = parts[2]
        if field not in ADS_FIELDS:
            return await callback.answer("Field not found.", show_alert=True)
        return await _ask(callback, admin_id, {"kind": "ads", "field": field}, ADS_FIELDS[field]["label"], ADS_FIELDS[field]["hint"])

    if action == "adtest":
        ads = await get_ads_config()
        if not (ads.get("api_url") and ads.get("api_key")):
            return await callback.answer("Please save the API URL and key first.", show_alert=True)
        await callback.answer("Testing the shortener...")
        short, err = await shorten_url(ads, f"https://t.me/{BOT_USERNAME}")
        if short:
            return await callback.message.reply_text(f"✅ <b>Shortener test passed</b>\n\n<code>{short}</code>")
        return await callback.message.reply_text(f"❌ <b>Shortener test failed:</b>\n<code>{err}</code>")

    # ================= TOP-UP BONUS =================
    if action == "bonus":
        await _clear_state(admin_id)
        text, markup = await _bonus_panel()
        return await _show(callback, text, markup)

    if action == "bntog":
        b = await get_bonus_config()
        await _save("enabled", not b.get("enabled"), root="bonus_config")
        await callback.answer("Bonus is ON." if not b.get("enabled") else "Bonus is OFF.")
        text, markup = await _bonus_panel()
        return await _show(callback, text, markup)

    if action == "bnf":
        field = parts[2]
        if field not in BONUS_FIELDS:
            return await callback.answer("Field not found.", show_alert=True)
        return await _ask(callback, admin_id, {"kind": "bonus", "field": field}, BONUS_FIELDS[field]["label"], BONUS_FIELDS[field]["hint"])

    await callback.answer()


# ------------------------------- VALUE INPUT -------------------------------
async def _process_input(client, message, state):
    """Does ALL the work for one pending setup step. Never raises StopPropagation itself."""
    admin_id = message.from_user.id
    raw = message.text

    async def finish(ok_text: str, panel):
        await _clear_state(admin_id)
        try:
            await message.delete()   # do not leave the secret in the chat
        except Exception:
            pass
        text, markup = panel
        await client.send_message(message.chat.id, f"{ok_text}\n\n{text}", reply_markup=markup, disable_web_page_preview=True)

    async def reject(reason: str):
        await message.reply_text(f"❌ <b>{reason}</b>\nPlease send it again, or send /cancel to stop.")

    kind = state["kind"]

    if kind == "upi":
        upi = _extract_upi(raw)
        if not upi:
            return await reject("That does not look like a UPI ID. Example: <code>yourname@bank</code>")
        await _save("upi_id", upi)
        return await finish(f"✅ <b>UPI ID saved:</b> <code>{upi}</code>", await _home_panel())

    if kind == "ads":
        field = state["field"]
        ok, value_or_err = _validate_ads_value(field, raw)
        if not ok:
            return await reject(value_or_err)
        await _save(field, value_or_err, root="ads_config")
        return await finish(f"✅ <b>{ADS_FIELDS[field]['label']} saved.</b>", await _ads_panel())

    if kind == "bonus":
        field = state["field"]
        ok, value_or_err = _validate_bonus_value(field, raw)
        if not ok:
            return await reject(value_or_err)
        await _save(field, value_or_err, root="bonus_config")
        return await finish(f"✅ <b>{BONUS_FIELDS[field]['label']} saved.</b>", await _bonus_panel())

    # ---- gateway field ----
    gw, field = state["gw"], state["field"]
    value = _clean_value(raw, field)
    ok, err = _validate_gateway_value(gw, field, value)
    if not ok:
        print(f"[setup] {gw}.{field} rejected: {err} (length {len(value)})")
        return await reject(err)

    await _save(f"{gw}.{field}", value)
    label = next(f["label"] for f in GATEWAYS[gw]["fields"] if f["name"] == field)
    await finish(f"✅ <b>{label} saved</b> (<code>{mask(value)}</code>).", await _gateway_panel(gw))


# group=-1 runs before the master input handler in admin.py, so a secret never reaches another handler.
@Client.on_message(filters.private & filters.user(ADMIN_ID) & filters.text & ~filters.command(
    ["start", "setup", "payments", "cancel", "setkey"]), group=-1)
async def setup_input(client, message):
    state = await _get_state(message.from_user.id)

    if not state:
        # The admin answered one of our prompts but the session has expired -> say so instead of staying silent.
        replied = message.reply_to_message
        if replied and replied.from_user and replied.from_user.is_self and (replied.text or "").startswith(PROMPT_MARK):
            await message.reply_text(
                "⚠️ <b>This setup session has expired.</b>\nOpen /setup and tap the field again, or use <code>/setkey</code>."
            )
            message.stop_propagation()          # LAST line: raises, so nothing after it would run
        return  # no setup in progress: the other handlers handle this message

    try:
        await _process_input(client, message, state)
    except Exception as e:
        print(f"[setup] input error: {type(e).__name__}: {e}")
        try:
            await message.reply_text("❌ <b>Something went wrong while saving.</b> Please try again, or use <code>/setkey</code>.")
        except Exception:
            pass

    # LAST line (it raises StopPropagation): the setup message never reaches any other handler.
    message.stop_propagation()
