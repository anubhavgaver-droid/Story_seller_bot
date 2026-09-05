
import asyncio
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated
from config import ADMIN_ID
from database.db import get_all_users, send_log

@Client.on_message(filters.command("broadcast") & filters.user(ADMIN_ID) & filters.private, group=1)
async def broadcast_handler(client, message):
    if not message.reply_to_message:
        return await message.reply_text(
            "⚠️ <b>ᴜsᴀɢᴇ:</b>\n\n"
            "जिस मैसेज को ब्रॉडकास्ट करना है, उस पर Reply करके लिखें:\n"
            "• <code>/broadcast</code> (सामान्य मैसेज)\n"
            "• <code>/broadcast -pin</code> (मैसेज पिन भी होगा)"
        )

    pin_message = False
    if len(message.command) > 1 and message.command[1].lower() == "-pin":
        pin_message = True

    reply_msg = message.reply_to_message
    users = await get_all_users()
    
    if not users:
        return await message.reply_text("❌ <b>ᴅᴀᴛᴀʙᴀsᴇ ᴍᴇɪɴ ᴋᴏɪ ᴜsᴇʀs ɴᴀʜɪ ᴍɪʟᴇ!</b>")

    status_msg = await message.reply_text("🚀 <b>ʙʀᴏᴀᴅᴄᴀsᴛ sᴛᴀʀᴛᴇᴅ...</b>\n\n<i>कैलकुलेट हो रहा है...</i>")

    total_users = len(users)
    success = 0
    failed = 0
    blocked = 0

    for user in users:
        # DB schema के अनुसार user_id extract करना
        user_id = user['user_id'] if isinstance(user, dict) else user
        
        try:
            sent_msg = await reply_msg.copy(chat_id=user_id)
            if pin_message:
                try:
                    await sent_msg.pin(both_sides=True)
                except Exception:
                    pass
            success += 1
            await asyncio.sleep(0.05)  # Telegram Rate Limits (FloodWait) से बचने के लिए

        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                sent_msg = await reply_msg.copy(chat_id=user_id)
                if pin_message:
                    try:
                        await sent_msg.pin(both_sides=True)
                    except Exception:
                        pass
                success += 1
            except Exception:
                failed += 1

        except UserIsBlocked:
            blocked += 1
        except InputUserDeactivated:
            failed += 1
        except Exception:
            failed += 1

    report_text = (
        f"✅ <b>ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏᴍᴘʟᴇᴛᴇᴅ!</b>\n\n"
        f"📊 <b>Total Users:</b> {total_users}\n"
        f"🎯 <b>Successful:</b> {success}\n"
        f"🚫 <b>Blocked Bot:</b> {blocked}\n"
        f"❌ <b>Failed / Deleted Accounts:</b> {failed}"
    )
    
    await status_msg.edit_text(report_text)

    # Log Channel में ब्रॉडकास्ट की रिपोर्ट भेजना
    try:
        await send_log(client, f"📢 <b>ADMIN BROADCAST COMPLETED</b>\n\n{report_text}")
    except Exception:
        pass
