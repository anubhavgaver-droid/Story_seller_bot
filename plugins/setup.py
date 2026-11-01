"""
/setup  (ya /payments)  -  Admin ke liye payment setup panel.

Yahin se sab set hota hai (Render me jaake variable nahi badalne padte):
  - Gateway chunna: Demotry.shop / Razorpay / Cashfree
  - Har gateway ki API key, secret, mode
  - Manual payment ki UPI ID
  - Auto Pay ON / Maintenance toggle
  - Keys ka "Test" (bina order banaye)

Sab kuch database me save hota hai. Admin ka bheja hua secret message save hote hi delete ho jata hai.
"""
import re

from pyrogram import Client, filters, enums
from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply

from config import ADMIN_ID, WEB_APP_URL
from database.db import get_setting, set_setting, settings_col
from gateway import GATEWAYS, load_config, is_configured, mask, test_gateway

# admin_id -> {"kind": "field"/"upi", "gw": ..., "field": ...}
SETUP_STATE = {}

UPI_RE = re.compile(r"^[A-Za-z0-9.\-_]{2,}@[A-Za-z]{2,}$")


def _btn(text, data):
    return InlineKeyboardButton(text, callback_data=data)


async def _save(path: str, value):
    await settings_col.update_one(
        {"key": "gateway_config"}, {"$set": {f"value.{path}": value}}, upsert=True
    )


