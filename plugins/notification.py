import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated
from config import ADMIN_ID, BOT_USERNAME
from database.db import purchases_col, users_col, send_log, get_story_by_title, delivery_link

# -------------------- HELPER: GET STORY BUYERS --------------------
async def get_story_buyers(story_title: str, story_id: str = None):
    """
    किसी स्टोरी के सभी खरीदार (Buyers) यूज़र्स की unique user_id लिस्ट निकालता है।
    story_id (naye purchases) aur title (purane purchases) dono se dhundhta hai.
    """
    clean_title = story_title.strip().split("\n")[0]

    purchase_query = {"$or": [{"story_title": clean_title}]}
    users_query = {"$or": [{"purchased_stories": clean_title}]}
    if story_id:
        purchase_query["$or"].append({"story_id": story_id})
        users_query["$or"].append({"purchased_story_ids": story_id})

    # 1. Purchases collection से Buyers निकालना
    cursor = purchases_col.find(purchase_query, {"user_id": 1, "_id": 0})
    buyers_from_purchases = [doc["user_id"] async for doc in cursor if "user_id" in doc]

    # 2. Users collection से भी Check करना (Backup Sync)
    cursor_users = users_col.find(users_query, {"user_id": 1, "_id": 0})
    buyers_from_users = [doc["user_id"] async for doc in cursor_users if "user_id" in doc]

    # Duplicates हटाने के लिए Set का प्रयोग
    all_buyers = list(set(buyers_from_purchases + buyers_from_users))
    return all_buyers

# -------------------- BROADCAST NOTIFICATION FUNCTION --------------------
async def notify_story_buyers(client: Client, story_title: str, ep_info: str = "New Episode Added"):
    """
    स्टोरी में नया एपिसोड/फाइल ऐड होने पर बायर्स को ऑटोमेटिक नोटिफिकेशन बटन के साथ भेजने का फ़ंक्शन।
    """
    clean_title = story_title.strip().split("\n")[0]
    story_doc = await get_story_by_title(clean_title)
    story_id = story_doc.get("story_id") if story_doc else None
    buyers = await get_story_buyers(clean_title, story_id)

    if not buyers:
        print(f"[Notification] No buyers found for story: {clean_title}")
        return

    # Deep Link Generate (e.g. https://t.me/botusername?start=get_a8xk29qp) - random ID, title nahi
    if story_id:
        story_link = delivery_link(story_id)
    else:
        story_link = f"https://t.me/{BOT_USERNAME}?start=get_{clean_title.replace(' ', '_')[:50]}"

    notification_text = (
        f"🎉 <b>New Episode Alert!</b> 🎉\n\n"
        f"📖 <b>Story:</b> <code>{clean_title}</code>\n"
        f"🎬 <b>Update:</b> <code>{ep_info}</code>\n\n"
        f"✨ आपकी खरीदी हुई स्टोरी में नए एपिसोड ऐड हो गए हैं! देखने के लिए नीचे दिए गए बटन पर क्लिक करें:"
    )

    # 🔘 Inline Access Button
    access_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📲 Access Your Story", url=story_link)]
    ])

    success = 0
    blocked = 0
    failed = 0

    for user_id in buyers:
        try:
            await client.send_message(
                chat_id=user_id, 
                text=notification_text, 
                reply_markup=access_markup,
                disable_web_page_preview=True
            )
            success += 1
            await asyncio.sleep(0.08)  # Rate Limit / FloodWait से बचने के लिए Delay
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                await client.send_message(
                    chat_id=user_id, 
                    text=notification_text, 
                    reply_markup=access_markup,
                    disable_web_page_preview=True
                )
                success += 1
            except Exception:
                failed += 1
        except (UserIsBlocked, InputUserDeactivated):
            blocked += 1
        except Exception:
            failed += 1

    log_msg = (
        f"📢 <b>Episode Notification Broadcast Complete!</b>\n\n"
        f"📖 <b>Story:</b> <code>{clean_title}</code>\n"
        f"🎬 <b>Details:</b> <code>{ep_info}</code>\n"
        f"🔗 <b>Access Link:</b> {story_link}\n\n"
        f"✅ Delivered: <code>{success}</code>\n"
        f"🚫 Blocked Users: <code>{blocked}</code>\n"
        f"❌ Failed: <code>{failed}</code>"
    )
    
    # Log Channel में पूरी रिपोर्ट भेजेगा
    try:
        await send_log(client, log_msg)
    except Exception:
        pass

# -------------------- MANUAL ADMIN COMMAND --------------------
@Client.on_message(filters.command("notifyep") & filters.user(ADMIN_ID) & filters.private, group=1)
async def manual_notify_cmd(client: Client, message):
    """
    Admin के लिए मैन्युअल कमांड (अगर खुद से मैसेज भेजना हो):
    Usage: /notifyep Story Title | Episode Details
    """
    if len(message.command) < 2:
        return await message.reply_text("⚠️ <b>Usage:</b>\n<code>/notifyep Story Title | Episode 51-100</code>")

    content = message.text.split(" ", 1)[1]
    if "|" in content:
        title, ep_info = content.split("|", 1)
    else:
        title, ep_info = content, "New Episodes Added!"

    title = title.strip()
    ep_info = ep_info.strip()

    status_msg = await message.reply_text(f"⏳ <b>'{title}'</b> के Buyers को नोटिफिकेशन भेजा जा रहा है...")
    
    await notify_story_buyers(client, title, ep_info)
    
    await status_msg.edit_text(f"✅ <b>Notification Process Completed for '{title}'!</b>")
