import json
import asyncio
import time
import re
from urllib.parse import quote
from pyrogram import Client, filters, enums
from pyrogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    ForceReply,
    WebAppInfo,
    CallbackQuery,
    ReplyKeyboardRemove
)

# Required Database functions
from database.db import (
    get_story_by_title, 
    send_log, 
    is_user_registered, 
    register_user, 
    get_user_purchases, 
    get_user_wallet,
    update_user_wallet,
    add_user_purchase,
    is_story_unlocked,
    get_exact_episode_range,
    add_wallet_balance,
    get_referred_users_count,
    users_col
)
# Config file imports
from config import (
    BOT_USERNAME, 
    WEB_APP_URL, 
    CHANNEL_ID, 
    DELIVERY_STICKER_ID, 
    SEARCH_RANGE_STICKER_ID
)

REFER_BONUS = 1.0  # ₹1.00 Per Referral

# Storage Dictionary for Range Input & Selected Story
START_RANGE_WAITING = {}
USER_ACTIVE_STORY = {}

# Storage Set for Delivery Stop Control
STOP_DELIVERY_USERS = set()

# 1. Main Menu Keyboard Layout (With Refer & Earn Added)
MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ")],
        [KeyboardButton("💼 ᴍʏ ᴡᴀʟʟᴇᴛ"), KeyboardButton("👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ")],
        [KeyboardButton("🎁 ʀᴇғᴇʀ & ᴇᴀʀɴ")],
        [KeyboardButton("🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ"), KeyboardButton("📻 ᴘᴏᴄᴋᴇᴛ ғᴍ")],
        [KeyboardButton("📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ"), KeyboardButton("📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ")],
        [KeyboardButton("📞 sᴜᴘᴘᴏʀᴛ")]
    ],
    resize_keyboard=True
)

# Custom Filter for WebApp Data
async def web_app_filter(_, __, message):
    return bool(message.web_app_data)

filter_webapp = filters.create(web_app_filter)

# ------------------ Dynamic Stop Delivery Callback Handler ------------------
@Client.on_callback_query(filters.regex("^stop_delivery$"))
async def stop_delivery_handler(client, callback_query):
    user_id = callback_query.from_user.id
    STOP_DELIVERY_USERS.add(user_id)
    await callback_query.answer("🛑 डिलीवरी रोकी जा रही है... कृपया प्रतीक्षा करें!", show_alert=True)

# ------------------ Helper: Dynamic Reply Keyboard Grid Generator ------------------
def build_custom_range_reply_keyboard(custom_ranges):
    keyboard_rows = []
    current_row = []

    # Custom Ranges को 2-Column Grid में सेट करना
    for r in custom_ranges:
        btn_text = f"Files {r['name']}"
        current_row.append(KeyboardButton(btn_text))
        
        if len(current_row) == 2:
            keyboard_rows.append(current_row)
            current_row = []

    if current_row:
        keyboard_rows.append(current_row)

    # Full Delivery / All Files Button
    keyboard_rows.append([KeyboardButton("📦 Full Delivery (All Files)")])

    # Cancel Button
    keyboard_rows.append([KeyboardButton("❌ Cancel")])

    return ReplyKeyboardMarkup(
        keyboard=keyboard_rows,
        resize_keyboard=True,
        one_time_keyboard=False  # FIXED: Set to False so keyboard UI remains active
    )

# ------------------ Global Close Callback Handler ------------------
@Client.on_callback_query(filters.regex("^close_message$"))
async def close_message_handler(client, callback_query):
    try:
        await callback_query.message.delete()
    except Exception:
        pass
    await callback_query.answer()

