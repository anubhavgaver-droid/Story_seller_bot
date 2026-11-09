
import asyncio
import html as _html
from collections import Counter

from pyrogram import Client, filters
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated
from config import ADMIN_ID
from database.db import get_all_users, send_log

try:
    from richui import _api as _bot_api   # raw Bot API call (never raises)
except Exception:                          # pragma: no cover
    _bot_api = None


class _Blocked(Exception):
    pass


class _Gone(Exception):
    pass


async def _copy_via_bot_api(chat_id: int, from_chat_id: int, message_id: int) -> int:
    """
    Bot API copyMessage works for EVERY kind of message, including the Rich Messages (big heading + table)
    that the bot itself sends. Pyrogram's Message.copy() cannot copy those, so it fails for every user.
    Returns the new message_id.
    """
    if _bot_api is None:
        raise RuntimeError("Bot API fallback is not available")
    payload = {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id}
    res = await _bot_api("copyMessage", payload)
    if not res.get("ok"):
        wait = (res.get("parameters") or {}).get("retry_after")
        if wait:
            await asyncio.sleep(int(wait) + 1)
            res = await _bot_api("copyMessage", payload)
    if res.get("ok"):
        return (res.get("result") or {}).get("message_id")
    desc = str(res.get("description") or "unknown error")
    low = desc.lower()
    if "blocked" in low or "kicked" in low:
        raise _Blocked(desc)
    if "deactivated" in low or "chat not found" in low or "user not found" in low:
        raise _Gone(desc)
    raise RuntimeError(desc)


async def _copy_to(client, reply_msg, user_id: int):
    """Copies the replied message to one user. Returns the new message_id (or None)."""
    try:
        sent = await reply_msg.copy(chat_id=user_id)
        return getattr(sent, "id", None)
    except (FloodWait, UserIsBlocked, InputUserDeactivated):
        raise
    except Exception:
        # Pyrogram could not copy this message type (for example a Rich Message): use the Bot API instead.
        return await _copy_via_bot_api(user_id, reply_msg.chat.id, reply_msg.id)


async def _send_one(client, reply_msg, user_id: int, pin_message: bool):
    mid = await _copy_to(client, reply_msg, user_id)
    if pin_message and mid:
        try:
            await client.pin_chat_message(user_id, mid, both_sides=True)
        except Exception:
            pass


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
    reasons = Counter()      # why the failures happened (shown in the report, so a problem is never hidden)

    for user in users:
        # DB schema के अनुसार user_id extract करना
        user_id = user['user_id'] if isinstance(user, dict) else user
        
        try:
            await _send_one(client, reply_msg, user_id, pin_message)
            success += 1
            await asyncio.sleep(0.05)  # Telegram Rate Limits (FloodWait) से बचने के लिए

        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                await _send_one(client, reply_msg, user_id, pin_message)
                success += 1
            except (UserIsBlocked, _Blocked):
                blocked += 1
            except Exception as e2:
                failed += 1
                reasons[f"{type(e2).__name__}: {e2}"[:120]] += 1

        except (UserIsBlocked, _Blocked):
            blocked += 1
        except (InputUserDeactivated, _Gone) as e:
            failed += 1
            reasons[f"{type(e).__name__}: {e}"[:120]] += 1
        except Exception as e:
            failed += 1
            reasons[f"{type(e).__name__}: {e}"[:120]] += 1

    report_text = (
        f"✅ <b>ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏᴍᴘʟᴇᴛᴇᴅ!</b>\n\n"
        f"📊 <b>Total Users:</b> {total_users}\n"
        f"🎯 <b>Successful:</b> {success}\n"
        f"🚫 <b>Blocked Bot:</b> {blocked}\n"
        f"❌ <b>Failed / Deleted Accounts:</b> {failed}"
    )
    if reasons:
        top = "\n".join(f"• {_html.escape(r)} (×{n})" for r, n in reasons.most_common(3))
        report_text += f"\n\n⚠️ <b>Failure reasons:</b>\n{top}"
    
    await status_msg.edit_text(report_text)

    # Log Channel में ब्रॉडकास्ट की रिपोर्ट भेजना
    try:
        await send_log(client, f"📢 <b>ADMIN BROADCAST COMPLETED</b>\n\n{report_text}")
    except Exception:
        pass
