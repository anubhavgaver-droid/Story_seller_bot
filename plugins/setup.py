"""
/setup  (ya /payments)  -  Admin ke liye payment + ads setup panel.

Yahin se sab set hota hai (Render me jaake variable nahi badalne padte):
  - Gateway chunna: Demotry.shop / Razorpay / Cashfree, aur unki API key / secret / mode
  - Manual payment ki UPI ID
  - Auto Pay ON / Maintenance
  - Free Story Ads (URL shortener) ON / OFF, API URL, API key, minimum wait
  - Keys ka "Test" (bina order banaye)

Input kaise lete hain (pehle kabhi-kabhi "accept nahi hota" tha, ab theek):
  - Setup ki state ab DATABASE me rehti hai, Render restart / sleep par bhi nahi khoti
  - Value tolerant tareeke se padhi jaati hai: space, line-break, "X-API-Key: ...", quotes, chipka hua header
  - Reject hone par saaf wajah batayi jaati hai
  - Dusra raasta: /setkey <gateway> <field> <value>
Admin ka bheja hua secret message save hote hi chat se delete ho jata hai.
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

PROMPT_MARK = "⌨️"          # har input-prompt isse shuru hota hai (expire hui session pehchanne ke liye)
STATE_TTL = 30 * 60         # 30 minute

UPI_RE = re.compile(r"^[A-Za-z0-9.\-_]{2,}@[A-Za-z]{2,}$")

ADS_FIELDS = {
    "api_url": {"label": "Shortener API URL", "hint": "jaise: <code>https://gplinks.in/api</code> (bot khud <code>?api=KEY&url=LINK</code> jodta hai)"},
    "api_key": {"label": "Shortener API Key", "hint": "shortener ki website se mili API key/token"},
    "min_seconds": {"label": "Minimum wait (second)", "hint": "ad kholne ke baad kam se kam itne second baad hi verify hoga (jaise 15)"},
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
    Admin ki bheji value saaf karo:
      "X-API-Key: pi_live_abc"        -> pi_live_abc
      "api_key=abc"                   -> abc
      "pi_live_abcX-API-Secret: sk_.."-> field ke hisaab se sahi hissa (docs ka header chipka hua copy hota hai)
      `quotes`, spaces, line-breaks   -> hata do
    """
    v = (raw or "").strip()

    # Dono headers chipke hue paste ho gaye
    low = v.lower()
    if "x-api-secret" in low:
        i = low.index("x-api-secret")
        left, right = v[:i], v[i + len("x-api-secret"):]
        v = right if field in ("api_secret", "key_secret", "client_secret") else left
        v = re.sub(r"^\s*[:=]\s*", "", v)

    # "Label: value" / "label=value"
    m = re.match(r"^\s*[A-Za-z][A-Za-z0-9_\- ]{1,40}\s*[:=]\s*(\S.*)$", v, re.S)
    if m and not v.lower().startswith(("http://", "https://")):
        v = m.group(1)

    v = v.strip().strip("`'\"“”‘’ ")
    return re.sub(r"\s+", "", v)


def _validate_gateway_value(gw: str, field: str, value: str):
    """Returns (ok, error_text)."""
    spec = next((f for f in GATEWAYS[gw]["fields"] if f["name"] == field), None)
    if not spec:
        return False, "Field nahi mila"
    if not value:
        return False, "Value khaali hai"
    need = spec.get("min", 1)
    if len(value) < need:
        return False, f"Value bahut chhoti hai ({len(value)} akshar, kam se kam {need} chahiye)"
    if spec.get("prefix") and not value.startswith(spec["prefix"]):
        return False, f"Ye <code>{spec['prefix']}</code> se shuru honi chahiye (aapne <code>{value[:6]}…</code> bheja)"
    if spec.get("choices") and value not in spec["choices"]:
        return False, f"Sirf ye chalega: {', '.join(spec['choices'])}"
    return True, ""