# ------------------ Helper: Extract Episode Number ------------------
def extract_episode_number(text: str) -> int:
    if not text:
        return None
    
    patterns = [
        r'(?:episode|ep|episodes)\s*[-:]?\s*(\d+)',
        r'#\s*(\d+)',
        r'(?:part|pt)\s*[-:]?\s*(\d+)',
        r'\bep\s*(\d+)\b',
        r'\b(\d+)\b'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None

# ------------------ Helper: Extract Text from Message ------------------
def get_message_searchable_text(msg) -> str:
    if not msg:
        return ""
    
    combined_texts = []
    
    if msg.caption:
        combined_texts.append(msg.caption)
    if msg.text:
        combined_texts.append(msg.text)
        
    if msg.audio:
        if msg.audio.title:
            combined_texts.append(msg.audio.title)
        if msg.audio.file_name:
            combined_texts.append(msg.audio.file_name)
        if msg.audio.performer:
            combined_texts.append(msg.audio.performer)

    if msg.document and msg.document.file_name:
        combined_texts.append(msg.document.file_name)

    if msg.video and msg.video.file_name:
        combined_texts.append(msg.video.file_name)

    if msg.voice and msg.caption:
        combined_texts.append(msg.caption)

    return " | ".join(combined_texts)

# ------------------ Helper: Smart File Delivery Function ------------------
async def send_story_files_start(client, user_id, story, first_id, last_id, clean_title, custom_range_text="", target_start_ep=None, target_end_ep=None):
    sent_messages_obj = []
    sent_message_ids = []
    success_count = 0

    # Reset user's stop delivery status
    if user_id in STOP_DELIVERY_USERS:
        STOP_DELIVERY_USERS.remove(user_id)

    chosen_sticker = SEARCH_RANGE_STICKER_ID if target_start_ep is not None else DELIVERY_STICKER_ID

    # Stop Delivery Keyboard Layout
    stop_reply_keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("🛑 sᴛᴏᴘ ᴅᴇʟɪᴠᴇʀʏ")]],
        resize_keyboard=True
    )

    # 1. Send Sticker with Stop Keyboard
    try:
        status_sticker = await client.send_sticker(
            chat_id=user_id,
            sticker=chosen_sticker,
            reply_markup=stop_reply_keyboard
        )
    except Exception:
        status_sticker = None

    msg_ids_to_fetch = list(range(first_id, last_id + 1))
    chunk_size = 200
    matching_messages = []

    for i in range(0, len(msg_ids_to_fetch), chunk_size):
        chunk = msg_ids_to_fetch[i:i + chunk_size]
        try:
            channel_msgs = await client.get_messages(chat_id=CHANNEL_ID, message_ids=chunk)
            if not isinstance(channel_msgs, list):
                channel_msgs = [channel_msgs]

            for msg in channel_msgs:
                if not msg or msg.empty:
                    continue
                
                searchable_text = get_message_searchable_text(msg)
                ep_num = extract_episode_number(searchable_text)

                if target_start_ep is not None and target_end_ep is not None:
                    if ep_num is not None and target_start_ep <= ep_num <= target_end_ep:
                        matching_messages.append((ep_num, msg))
                else:
                    matching_messages.append((ep_num or 0, msg))
        except Exception as e:
            print(f"Error fetching channel messages batch: {e}")

    if target_start_ep is not None and target_end_ep is not None:
        matching_messages.sort(key=lambda x: x[0])
        messages_to_send = [item[1] for item in matching_messages]
    else:
        messages_to_send = [item[1] for item in matching_messages]

    total_files = len(messages_to_send)

    if total_files == 0:
        if status_sticker:
            try: await status_sticker.delete()
            except Exception: pass

        return await client.send_message(
            chat_id=user_id,
            text=f"❌ <b>ɴᴏ ᴍᴀᴛᴄʜɪɴɢ ᴇᴘɪsᴏᴅᴇs ғᴏᴜɴᴅ!</b>\n\n"
                 f"रेंज <b>{custom_range_text}</b> के एपिसोड्स उपलब्ध नहीं हैं।",
            reply_markup=MAIN_MENU
        )

    # 2. Send Progress Message WITH Reply Keyboard (To ensure Telegram UI renders it)
    progress_msg = await client.send_message(
        chat_id=user_id,
        text=f"📦 <b>ᴅᴇʟɪᴠᴇʀɪɴɢ ғɪʟᴇs...</b>\n\n"
             f"📖 <b>Story:</b> {clean_title}\n"
             f"📊 <b>Progress:</b> 0 / {total_files} Files Sent\n\n"
             f"<i>रोकने के लिए नीचे दिए गए '🛑 sᴛᴏᴘ ᴅᴇʟɪᴠᴇʀʏ' बटन को दबाएं।</i>",
        reply_markup=stop_reply_keyboard
    )

    is_stopped_by_user = False

    for msg in messages_to_send:
        # Check Stop Keyboard Button Click
        if user_id in STOP_DELIVERY_USERS:
            is_stopped_by_user = True
            STOP_DELIVERY_USERS.remove(user_id)
            break

        try:
            sent_msg = await client.copy_message(
                chat_id=user_id,
                from_chat_id=CHANNEL_ID,
                message_id=msg.id,
                protect_content=True
            )
            sent_messages_obj.append(sent_msg)
            sent_message_ids.append(sent_msg.id)
            success_count += 1

            # Live Progress Update
            try:
                await progress_msg.edit_text(
                    f"📦 <b>ᴅᴇʟɪᴠᴇʀɪɴɢ ғɪʟᴇs...</b>\n\n"
                    f"📖 <b>Story:</b> {clean_title}\n"
                    f"📊 <b>Progress:</b> {success_count} / {total_files} Files Sent\n\n"
                    f"<i>रोकने के लिए नीचे दिए गए '🛑 sᴛᴏᴘ ᴅᴇʟɪᴠᴇʀʏ' बटन को दबाएं।</i>"
                )
            except Exception:
                pass

            await asyncio.sleep(1.0)
        except Exception as e:
            print(f"Error copying message {msg.id}: {e}")

    # Cleanup Status Sticker and Progress Tracker
    try:
        if status_sticker: await status_sticker.delete()
        await progress_msg.delete()
    except Exception:
        pass

    ep_range = get_exact_episode_range(sent_messages_obj) if sent_messages_obj else f"Files Range"

    # Clean Chat Keyboard Setup
    if sent_message_ids:
        first_sent_id = sent_message_ids[0]
        last_sent_id = sent_message_ids[-1]
        
        clean_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧹 ᴄʟᴇᴀɴ / ᴅᴇʟᴇᴛᴇ ᴀʟʟ ғɪʟᴇs", callback_data=f"rangechatclean_{first_sent_id}_{last_sent_id}")]
        ])
    else:
        clean_kb = None

    status_header = "🛑 <b>ᴅᴇʟɪᴠᴇʀʏ sᴛᴏᴘᴘᴇᴅ ʙʏ ᴜsᴇʀ!</b>" if is_stopped_by_user else "🎉 <b>ғɪʟᴇs ᴅᴇʟɪᴠᴇʀᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>"

    await client.send_message(
        chat_id=user_id,
        text=f"{status_header}\n\n"
             f"📖 <b>sᴛᴏʀʏ:</b> {clean_title}\n"
             f"🎧 <b>ʀᴀɴɢᴇ:</b> {ep_range} {custom_range_text}\n"
             f"📦 <b>ᴅᴇʟɪᴠᴇʀᴇᴅ:</b> {success_count} / {total_files} Files\n\n"
             f"👇 <i>सुनने के बाद मैसेज / फाइल्स साफ़ करने के लिए नीचे बटन पर क्लिक करें:</i>",
        reply_markup=clean_kb
    )
    
    # Restore Main Menu Keyboard
    await client.send_message(chat_id=user_id, text="👇 <b>Main Menu:</b>", reply_markup=MAIN_MENU)

