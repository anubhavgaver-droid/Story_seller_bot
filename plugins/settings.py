from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_ID, DB_CHANNEL_IDS
from database.db import (
    get_setting,
    set_setting,
    get_active_db_channel,
    stories_col,
)


# ------------------ /autopay : Auto UPI maintenance on/off ------------------
@Client.on_message(filters.command("autopay") & filters.user(ADMIN_ID) & filters.private, group=1)
async def autopay_command(client, message):
    """
    /autopay          -> abhi ka status
    /autopay off      -> Auto UPI par 'Under Maintenance' popup (users ko Manual dikhega)
    /autopay on       -> Auto UPI wapas chalu
    """
    arg = message.command[1].lower() if len(message.command) > 1 else ""

    if arg in ("on", "enable", "chalu"):
        await set_setting("auto_pay_maintenance", False)
        return await message.reply_text("✅ <b>Auto UPI chalu kar diya gaya.</b>")

    if arg in ("off", "disable", "band", "maintenance"):
        await set_setting("auto_pay_maintenance", True)
        return await message.reply_text("🛠 <b>Auto UPI ab 'Under Maintenance' hai.</b>\nUsers ko popup dikhega aur Manual option use karna hoga.")

    maintenance = await get_setting("auto_pay_maintenance", True)
    status = "🛠 Under Maintenance (band)" if maintenance else "✅ Chalu"
    await message.reply_text(
        f"⚡ <b>Auto UPI status:</b> {status}\n\n"
        f"<code>/autopay on</code>  → chalu karein\n"
        f"<code>/autopay off</code> → maintenance popup lagayein"
    )


# ------------------ /dbchannels : multiple DB channels ------------------
async def _build_channel_panel(client):
    active = await get_active_db_channel()
    lines = ["📡 <b>DB Channels</b>\n"]
    rows = []

    for idx, cid in enumerate(DB_CHANNEL_IDS):
        try:
            chat = await client.get_chat(cid)
            name = chat.title or "Channel"
            access = "✅"
        except Exception:
            name = "Access nahi (bot admin/member nahi)"
            access = "❌"

        stories_count = await stories_col.count_documents(
            {"db_channel": cid} if idx != 0 else {"$or": [{"db_channel": cid}, {"db_channel": {"$exists": False}}]}
        )
        mark = "🟢 ACTIVE" if cid == active else ""
        lines.append(f"{idx + 1}. {access} <b>{name}</b> {mark}\n   <code>{cid}</code> | 📚 {stories_count} stories")

        if cid != active and access == "✅":
            rows.append([InlineKeyboardButton(f"➡️ #{idx + 1} ko Active banayein", callback_data=f"setdbch:{idx}")])

    lines.append(
        "\n<i>Active channel: jab /addstory me aap link ki jagah sirf message ID dete hain, "
        "tab nayi story isi channel me maani jaati hai. Link (t.me/c/...) dene par channel link se hi pata chal jaata hai.</i>\n\n"
        "➕ <b>Naya channel jodne ke liye:</b> Render me <code>DB_CHANNELS</code> variable me ID comma se jodein "
        "(jaise <code>-1001111111111,-1002222222222</code>), bot ko us channel me admin banayein, restart karein."
    )
    return "\n".join(lines), InlineKeyboardMarkup(rows) if rows else None


@Client.on_message(filters.command("dbchannels") & filters.user(ADMIN_ID) & filters.private, group=1)
async def dbchannels_command(client, message):
    text, markup = await _build_channel_panel(client)
    await message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^setdbch:\d+$") & filters.user(ADMIN_ID))
async def set_active_channel_callback(client, callback):
    idx = int(callback.data.split(":")[1])
    if idx >= len(DB_CHANNEL_IDS):
        return await callback.answer("❌ Channel nahi mila!", show_alert=True)

    await set_setting("active_db_channel", DB_CHANNEL_IDS[idx])
    await callback.answer("✅ Active channel badal gaya!", show_alert=True)

    text, markup = await _build_channel_panel(client)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