# ------------------------------- PANELS -------------------------------
async def _home_panel():
    cfg = await load_config()
    ads = await get_ads_config()
    maintenance = await get_setting("auto_pay_maintenance", True)
    active = cfg["active"]
    spec = GATEWAYS.get(active, GATEWAYS["demotry"])
    ready = "✅ keys set" if is_configured(active, cfg) else "❌ keys set nahi"
    auto = "🛠 Under Maintenance (BAND)" if maintenance else "✅ ON"
    ads_state = ("✅ ON" if ads_ready(ads) else ("⚠️ ON par setup adhoora" if ads.get("enabled") else "❌ OFF"))

    text = (
        "⚙️ <b>ᴘᴀʏᴍᴇɴᴛ & ᴀᴅs sᴇᴛᴜᴘ</b>\n\n"
        f"💳 <b>Active Gateway:</b> {spec['title']} ({ready})\n"
        f"⚡ <b>Auto Pay:</b> {auto}\n"
        f"🏦 <b>Manual UPI ID:</b> <code>{cfg['upi_id']}</code>\n"
        f"🎁 <b>Free Story Ads:</b> {ads_state}\n\n"
        "<i>Sab kuch yahin se set karein, Render me variable badalne ki zaroorat nahi.</i>"
    )
    toggle_label = "🛠 Maintenance lagayein (Auto Pay band)" if not maintenance else "✅ Auto Pay chalu karein"
    rows = [
        [_btn("💳 Payment Gateway chunein / Setup", "st:gws")],
        [_btn("🏦 UPI ID badlein (Manual payment)", "st:upi")],
        [_btn(toggle_label, "st:toggle")],
        [_btn("🎁 Free Story Ads (Shortener)", "st:ads")],
        [_btn("🔌 Active gateway Test", "st:test")],
        [_btn("🏠 Admin Panel", "ap:home"), _btn("❌ Close", "st:close")],
    ]
    return text, InlineKeyboardMarkup(rows)