# ------------------ Range-Based Clean Chat Callback Handler ------------------
@Client.on_callback_query(filters.regex(r"^rangechatclean_"))
async def range_clean_chat_handler(client, callback_query):
    try:
        user_id = callback_query.from_user.id
        data_parts = callback_query.data.split("_")
        
        start_id = int(data_parts[1])
        end_id = int(data_parts[2])

        await callback_query.answer("🧹 Cleaning files... Please wait!")

        msg_ids_to_delete = list(range(start_id, end_id + 1))
        msg_ids_to_delete.append(callback_query.message.id)

        chunk_size = 100
        for i in range(0, len(msg_ids_to_delete), chunk_size):
            batch = msg_ids_to_delete[i:i + chunk_size]
            try:
                await client.delete_messages(chat_id=user_id, message_ids=batch)
                await asyncio.sleep(0.2)
            except Exception as e:
                print(f"Error deleting batch: {e}")

        try:
            await client.send_message(
                chat_id=user_id, 
                text="✅ <b>आपकी डिलीवरी फाइल्स और चैट सफलतापूर्वक साफ़ कर दी गई हैं!</b> 🗑️"
            )
        except Exception:
            pass

    except Exception as e:
        print(f"Clean chat error: {e}")
        await callback_query.answer("❌ फाइल्स पहले ही डिलीट हो चुकी हैं!", show_alert=True)

# ------------------ Mini App Web Data Receiver ------------------
@Client.on_message(filters.service & filter_webapp & filters.private)
async def web_app_data_handler(client, message):
    try:
        data = json.loads(message.web_app_data.data)
        action = data.get("action")
        story_title = data.get("title")
        price = float(data.get("price", 0))
        
        if action in ["view_demo", "demo", "get_demo"]:
            story = await get_story_by_title(story_title)
            if not story or not story.get("demo_enabled"):
                return await message.reply_text("⚠️ <b>इस स्टोरी का डेमो उपलब्ध नहीं है!</b>", quote=True)

            demo_ids = story.get("demo_msg_ids", [])
            if not demo_ids:
                return await message.reply_text("❌ <b>डेमो फाइल्स नहीं मिलीं!</b>", quote=True)

            user_id = message.from_user.id
            sent_messages = []

            header_msg = await message.reply_text(
                f"🎬 <b>ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ ғᴏᴏᴛᴀɢᴇ:</b> <code>{story['title']}</code>\n\n"
                f"⏰ <i>यह डेमो सैंपल 10 मिनट बाद अपने आप डिलीट हो जाएगा!</i>",
                quote=True
            )
            sent_messages.append(header_msg)

            for msg_id in demo_ids:
                try:
                    copied_msg = await client.copy_message(
                        chat_id=user_id,
                        from_chat_id=CHANNEL_ID,
                        message_id=msg_id,
                        caption=f"🎧 <b>Demo Sample</b> - {story['title']}"
                    )
                    sent_messages.append(copied_msg)
                except Exception as e:
                    print(f"Error copying demo msg {msg_id}: {e}")

            async def auto_delete_task(messages_list):
                await asyncio.sleep(600)
                for msg in messages_list:
                    try:
                        await msg.delete()
                    except Exception:
                        pass

            asyncio.create_task(auto_delete_task(sent_messages))
            return

        elif action == "buy_story":
            story = await get_story_by_title(story_title)
            if not story:
                return await message.reply_text("❌ <b>sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ.</b>", quote=True)

            clean_title = story_title.strip().split("\n")[0]
            encoded_title = clean_title.replace(" ", "_")
            wallet_bal = await get_user_wallet(message.from_user.id)
            
            inline_buttons = []
            
            if story.get('demo_enabled', False):
                inline_buttons.append([InlineKeyboardButton("🎬 ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ", callback_data=f"viewdemo_{encoded_title}")])

            inline_buttons.extend([
                [InlineKeyboardButton(f"💳 ᴅɪʀᴇᴄᴛ ᴘᴀʏ (₹{price})", callback_data=f"buy_{encoded_title}_{price}")],
                [InlineKeyboardButton(f"👛 ᴘᴀʏ ᴠɪᴀ ᴡᴀʟʟᴇᴛ (Bal: ₹{wallet_bal})", callback_data=f"walletpay_{encoded_title}_{price}")]
            ])
            
            btn = InlineKeyboardMarkup(inline_buttons)
            photo_url = story.get('photo', 'https://picsum.photos/400/200')

            caption_text = (
                f"🛒 <b>ᴏʀᴅᴇʀ ɪɴɪᴛɪᴀᴛᴇᴅ ғʀᴏᴍ ᴍɪɴɪ ᴀᴘᴘ</b>\n\n"
                f"♨️ <b>Story :</b> {clean_title}\n"
                f"🔰 <b>Status :</b> {story.get('status', 'Completed')}\n"
                f"🖥️ <b>Platform :</b> {story.get('category', 'Pocket FM')}\n"
                f"🧩 <b>Genre :</b> {story.get('genre', 'Drama')}\n"
                f"🎬 <b>Episodes :</b> {story.get('episodes', 'N/A')}\n\n"
                f"░▒▓█ PRICE - ₹{price} █▓▒░\n\n"
                f"👛 <b>ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ:</b> ₹{wallet_bal}\n\n"
                f"👇 <b>Select payment method to complete purchase:</b>"
            )
            
            try:
                await message.reply_photo(photo=photo_url, caption=caption_text, reply_markup=btn, quote=True)
            except Exception:
                await message.reply_text(caption_text, reply_markup=btn, quote=True)
    except Exception as e:
        print(f"WebApp Data Error: {e}")

