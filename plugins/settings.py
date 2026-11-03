from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_ID, DB_CHANNEL_IDS
from database.db import (
    get_setting,
    set_setting,
    get_active_db_channel,
    stories_col,
)
from style import sc


# ------------------ /autopay : Auto UPI maintenance on/off ------------------
@Client.on_message(filters.command("autopay") & filters.user(ADMIN_ID) & filters.private, group=1)
async def autopay_command(client, message):
    """
    /autopay        -> current status
    /autopay off    -> "Under maintenance" popup on the Auto UPI button (users are pointed to Manual)
    /autopay on     -> Auto UPI works again
    """
    arg = message.command[1].lower() if len(message.command) > 1 else ""

    if arg in ("on", "enable"):
        await set_setting("auto_pay_maintenance", False)
        return await message.reply_text(f"✅ <b>{sc('Auto UPI is now ON')}</b>")

    if arg in ("off", "disable", "maintenance"):
        await set_setting("auto_pay_maintenance", True)
        return await message.reply_text(
            f"🛠 <b>{sc('Auto UPI is under maintenance')}</b>\nUsers will see a popup and will be asked to use the Manual option."
        )

    maintenance = await get_setting("auto_pay_maintenance", True)
    status = "🛠 Under maintenance (OFF)" if maintenance else "✅ ON"
    await message.reply_text(
        f"⚡ <b>{sc('Auto UPI status')}:</b> {status}\n\n"
        "<code>/autopay on</code>  → turn it ON\n"
        "<code>/autopay off</code> → put it under maintenance"
    )


# ------------------ /dbchannels : multiple DB channels ------------------
async def _build_channel_panel(client):
    active = await get_active_db_channel()
    lines = [f"📡 <b>{sc('DB channels')}</b>\n"]
    rows = []

    for idx, cid in enumerate(DB_CHANNEL_IDS):
        try:
            chat = await client.get_chat(cid)
            name = chat.title or "Channel"
            access = "✅"
        except Exception:
            name = "No access (the bot is not an admin or member)"
            access = "❌"

        stories_count = await stories_col.count_documents(
            {"db_channel": cid} if idx != 0 else {"$or": [{"db_channel": cid}, {"db_channel": {"$exists": False}}]}
        )
        mark = "🟢 ACTIVE" if cid == active else ""
        lines.append(f"{idx + 1}. {access} <b>{name}</b> {mark}\n   <code>{cid}</code> | 📚 {stories_count} stories")

        if cid != active and access == "✅":
            rows.append([InlineKeyboardButton(f"➡️ {sc('Make')} #{idx + 1} {sc('active')}", callback_data=f"setdbch:{idx}")])

    lines.append(
        "\n<i>The active channel is used when you give only a message ID (not a link) in /addstory. "
        "If you give a link (t.me/c/...), the channel is detected from the link itself.</i>\n\n"
        "➕ <b>To add a channel:</b> put its ID in the <code>CHANNEL_ID</code> or <code>DB_CHANNELS</code> variable on Render "
        "(comma separated, for example <code>-1001111111111,-1002222222222</code>), make the bot an admin of that channel, "
        "and restart the bot."
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
        return await callback.answer("Channel not found.", show_alert=True)

    await set_setting("active_db_channel", DB_CHANNEL_IDS[idx])
    await callback.answer("Active channel changed.", show_alert=True)

    text, markup = await _build_channel_panel(client)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