# ------------------------------- PANELS -------------------------------
async def _home_panel():
    cfg = await load_config()
    maintenance = await get_setting("auto_pay_maintenance", True)
    active = cfg["active"]
    spec = GATEWAYS.get(active, GATEWAYS["demotry"])
    ready = "✅ keys set" if is_configured(active, cfg) else "❌ keys set nahi"
    auto = "🛠 Under Maintenance (BAND)" if maintenance else "✅ ON"

    text = (
        "⚙️ <b>ᴘᴀʏᴍᴇɴᴛ sᴇᴛᴜᴘ</b>\n\n"
        f"💳 <b>Active Gateway:</b> {spec['title']} ({ready})\n"
        f"⚡ <b>Auto Pay:</b> {auto}\n"
        f"🏦 <b>Manual UPI ID:</b> <code>{cfg['upi_id']}</code>\n\n"
        "<i>Sab kuch yahin se set karein, Render me variable badalne ki zaroorat nahi.</i>"
    )
    toggle_label = "🛠 Maintenance lagayein (Auto Pay band)" if not maintenance else "✅ Auto Pay chalu karein"
    rows = [
        [_btn("💳 Payment Gateway chunein / Setup", "st:gws")],
        [_btn("🏦 UPI ID badlein (Manual payment)", "st:upi")],
        [_btn(toggle_label, "st:toggle")],
        [_btn("🔌 Active gateway Test", "st:test")],
        [_btn("❌ Close", "st:close")],
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

    action_row = []
    if is_configured(gw, cfg) and not is_active:
        action_row.append(_btn("🟢 Active banayein", f"st:act:{gw}"))
    action_row.append(_btn("🔌 Test", f"st:tg:{gw}"))
    rows.append(action_row)
    rows.append([_btn("🗑 Keys hatayein", f"st:clr:{gw}")])
    rows.append([_btn("⬅️ Back", "st:gws")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


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
    SETUP_STATE.pop(message.from_user.id, None)
    text, markup = await _home_panel()
    await message.reply_text(text, reply_markup=markup)


# /cancel: chalta hua key-input band (admin.py ka /cancel apna kaam alag karta hai)
@Client.on_message(filters.command("cancel") & filters.user(ADMIN_ID) & filters.private, group=-1)
async def setup_cancel(client, message):
    if SETUP_STATE.pop(message.from_user.id, None):
        await message.reply_text("❌ <b>Setup input cancel kar diya.</b>")


# ------------------------------- CALLBACKS -------------------------------
@Client.on_callback_query(filters.regex(r"^st:") & filters.user(ADMIN_ID))
async def setup_callbacks(client, callback):
    parts = callback.data.split(":")
    action = parts[1]
    admin_id = callback.from_user.id

    if action == "home":
        SETUP_STATE.pop(admin_id, None)
        text, markup = await _home_panel()
        return await _show(callback, text, markup)

    if action == "close":
        SETUP_STATE.pop(admin_id, None)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return await callback.answer()

    if action == "gws":
        SETUP_STATE.pop(admin_id, None)
        text, markup = await _gateways_panel()
        return await _show(callback, text, markup)

    if action == "gw":
        SETUP_STATE.pop(admin_id, None)
        text, markup = await _gateway_panel(parts[2])
        return await _show(callback, text, markup)

    # ---- ek field ki value maangna ----
    if action == "f":
        gw, field = parts[2], parts[3]
        spec = next((f for f in GATEWAYS[gw]["fields"] if f["name"] == field), None)
        if not spec:
            return await callback.answer("❌ Field nahi mila", show_alert=True)
        SETUP_STATE[admin_id] = {"kind": "field", "gw": gw, "field": field}
        await callback.message.reply_text(
            f"✏️ <b>{GATEWAYS[gw]['title']} → {spec['label']}</b>\n\n"
            f"Ab ye value bhejein.\n"
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

    # ---- test ----
    if action in ("tg", "test"):
        cfg = await load_config()
        gw = parts[2] if action == "tg" else cfg["active"]
        await callback.answer("🔌 Test ho raha hai...")
        ok, msg = await test_gateway(gw)
        await callback.message.reply_text(
            f"{'✅' if ok else '❌'} <b>{GATEWAYS[gw]['title']} Test:</b> {msg}"
        )
        return

    # ---- UPI ID ----
    if action == "upi":
        SETUP_STATE[admin_id] = {"kind": "upi"}
        await callback.message.reply_text(
            "🏦 <b>Manual payment ki UPI ID bhejein</b>\n\n"
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

    await callback.answer()


# ------------------------------- VALUE INPUT -------------------------------
# group=-1: admin.py ke master input handler se pehle chalta hai, taaki secret kisi aur handler tak na jaye
@Client.on_message(filters.private & filters.user(ADMIN_ID) & filters.text & ~filters.command(
    ["start", "setup", "payments", "cancel"]), group=-1)
async def setup_input(client, message):
    state = SETUP_STATE.get(message.from_user.id)
    if not state:
        return  # koi setup chal nahi raha: baaki handlers (group 0, 1...) apna kaam karenge

    value = message.text.strip()
    message.stop_propagation()   # ye message sirf setup ka hai

    # ---- UPI ID ----
    if state["kind"] == "upi":
        if not UPI_RE.match(value):
            return await message.reply_text("❌ <b>UPI ID sahi nahi lag rahi.</b> Jaise: <code>yourname@bank</code>\nDobara bhejein ya /cancel:")
        await _save("upi_id", value)
        SETUP_STATE.pop(message.from_user.id, None)
        try:
            await message.delete()
        except Exception:
            pass
        text, markup = await _home_panel()
        return await message.reply_text(f"✅ <b>UPI ID save ho gayi.</b>\n\n{text}", reply_markup=markup)

    # ---- gateway field ----
    gw, field = state["gw"], state["field"]
    spec = next(f for f in GATEWAYS[gw]["fields"] if f["name"] == field)

    if len(value) < spec.get("min", 1) or " " in value:
        return await message.reply_text("❌ <b>Value sahi nahi lag rahi</b> (chhoti hai ya space hai). Dobara bhejein ya /cancel:")
    if spec.get("prefix") and not value.startswith(spec["prefix"]):
        return await message.reply_text(f"❌ <b>Ye <code>{spec['prefix']}</code> se shuru honi chahiye.</b> Dobara bhejein ya /cancel:")

    await _save(f"{gw}.{field}", value)
    SETUP_STATE.pop(message.from_user.id, None)
    try:
        await message.delete()   # secret chat me na rahe
    except Exception:
        pass

    text, markup = await _gateway_panel(gw)
    await message.reply_text(f"✅ <b>{spec['label']} save ho gaya.</b>\n\n{text}", reply_markup=markup, disable_web_page_preview=True)