# ------------------ View Demo Callback Handler ------------------
@Client.on_callback_query(filters.regex(r"^viewdemo_"))
async def view_demo_callback(client: Client, callback_query: CallbackQuery):
    try:
        encoded_title = callback_query.data.split("viewdemo_")[1]
        story_title = encoded_title.replace("_", " ")
        
        story = await get_story_by_title(story_title)
        if not story or not story.get("demo_enabled"):
            return await callback_query.answer("⚠️ Demo is not available for this story!", show_alert=True)
            
        demo_ids = story.get("demo_msg_ids", [])
        if not demo_ids:
            return await callback_query.answer("❌ No Demo files available!", show_alert=True)
            
        await callback_query.answer("🎬 Sending Demo files... Please check your chat!")
        
        user_id = callback_query.from_user.id
        sent_messages = []
        
        header_msg = await client.send_message(
            chat_id=user_id,
            text=f"🎬 <b>ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ ғᴏʀ:</b> <code>{story['title']}</code>\n\n"
                 f"⏰ <i>This demo preview will automatically delete in 10 minutes!</i>"
        )
        sent_messages.append(header_msg)
        
        for msg_id in demo_ids:
            try:
                copied_msg = await client.copy_message(
                    chat_id=user_id,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg_id,
                    caption=f"🎧 <b>Demo Sample</b> - {story['title']}"
                )
                sent_messages.append(copied_msg)
            except Exception as e:
                print(f"Error copying demo msg {msg_id}: {e}")

        async def auto_delete_task(messages_list):
            await asyncio.sleep(600)
            for msg in messages_list:
                try:
                    await msg.delete()
                except Exception:
                    pass
                    
        asyncio.create_task(auto_delete_task(sent_messages))

    except Exception as e:
        print(f"Error in view_demo_callback: {e}")
        await callback_query.answer("❌ Failed to send Demo files!", show_alert=True)

# ------------------ Wallet Payment Callback Handler ------------------
@Client.on_callback_query(filters.regex(r"^walletpay_"))
async def process_wallet_payment(client, callback_query):
    try:
        data_parts = callback_query.data.split("_")
        price = float(data_parts[-1])
        story_title = " ".join(data_parts[1:-1])

        story = await get_story_by_title(story_title)
        if not story:
            return await callback_query.answer("❌ Story not found!", show_alert=True)

        user_id = callback_query.from_user.id
        current_balance = await get_user_wallet(user_id)

        if current_balance < price:
            return await callback_query.answer(
                f"❌ Insufficient Balance!\nRequired: ₹{price}\nAvailable: ₹{current_balance}\n\nPlease top-up your wallet.",
                show_alert=True
            )

        clean_title = story['title'].strip().split("\n")[0]
        encoded_title = clean_title.replace(" ", "_")
        delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"

        new_balance = current_balance - price
        await update_user_wallet(user_id, new_balance)
        await add_user_purchase(user_id, clean_title, story_link=delivery_link)

        await callback_query.answer("🎉 Purchase successful! Story unlocked.", show_alert=True)
        
        success_text = (
            f"✅ <b>ᴘᴜʀᴄʜᴀsᴇ sᴜᴄᴄᴇssғᴜʟ!</b>\n\n"
            f"📖 <b>sᴛᴏʀʏ:</b> {clean_title}\n"
            f"💸 <b>ᴅᴇᴅᴜᴄᴛᴇᴅ:</b> ₹{price}\n"
            f"👛 <b>ʀᴇᴍᴀɪɴɪɴɢ ʙᴀʟᴀɴᴄᴇ:</b> ₹{new_balance}\n\n"
            f"👇 Click below to access your story files:"
        )
        
        access_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (Unlocked)", url=delivery_link)]
        ])
        
        await callback_query.message.edit_text(success_text, reply_markup=access_btn)

    except Exception as e:
        print(f"Error processing wallet payment: {e}")
        await callback_query.answer("❌ Error processing wallet payment!", show_alert=True)