async def _gateways_panel():
    cfg = await load_config()
    rows = []
    for gw, spec in GATEWAYS.items():
        status = "✅" if is_configured(gw, cfg) else "⚠️"
        active = " 🟢 ACTIVE" if cfg["active"] == gw else ""
        rows.append([_btn(f"{status} {spec['title']}{active}", f"st:gw:{gw}")])
    rows.append([_btn("⬅️ Back", "st:home")])
    text = (
        "💳 <b>Payment Gateway</b>\n\n"
        "Jo gateway chahiye uspe tap karein, uski keys daalein, phir <b>Active banayein</b> dabayein.\n"
        "✅ = keys set hain   ⚠️ = keys baaki hain"
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
            shown = f"✅ <code>{mask(val)}</code>" if val else "❌ set nahi"
            lines.append(f"• <b>{f['label']}:</b> {shown}")
            rows.append([_btn(f"✏️ {f['label']}", f"st:f:{gw}:{f['name']}")])

    lines.append("\n" + spec["note"].format(web=WEB_APP_URL.rstrip("/")))
    lines.append("\n<i>Value kaam na kare to: <code>/setkey " + gw + " &lt;field&gt; &lt;value&gt;</code></i>")

    action_row = []
    if is_configured(gw, cfg) and not is_active:
        action_row.append(_btn("🟢 Active banayein", f"st:act:{gw}"))
    action_row.append(_btn("🔌 Test", f"st:tg:{gw}"))
    rows.append(action_row)
    rows.append([_btn("🗑 Keys hatayein", f"st:clr:{gw}")])
    rows.append([_btn("⬅️ Back", "st:gws")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _ads_panel():
    ads = await get_ads_config()
    state = "✅ ON" if ads.get("enabled") else "❌ OFF"
    ready = "✅ taiyaar" if ads_ready(ads) else "⚠️ URL / Key baaki"
    text = (
        "🎁 <b>ғʀᴇᴇ sᴛᴏʀʏ ᴀᴅs (sʜᴏʀᴛɴᴇʀ)</b>\n\n"
        f"• <b>Status:</b> {state}  ({ready})\n"
        f"• <b>API URL:</b> <code>{ads.get('api_url') or '—'}</code>\n"
        f"• <b>API Key:</b> {('✅ <code>' + mask(ads['api_key']) + '</code>') if ads.get('api_key') else '❌ set nahi'}\n"
        f"• <b>Minimum wait:</b> {ads.get('min_seconds')} second\n\n"
        "<b>Kaise kaam karta hai:</b> user 'Claim Free' dabata hai → bot shortener ka ad link deta hai → "
        "user ad steps poore karke bot par wapas aata hai → story unlock.\n"
        "Ads OFF ho to Claim Free se story seedha unlock ho jati hai. "
        "Shortener fail ho jaye to bhi user ko rokte nahi (seedha unlock + aapko log).\n\n"
        "<i>Story free karne ke liye /addstory me price <code>0</code> rakhein.</i>"
    )
    rows = [
        [_btn("🔴 Ads band karein" if ads.get("enabled") else "🟢 Ads chalu karein", "st:adtog")],
        [_btn("✏️ Shortener API URL", "st:adf:api_url")],
        [_btn("✏️ Shortener API Key", "st:adf:api_key")],
        [_btn("✏️ Minimum wait (second)", "st:adf:min_seconds")],
        [_btn("🔌 Shortener Test", "st:adtest")],
        [_btn("⬅️ Back", "st:home")],
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


@Client.on_message(filters.command("setkey") & filters.user(ADMIN_ID) & filters.private, group=1)
async def setkey_command(client, message):
    """
    /setkey <gateway> <field> <value>      jaise: /setkey demotry api_key pi_live_xxx
    /setkey upi yourname@bank
    /setkey ads api_url https://gplinks.in/api     (ads: api_url | api_key | min_seconds)
    Bot ke buttons se value accept na ho to ye raasta hamesha chalta hai.
    """
    parts = message.text.split(maxsplit=3)
    usage = (
        "ℹ️ <b>Usage:</b>\n"
        "<code>/setkey demotry api_key VALUE</code>\n"
        "<code>/setkey demotry api_secret VALUE</code>\n"
        "<code>/setkey razorpay key_id VALUE</code>\n"
        "<code>/setkey razorpay key_secret VALUE</code>\n"
        "<code>/setkey cashfree client_id VALUE</code>\n"
        "<code>/setkey cashfree client_secret VALUE</code>\n"
        "<code>/setkey upi yourname@bank</code>\n"
        "<code>/setkey ads api_url VALUE</code> (api_key / min_seconds bhi)\n\n"
        "<i>Message save hote hi delete ho jayega.</i>"
    )
    if len(parts) < 3:
        return await message.reply_text(usage)

    target = parts[1].lower()

    async def done(text):
        try:
            await message.delete()
        except Exception:
            pass
        await client.send_message(message.chat.id, text)

    if target == "upi":
        value = _clean_value(parts[2])
        if not UPI_RE.match(value):
            return await message.reply_text("❌ UPI ID sahi nahi lag rahi. Jaise: <code>yourname@bank</code>")
        await _save("upi_id", value)
        return await done(f"✅ UPI ID save ho gayi: <code>{value}</code>")

    if len(parts) < 4:
        return await message.reply_text(usage)
    field, raw = parts[2], parts[3]

    if target == "ads":
        if field not in ADS_FIELDS:
            return await message.reply_text("❌ ads ke field: api_url, api_key, min_seconds")
        ok, value_or_err = _validate_ads_value(field, raw)
        if not ok:
            return await message.reply_text(f"❌ {value_or_err}")
        await _save(field, value_or_err, root="ads_config")
        return await done(f"✅ Ads {ADS_FIELDS[field]['label']} save ho gaya.")

    if target not in GATEWAYS:
        return await message.reply_text("❌ Gateway: demotry, razorpay ya cashfree")
    value = _clean_value(raw, field)
    ok, err = _validate_gateway_value(target, field, value)
    if not ok:
        return await message.reply_text(f"❌ {err}")
    await _save(f"{target}.{field}", value)
    await done(f"✅ {GATEWAYS[target]['title']} → {field} save ho gaya (<code>{mask(value)}</code>).\n/setup se Active banayein.")


def _validate_ads_value(field: str, raw: str):
    v = _clean_value(raw, field) if field != "api_url" else raw.strip().strip("`'\"“”‘’ ")
    if field == "api_url":
        v = re.sub(r"\s+", "", v)
        if not v.startswith(("http://", "https://")):
            return False, "API URL <code>https://</code> se shuru honi chahiye"
        return True, v
    if field == "api_key":
        if len(v) < 4:
            return False, "API key bahut chhoti hai"
        return True, v
    if field == "min_seconds":
        if not v.isdigit() or not (0 <= int(v) <= 600):
            return False, "0 se 600 ke beech number bhejein"
        return True, int(v)
    return False, "Unknown field"


# /cancel: chalta hua input band (admin.py ka /cancel apna kaam alag karta hai)
@Client.on_message(filters.command("cancel") & filters.user(ADMIN_ID) & filters.private, group=-1)
async def setup_cancel(client, message):
    if await _get_state(message.from_user.id):
        await _clear_state(message.from_user.id)
        await message.reply_text("❌ <b>Setup input cancel kar diya.</b>")


# ------------------------------- CALLBACKS -------------------------------
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

    # ---- ek gateway field ki value maangna ----
    if action == "f":
        gw, field = parts[2], parts[3]
        spec = next((f for f in GATEWAYS[gw]["fields"] if f["name"] == field), None)
        if not spec:
            return await callback.answer("❌ Field nahi mila", show_alert=True)
        await _set_state(admin_id, {"kind": "field", "gw": gw, "field": field})
        await callback.message.reply_text(
            f"{PROMPT_MARK} <b>{GATEWAYS[gw]['title']} → {spec['label']}</b>\n\n"
            f"Ab ye value bhejein (seedha paste kar sakte hain).\n"
            f"<i>Message save hote hi chat se delete ho jayega. Rokne ke liye /cancel.</i>",
            reply_markup=ForceReply(True)
        )
        return await callback.answer()

    # ---- choices (jaise Cashfree prod/sandbox) ----
    if action == "v":
        gw, field, value = parts[2], parts[3], parts[4]
        await _save(f"{gw}.{field}", value)
        await callback.answer(f"✅ {value} set ho gaya")
        text, markup = await _gateway_panel(gw)
        return await _show(callback, text, markup)

    # ---- gateway ko Active banana ----
    if action == "act":
        gw = parts[2]
        cfg = await load_config()
        if not is_configured(gw, cfg):
            return await callback.answer("❌ Pehle saari keys set karein", show_alert=True)
        await _save("active", gw)
        maintenance = await get_setting("auto_pay_maintenance", True)
        hint = "\n\n⚠️ Auto Pay abhi Maintenance me hai. Main panel se chalu karein." if maintenance else ""
        await callback.answer(f"✅ {GATEWAYS[gw]['title']} ab Active hai{hint}", show_alert=True)
        text, markup = await _gateway_panel(gw)
        return await _show(callback, text, markup)

    # ---- keys hatana ----
    if action == "clr":
        gw = parts[2]
        await settings_col.update_one({"key": "gateway_config"}, {"$unset": {f"value.{gw}": ""}}, upsert=True)
        await callback.answer("🗑 Keys hata di gayi", show_alert=True)
        text, markup = await _gateway_panel(gw)
        return await _show(callback, text, markup)

    # ---- gateway test ----
    if action in ("tg", "test"):
        cfg = await load_config()
        gw = parts[2] if action == "tg" else cfg["active"]
        await callback.answer("🔌 Test ho raha hai...")
        ok, msg = await test_gateway(gw)
        await callback.message.reply_text(f"{'✅' if ok else '❌'} <b>{GATEWAYS[gw]['title']} Test:</b> {msg}")
        return

    # ---- UPI ID ----
    if action == "upi":
        await _set_state(admin_id, {"kind": "upi"})
        await callback.message.reply_text(
            f"{PROMPT_MARK} <b>Manual payment ki UPI ID bhejein</b>\n\n"
            "Jaise: <code>yourname@bank</code>\n<i>Rokne ke liye /cancel.</i>",
            reply_markup=ForceReply(True)
        )
        return await callback.answer()

    # ---- Auto Pay ON / Maintenance ----
    if action == "toggle":
        maintenance = await get_setting("auto_pay_maintenance", True)
        if maintenance:
            cfg = await load_config()
            if not is_configured(cfg["active"], cfg):
                return await callback.answer(
                    f"❌ {GATEWAYS[cfg['active']]['title']} ki keys set nahi hain. Pehle keys daalein.",
                    show_alert=True
                )
            await set_setting("auto_pay_maintenance", False)
            await callback.answer("✅ Auto Pay chalu", show_alert=True)
        else:
            await set_setting("auto_pay_maintenance", True)
            await callback.answer("🛠 Maintenance lag gaya. Users ko popup dikhega.", show_alert=True)
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
            return await callback.answer("❌ Pehle Shortener API URL aur Key set karein.", show_alert=True)
        await _save("enabled", new_state, root="ads_config")
        await callback.answer("✅ Ads chalu" if new_state else "🔴 Ads band")
        text, markup = await _ads_panel()
        return await _show(callback, text, markup)

    if action == "adf":
        field = parts[2]
        if field not in ADS_FIELDS:
            return await callback.answer("❌ Field nahi mila", show_alert=True)
        await _set_state(admin_id, {"kind": "ads", "field": field})
        await callback.message.reply_text(
            f"{PROMPT_MARK} <b>{ADS_FIELDS[field]['label']}</b>\n\n{ADS_FIELDS[field]['hint']}\n\n"
            "<i>Value bhejein. Rokne ke liye /cancel.</i>",
            reply_markup=ForceReply(True)
        )
        return await callback.answer()

    if action == "adtest":
        ads = await get_ads_config()
        if not (ads.get("api_url") and ads.get("api_key")):
            return await callback.answer("❌ Pehle URL aur Key set karein", show_alert=True)
        await callback.answer("🔌 Test ho raha hai...")
        short, err = await shorten_url(ads, f"https://t.me/{BOT_USERNAME}")
        if short:
            return await callback.message.reply_text(f"✅ <b>Shortener Test OK</b>\n\n<code>{short}</code>")
        return await callback.message.reply_text(f"❌ <b>Shortener Test fail:</b>\n<code>{err}</code>")

    await callback.answer()


# ------------------------------- VALUE INPUT -------------------------------
# group=-1: admin.py ke master input handler se pehle chalta hai, taaki secret kisi aur handler tak na jaye
@Client.on_message(filters.private & filters.user(ADMIN_ID) & filters.text & ~filters.command(
    ["start", "setup", "payments", "cancel", "setkey"]), group=-1)
async def setup_input(client, message):
    admin_id = message.from_user.id
    state = await _get_state(admin_id)

    if not state:
        # Admin ne hamare prompt ka reply diya par session expire ho chuka -> saaf bata do
        replied = message.reply_to_message
        if replied and replied.from_user and replied.from_user.is_self and (replied.text or "").startswith(PROMPT_MARK):
            message.stop_propagation()
            return await message.reply_text(
                "⚠️ <b>Ye setup session expire ho gaya.</b>\n/setup se dobara shuru karein, "
                "ya seedha <code>/setkey</code> use karein."
            )
        return  # koi setup chal nahi raha: baaki handlers apna kaam karenge

    message.stop_propagation()   # ye message sirf setup ka hai
    raw = message.text

    async def finish(ok_text: str, panel):
        await _clear_state(admin_id)
        try:
            await message.delete()   # secret chat me na rahe
        except Exception:
            pass
        text, markup = panel
        await client.send_message(message.chat.id, f"{ok_text}\n\n{text}", reply_markup=markup, disable_web_page_preview=True)

    # ---- UPI ID ----
    if state["kind"] == "upi":
        value = _clean_value(raw)
        if not UPI_RE.match(value):
            return await message.reply_text(
                f"❌ <b>UPI ID sahi nahi lag rahi</b> (mila: <code>{value[:30]}</code>).\n"
                "Jaise: <code>yourname@bank</code>. Dobara bhejein ya /cancel:"
            )
        await _save("upi_id", value)
        return await finish("✅ <b>UPI ID save ho gayi.</b>", await _home_panel())

    # ---- ads field ----
    if state["kind"] == "ads":
        field = state["field"]
        ok, value_or_err = _validate_ads_value(field, raw)
        if not ok:
            return await message.reply_text(f"❌ <b>{value_or_err}</b>\nDobara bhejein ya /cancel:")
        await _save(field, value_or_err, root="ads_config")
        return await finish(f"✅ <b>{ADS_FIELDS[field]['label']} save ho gaya.</b>", await _ads_panel())

    # ---- gateway field ----
    gw, field = state["gw"], state["field"]
    value = _clean_value(raw, field)
    ok, err = _validate_gateway_value(gw, field, value)
    if not ok:
        print(f"[setup] {gw}.{field} rejected: {err} (len={len(value)})")
        return await message.reply_text(f"❌ <b>{err}</b>\nDobara bhejein ya /cancel:")

    await _save(f"{gw}.{field}", value)
    label = next(f["label"] for f in GATEWAYS[gw]["fields"] if f["name"] == field)
    await finish(f"✅ <b>{label} save ho gaya</b> (<code>{mask(value)}</code>).", await _gateway_panel(gw))