# ------------------ Process Start Custom Range Input Text ------------------
@Client.on_message(filters.private & filters.text, group=4)
async def process_start_range_input(client, message):
    user_id = message.from_user.id
    if user_id not in START_RANGE_WAITING:
        return message.continue_propagation()
        
    text = message.text.strip()
    if "-" not in text:
        return await message.reply_text("❌ <b>गलत फॉर्मेट!</b> कृपया सही फॉर्मेट में लिखें, जैसे: <code>1-5</code>", quote=True)
        
    try:
        start_ep, end_ep = map(int, text.split("-"))
    except ValueError:
        return await message.reply_text("❌ <b>केवल नंबर लिखें</b> (जैसे <code>1-5</code>)।", quote=True)
        
    data = START_RANGE_WAITING.get(user_id)
    story = data['story']
    
    db_first = story['first_msg_id']
    db_last = story['last_msg_id']
    
    if start_ep < 1 or start_ep > end_ep:
        return await message.reply_text("❌ <b>अमान्य रेंज!</b> शुरुआत का नंबर 1 से कम या अंत वाले नंबर से बड़ा नहीं हो सकता।", quote=True)

    START_RANGE_WAITING.pop(user_id, None)

    clean_title = story['title'].strip().split("\n")[0]
    
    await send_story_files_start(
        client=client, 
        user_id=user_id, 
        story=story, 
        first_id=db_first, 
        last_id=db_last, 
        clean_title=clean_title, 
        custom_range_text=f"(Episodes {start_ep} - {end_ep})",
        target_start_ep=start_ep,
        target_end_ep=end_ep
    )

# ------------------ Reply Keyboard Action Handler (For Range & Stop Delivery Buttons) ------------------
@Client.on_message(filters.private & filters.text, group=2)
async def handle_range_reply_buttons(client, message):
    user_id = message.from_user.id
    text = message.text.strip()

    # 1. Stop Delivery Action Check (Highest Priority - Checked BEFORE active story check)
    if "stop delivery" in text.lower() or "sᴛᴏᴘ ᴅᴇʟɪᴠᴇʀʏ" in text:
        STOP_DELIVERY_USERS.add(user_id)
        return await message.reply_text("🛑 **डिलीवरी रोकी जा रही है... कृपया प्रतीक्षा करें!**", quote=True)

    if user_id not in USER_ACTIVE_STORY:
        return message.continue_propagation()

    story = USER_ACTIVE_STORY[user_id]
    clean_title = story['title'].strip().split("\n")[0]

    # 2. Cancel Clicked
    if text.lower() in ["❌ cancel", "cancel"]:
        USER_ACTIVE_STORY.pop(user_id, None)
        return await message.reply_text(
            "❌ <b>Process Cancelled.</b>", 
            reply_markup=MAIN_MENU,
            quote=True
        )

    # 3. Full Delivery Clicked
    elif "full delivery" in text.lower() or "all files" in text.lower():
        USER_ACTIVE_STORY.pop(user_id, None)
        await send_story_files_start(
            client=client,
            user_id=user_id,
            story=story,
            first_id=story['first_msg_id'],
            last_id=story['last_msg_id'],
            clean_title=clean_title
        )

    # 4. Custom Range Grid Button Clicked (e.g. "Files 2401 - 2500")
    elif text.startswith("Files "):
        range_name = text.replace("Files ", "").strip()
        custom_ranges = story.get('custom_ranges', [])
        
        target_range = next((r for r in custom_ranges if r['name'] == range_name), None)
        
        if target_range:
            USER_ACTIVE_STORY.pop(user_id, None)
            await send_story_files_start(
                client=client,
                user_id=user_id,
                story=story,
                first_id=target_range['first_id'],
                last_id=target_range['last_id'],
                clean_title=clean_title,
                custom_range_text=f"({range_name})"
            )
        else:
            return message.continue_propagation()
    else:
        return message.continue_propagation()

# ------------------ Start & Deep-Link Batch Delivery Handler ------------------
@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    user = message.from_user
    args = message.text.split(maxsplit=1)
    
    # Refer & Earn Logic
    try:
        registered = await is_user_registered(user.id)
        
        if len(args) > 1 and args[1].startswith("ref_"):
            try:
                referrer_id = int(args[1].split("_")[1])
                
                if referrer_id == user.id:
                    await message.reply_text(
                        "⚠️ <b>Hey dude, don't try to use your own referral link!</b>\n"
                        "<i>Share this link with your friends to earn rewards.</i>", 
                        quote=True
                    )
                elif not registered:
                    await register_user(user.id, user.first_name, user.username)
                    await users_col.update_one({"user_id": user.id}, {"$set": {"referred_by": referrer_id}})
                    
                    new_bal = await add_wallet_balance(referrer_id, REFER_BONUS)
                    
                    try:
                        await client.send_message(
                            chat_id=referrer_id,
                            text=f"🎉 <b>ɴᴇᴡ ʀᴇғᴇʀʀᴀʟ ᴀʟᴇʀᴛ!</b>\n\n"
                                 f"👤 <b>{user.first_name}</b> (<code>{user.id}</code>) ने आपके रेफरल लिंक से जॉइन किया है!\n"
                                 f"💰 आपको मिला: <b>₹{REFER_BONUS:.2f} Bonus</b>\n"
                                 f"👛 नया वॉलेट बैलेंस: <b>₹{new_bal}</b>"
                        )
                    except Exception:
                        pass
                        
                    try:
                        log_text = (
                            f"<b>🆕 ɴᴇᴡ ᴜsᴇʀ ʀᴇɢɪsᴛᴇʀᴇᴅ (Vɪᴀ Rᴇғᴇʀʀᴀʟ)!</b>\n"
                            f"<b>ɴᴀᴍᴇ:</b> {user.first_name}\n"
                            f"<b>ᴜsᴇʀ ɪᴅ:</b> <code>{user.id}</code>\n"
                            f"<b>ᴜsᴇʀɴᴀᴍᴇ:</b> @{user.username if user.username else 'None'}\n"
                            f"<b>ʀᴇғᴇʀʀᴇᴅ ʙʏ:</b> <code>{referrer_id}</code>"
                        )
                        await send_log(client, log_text)
                    except Exception:
                        pass
                else:
                    await message.reply_text(
                        "⚠️ <b>You are already an existing user of this bot!</b>\n"
                        "<i>Referral bonus is only valid for new users.</i>", 
                        quote=True
                    )
            except Exception as ref_err:
                print(f"Referral processing error: {ref_err}")

        elif not registered:
            await register_user(user.id, user.first_name, user.username)
            try:
                log_text = (
                    f"<b>🆕 ɴᴇᴡ ᴜsᴇʀ ʀᴇɢɪsᴛᴇʀᴇᴅ!</b>\n"
                    f"<b>ɴᴀᴍᴇ:</b> {user.first_name}\n"
                    f"<b>ᴜsᴇʀ ɪᴅ:</b> <code>{user.id}</code>\n"
                    f"<b>ᴜsᴇʀɴᴀᴍᴇ:</b> @{user.username if user.username else 'None'}"
                )
                await send_log(client, log_text)
            except Exception as e:
                print(f"Log Error: {e}")
                
    except Exception as db_err:
        print(f"Database Error in /start registration: {db_err}")

    # Deep-Link Logic
    if len(args) > 1 and args[1].startswith("get_"):
        raw_param = args[1]
        try:
            encoded_title = raw_param.replace("get_", "")
            story_title = encoded_title.replace("_", " ")
        except Exception:
            return await message.reply_text("❌ <b>ɪɴᴠᴀʟɪᴅ ᴏʀ ᴄᴏʀʀᴜᴘᴛᴇᴅ ʟɪɴᴋ!</b>", quote=True)

        story = await get_story_by_title(story_title)
        if not story:
            return await message.reply_text("❌ <b>sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ ɪɴ ᴅᴀᴛᴀʙᴀsᴇ!</b>", quote=True)

        clean_title = story['title'].strip().split("\n")[0]

        unlocked = await is_story_unlocked(user.id, clean_title)
        if not unlocked:
            buy_btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 ʙᴜʏ ɴᴏᴡ", callback_data=f"buy_{encoded_title}_{story['price']}")]
            ])
            return await message.reply_text(
                f"🔒 <b>ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ!</b>\n\n"
                f"You haven't purchased <b>{clean_title}</b> yet.\n"
                f"Please buy it first to unlock access.",
                reply_markup=buy_btn,
                quote=True
            )

        first_id = story.get('first_msg_id')
        last_id = story.get('last_msg_id')

        if not first_id or not last_id:
            return await message.reply_text("⚠️ <b>ɴᴏ ғɪʟᴇs ᴀssᴏᴄɪᴀᴛᴇᴅ ᴡɪᴛʜ ᴛʜɪs sᴛᴏʀʏ!</b>\nPlease contact support.", quote=True)

        total_files = (last_id - first_id) + 1
        custom_ranges = story.get('custom_ranges', [])

        USER_ACTIVE_STORY[user.id] = story

        if custom_ranges:
            reply_kb = build_custom_range_reply_keyboard(custom_ranges)
            return await message.reply_text(
                f"Select Files:\n\n"
                f"Which part would you like to receive?\n"
                f"Please use the keyboard options below.",
                reply_markup=reply_kb,
                quote=True
            )

        await send_story_files_start(client, user.id, story, first_id, last_id, clean_title)
        return

    if len(args) > 1 and args[1].startswith("story_"):
        raw_param = args[1]
        story_title = raw_param.replace("story_", "").replace("_", " ")
        story = await get_story_by_title(story_title)
        
        if story:
            clean_title = story['title'].strip().split("\n")[0]
            encoded_title = clean_title.replace(" ", "_")
            photo_url = story.get('photo', 'https://picsum.photos/400/200')
            wallet_bal = await get_user_wallet(user.id)
            
            miniapp_direct_url = f"{WEB_APP_URL}?tgWebAppStartParam={raw_param}"
            
            buttons = [
                [
                    InlineKeyboardButton(
                        "🚀 ᴏᴘᴇɴ ᴅɪʀᴇᴄᴛ sᴛᴏʀʏ ᴍɪɴɪ ᴀᴘᴘ", 
                        web_app=WebAppInfo(url=miniapp_direct_url)
                    )
                ]
            ]
            
            if story.get('demo_enabled', False):
                buttons.append([InlineKeyboardButton("🎬 ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ", callback_data=f"viewdemo_{encoded_title}")])

            buttons.append([
                InlineKeyboardButton(
                    f"🛒 ʙᴜʏ ɴᴏᴡ (₹{story['price']})", 
                    callback_data=f"buy_{encoded_title}_{story['price']}"
                )
            ])
            buttons.append([
                InlineKeyboardButton(
                    f"👛 ᴘᴀʏ ᴠɪᴀ ᴡᴀʟʟᴇᴛ (Bal: ₹{wallet_bal})", 
                    callback_data=f"walletpay_{encoded_title}_{story['price']}"
                )
            ])
            
            btn = InlineKeyboardMarkup(buttons)
            
            caption_text = (
                f"♨️ <b>Story :</b> {clean_title}\n"
                f"🔰 <b>Status :</b> {story.get('status', 'Completed')}\n"
                f"🖥️ <b>Platform :</b> {story.get('category', 'Pocket FM')}\n"
                f"🧩 <b>Genre :</b> {story.get('genre', 'Drama')}\n"
                f"🎬 <b>Episodes :</b> {story.get('episodes', 'N/A')}\n\n"
                f"░▒▓█ PRICE - ₹{story['price']} █▓▒░\n\n"
                f"👛 <b>ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ:</b> ₹{wallet_bal}\n\n"
                f"<i>👇 Choose an option below to view or purchase:</i>"
            )
            
            try:
                return await message.reply_photo(photo=photo_url, caption=caption_text, reply_markup=btn, quote=True)
            except Exception:
                return await message.reply_text(caption_text, reply_markup=btn, quote=True)
        else:
            return await message.reply_text("❌ <b>ᴛʜɪs sᴛᴏʀʏ ɪs ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ.</b>", reply_markup=MAIN_MENU, quote=True)

    # Normal /start Welcome Message
    welcome_text = (
        f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"🌟 <b>STORY SELLER BOT</b> 🌟\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"<b>HELLO {user.first_name}! 👋</b>\n\n"
        f"<b>USE THE BUTTONS BELOW TO SEARCH OR PURCHASE YOUR FAVORITE STORIES.</b>"
    )
    await message.reply_text(welcome_text, reply_markup=MAIN_MENU, quote=True)

# ------------------ Wallet System Handlers ------------------

@Client.on_message(filters.regex("^(💼 ᴍʏ ᴡᴀʟʟᴇᴛ|💼 My Wallet)$") & filters.private)
async def wallet_handler(client, message):
    user_id = message.from_user.id
    balance = await get_user_wallet(user_id)
    
    text = (
        f"<b>👛 ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ ᴅᴇᴛᴀɪʟs</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"<b>💳 ᴄᴜʀʀᴇɴᴛ ʙᴀʟᴀɴᴄᴇ:</b> ₹{balance}\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 <i>Use wallet balance for 1-click instant purchases inside Mini App or Bot.</i>"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ᴀᴅᴅ ᴍᴏɴᴇʏ / ᴛᴏᴘ-ᴜᴘ", callback_data="add_wallet_funds")]
    ])
    
    await message.reply_text(text, reply_markup=kb, quote=True)

@Client.on_callback_query(filters.regex("^add_wallet_funds$"))
async def add_funds_callback(client, callback_query):
    text = (
        "<b>➕ ᴀᴅᴅ ᴍᴏɴᴇʏ ᴛᴏ ᴡᴀʟʟᴇᴛ</b>\n\n"
        "Contact admin or send payment screenshot to top-up your wallet balance automatically."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ ғᴏᴏʀ ᴛᴏᴘᴜᴘ", url="https://t.me/kaluu_help_bot")]
    ])
    await callback_query.message.edit_text(text, reply_markup=kb)

# ------------------ Refer & Earn Keyboard Handler ------------------

@Client.on_message(filters.regex("^(🎁 ʀᴇғᴇʀ & ᴇᴀʀɴ|🎁 Refer & Earn)$") & filters.private)
async def refer_earn_handler(client, message):
    user_id = message.from_user.id
    refer_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    
    wallet = await get_user_wallet(user_id)
    total_refs = await get_referred_users_count(user_id)
    
    text = (
        f"🎁 <b><u>ʀᴇғᴇʀ & ᴇᴀʀɴ ᴘʀᴏɢʀᴀᴍ</u></b>\n\n"
        f"अपने दोस्तों को बॉट शेयर करें और हर नए यूज़र के जॉइन करने पर पाएँ <b>₹1.00</b> डायरेक्ट वॉलेट में!\n\n"
        f"📊 <b>आपकी डिटेल्स:</b>\n"
        f"👥 <b>Total Referred:</b> {total_refs} Users\n"
        f"👛 <b>Wallet Balance:</b> ₹{wallet}\n\n"
        f"🔗 <b>आपका पर्सनल रेफरल लिंक:</b>\n"
        f"<code>{refer_link}</code>"
    )
    
    share_text = quote("✨ सुनो! इस बॉट पर ऑडियो स्टोरीज़ और पॉडकास्ट आसानी से मिल जाते हैं। तुरंत जॉइन करो:")
    share_url = f"https://t.me/share/url?url={quote(refer_link)}&text={share_text}"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 दोस्तों को शेयर करें", url=share_url)],
        [InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="close_message")]
    ])
    
    await message.reply_text(text, reply_markup=kb, disable_web_page_preview=True, quote=True)

# ------------------ Dynamic Button Handlers (With Close Buttons) ------------------

@Client.on_message(filters.regex("^(🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ|🚀 Open Mini App)$") & filters.private)
async def open_miniapp_handler(client, message):
    text = (
        "🚀 <b>ᴍɪɴɪ sᴛᴏʀᴇ ᴀᴘᴘ</b>\n\n"
        "ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴏᴘᴇɴ ᴏᴜʀ ᴏғғɪᴄɪᴀʟ ᴍɪɴɪ ᴀᴘᴘ ᴀɴᴅ ᴇxᴘʟᴏʀᴇ ᴀʟʟ sᴛᴏʀɪᴇs!"
    )
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 ʟᴀᴜɴᴄʜ ᴍɪɴɪ ᴀᴘᴘ", web_app=WebAppInfo(url=WEB_APP_URL))],
        [InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="close_message")]
    ])
    await message.reply_text(text, reply_markup=btn, quote=True)

@Client.on_message(filters.regex("^(📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ|📢 Updates Channel)$") & filters.private)
async def updates_handler(client, message):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ", url="https://t.me/freestoryhubMR")],
        [InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="close_message")]
    ])
    await message.reply_text("<b>📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ:</b>\n\nᴊᴏɪɴ ᴏᴜʀ ᴄʜᴀɴɴᴇʟ ғᴏᴏʀ ᴛʜᴇ ʟᴀᴛᴇsᴛ ᴜᴘᴅᴀᴛᴇs ᴀɴᴅ ɴᴇᴡ sᴛᴏʀɪᴇs!", reply_markup=kb, quote=True)

@Client.on_message(filters.regex("^(👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ|👤 My Account)$") & filters.private)
async def account_handler(client, message):
    user = message.from_user
    purchases = await get_user_purchases(user.id)
    balance = await get_user_wallet(user.id)
    
    acc_text = (
        f"<b>👤 ᴀᴄᴄᴏᴜɴᴛ ᴅᴇᴛᴀɪʟs:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"<b>ɴᴀᴍᴇ:</b> {user.first_name}\n"
        f"<b>ᴜsᴇʀ ɪᴅ:</b> <code>{user.id}</code>\n"
        f"<b>ᴜsᴇʀɴᴀᴍᴇ:</b> @{user.username if user.username else 'N/A'}\n"
        f"<b>👛 ᴡᴀʟʟᴇᴛ ʙᴀʟᴀɴᴄᴇ:</b> ₹{balance}\n"
        f"<b>sᴛᴀᴛᴜs:</b> ᴀᴄᴛɪᴠᴇ ᴜsᴇʀ ⚡\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    buttons = []
    
    if not purchases:
        acc_text += "❌ <b>ʏᴏᴜ ʜᴀᴠᴇɴ'ᴛ ᴘᴜʀᴄʜᴀsᴇᴅ ᴀɴʏ sᴛᴏʀɪᴇs ʏᴇᴛ.</b>"
    else:
        acc_text += "📖 <b>ʏᴏᴜʀ ᴘᴜʀᴄʜᴀsᴇᴅ sᴛᴏʀɪᴇs:</b>\n\n"
        for item in purchases:
            story = await get_story_by_title(item['story_title'])
            if story:
                clean_title = story['title'].strip().split("\n")[0]
                encoded_title = clean_title.replace(" ", "_")
                delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"
                
                acc_text += f"• <b>{clean_title}</b>\n"
                buttons.append([InlineKeyboardButton(f"🚀 ᴀᴄᴄᴇss {clean_title}", url=delivery_link)])
            
    buttons.append([InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="close_message")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await message.reply_text(acc_text, reply_markup=reply_markup, quote=True)

@Client.on_message(filters.regex("^(📞 sᴜᴘᴘᴏʀᴛ|📞 Support)$") & filters.private)
async def support_handler(client, message):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ", url="https://t.me/pratilipifm0900")],
        [InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="close_message")]
    ])
    await message.reply_text("<b>📞 ᴄᴜsᴛᴏᴍᴇʀ sᴜᴘᴘᴏʀᴛ:</b>\n\nɪғ ʏᴏᴜ ғᴀᴄᴇ ᴀɴʏ ɪssᴜᴇs, ғᴇᴇʟ ғʀᴇᴇ ᴛᴏ ᴄᴏɴᴛᴀᴄᴛ support.", reply_markup=kb, quote=True)
