import json
import asyncio
import time
import re
from urllib.parse import quote as url_quote
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait, MessageNotModified
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

# Storage Dictionaries
START_RANGE_WAITING = {}
USER_ACTIVE_STORY = {}
USER_PAGINATION_PAGE = {}
USER_ACCOUNT_PAGINATION = {}

# Storage Set for Delivery Stop Control
STOP_DELIVERY_USERS = set()

# 1. Main Menu Keyboard Layout
MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ", style=enums.ButtonStyle.PRIMARY)],
        [KeyboardButton("🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ", style=enums.ButtonStyle.PRIMARY)],
        [KeyboardButton("📻 ᴘᴏᴄᴋᴇᴛ ғᴍ", style=enums.ButtonStyle.PRIMARY), KeyboardButton("📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ", style=enums.ButtonStyle.PRIMARY)],
        [KeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴇɴᴜ", style=enums.ButtonStyle.PRIMARY)]
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
    await callback_query.answer("🛑 sᴛᴏᴘᴘɪɴɢ ᴅᴇʟɪᴠᴇʀʏ... ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ!", show_alert=True)

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

# ------------------ Helper: Dynamic Reply Keyboard Grid Generator with Pagination (10/10) ------------------
def build_custom_range_reply_keyboard(custom_ranges, page=0, per_page=10):
    total_ranges = len(custom_ranges)
    start_idx = page * per_page
    end_idx = start_idx + per_page
    current_page_ranges = custom_ranges[start_idx:end_idx]

    keyboard_rows = []
    current_row = []

    for r in current_page_ranges:
        btn_text = f"Files {r['name']}"
        current_row.append(KeyboardButton(btn_text))
        
        if len(current_row) == 2:
            keyboard_rows.append(current_row)
            current_row = []

    if current_row:
        keyboard_rows.append(current_row)

    nav_row = []
    if page > 0:
        nav_row.append(KeyboardButton("◀️ ʙᴀᴄᴋ", style=enums.ButtonStyle.PRIMARY))
    if total_ranges > 0:
        nav_row.append(KeyboardButton("👁️‍🗨️ ᴠɪᴇᴡ ᴀʟʟ", style=enums.ButtonStyle.PRIMARY))
    if end_idx < total_ranges:
        nav_row.append(KeyboardButton("ɴᴇxᴛ ▶️", style=enums.ButtonStyle.PRIMARY))

    if nav_row:
        keyboard_rows.append(nav_row)

    keyboard_rows.append([KeyboardButton("📦 ғᴜʟʟ ᴅᴇʟɪᴠᴇʀʏ (ᴀʟʟ ғɪʟᴇs)", style=enums.ButtonStyle.PRIMARY)])
    keyboard_rows.append([KeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER)])

    return ReplyKeyboardMarkup(
        keyboard=keyboard_rows,
        resize_keyboard=True,
        one_time_keyboard=False  
    )

# ------------------ Helper: Smart File Delivery Function ------------------
async def send_story_files_start(client, user_id, story, first_id, last_id, clean_title, custom_range_text="", target_start_ep=None, target_end_ep=None):
    sent_messages_obj = []
    sent_message_ids = []
    success_count = 0

    if user_id in STOP_DELIVERY_USERS:
        STOP_DELIVERY_USERS.remove(user_id)

    chosen_sticker = SEARCH_RANGE_STICKER_ID if target_start_ep is not None else DELIVERY_STICKER_ID

    stop_reply_keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("🛑 sᴛᴏᴘ ᴅᴇʟɪᴠᴇʀʏ", style=enums.ButtonStyle.PRIMARY)]],
        resize_keyboard=True
    )

    try:
        status_sticker = await client.send_sticker(
            chat_id=user_id,
            sticker=chosen_sticker,
            reply_markup=stop_reply_keyboard
        )
    except Exception:
        status_sticker = None

    progress_msg = await client.send_message(
        chat_id=user_id,
        text=f"📦 <b>ᴅᴇʟɪᴠᴇʀɪɴɢ ғɪʟᴇs...</b>\n\n"
             f"📖 <b>sᴛᴏʀʏ:</b> {clean_title}\n"
             f"⏳ <i>ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ, ғɪʟᴇs ᴀʀᴇ ʙᴇɪɴɢ sᴇɴᴛ...</i>\n\n"
             f"<i>ᴘʀᴇss '🛑 sᴛᴏᴘ ᴅᴇʟɪᴠᴇʀʏ' ʙᴇʟᴏᴡ ᴛᴏ ᴄᴀɴᴄᴇʟ.</i>",
        reply_markup=stop_reply_keyboard
    )

    is_stopped_by_user = False

    for msg_id in range(first_id, last_id + 1):
        if user_id in STOP_DELIVERY_USERS:
            is_stopped_by_user = True
            STOP_DELIVERY_USERS.remove(user_id)
            break

        msg = None
        while True:
            try:
                msg = await client.get_messages(chat_id=CHANNEL_ID, message_ids=msg_id)
                break
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
            except Exception as e:
                print(f"Error fetching msg {msg_id}: {e}")
                break

        if not msg or msg.empty:
            continue

        searchable_text = get_message_searchable_text(msg)
        ep_num = extract_episode_number(searchable_text)

        if target_start_ep is not None and target_end_ep is not None:
            if ep_num is None or not (target_start_ep <= ep_num <= target_end_ep):
                continue

        while True:
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

                if success_count % 3 == 0:
                    try:
                        await progress_msg.edit_text(
                            f"📦 <b>ᴅᴇʟɪᴠᴇʀɪɴɢ ғɪʟᴇs...</b>\n\n"
                            f"📖 <b>sᴛᴏʀʏ:</b> {clean_title}\n"
                            f"📊 <b>ᴅᴇʟɪᴠᴇʀᴇᴅ:</b> {success_count} Files\n\n"
                            f"<i>ᴘʀᴇss '🛑 sᴛᴏᴘ ᴅᴇʟɪᴠᴇʀʏ' ʙᴇʟᴏᴡ ᴛᴏ ᴄᴀɴᴄᴇʟ.</i>"
                        )
                    except Exception:
                        pass
                break

            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
            except Exception as e:
                print(f"Error copying msg {msg.id}: {e}")
                break

        await asyncio.sleep(1.8)

    try:
        if status_sticker: await status_sticker.delete()
        await progress_msg.delete()
    except Exception:
        pass

    if is_stopped_by_user:
        if sent_message_ids:
            first_sent_id = sent_message_ids[0]
            last_sent_id = sent_message_ids[-1]
            encoded_title = clean_title.replace(" ", "_")
            
            clean_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🧹 ᴄʟᴇᴀɴ / ᴅᴇʟᴇᴛᴇ ᴀʟʟ ғɪʟᴇs", style=enums.ButtonStyle.PRIMARY, callback_data=f"rangechatclean_{first_sent_id}_{last_sent_id}")],
                [InlineKeyboardButton("🔄 ʀᴇɢᴇɴᴇʀᴀᴛᴇ ғɪʟᴇ", style=enums.ButtonStyle.PRIMARY, callback_data=f"regenerate_{encoded_title}")]
            ])
        else:
            clean_kb = ReplyKeyboardRemove()

        await client.send_message(
            chat_id=user_id,
            text=f"🛑 <b>ᴅᴇʟɪᴠᴇʀʏ sᴛᴏᴘᴘᴇᴅ ʙʏ ᴜsᴇʀ!</b>\n\n"
                 f"📖 <b>sᴛᴏʀʏ:</b> {clean_title}\n"
                 f"📦 <b>ᴅᴇʟɪᴠᴇʀᴇᴅ:</b> {success_count} Files",
            reply_markup=clean_kb
        )
        return

    if success_count == 0:
        return await client.send_message(
            chat_id=user_id,
            text=f"❌ <b>ɴᴏ ᴍᴀᴛᴄʜɪɴɢ ғɪʟᴇs ғᴏᴜɴᴅ!</b>\n\n"
                 f"No files available for range <b>{custom_range_text}</b>.",
            reply_markup=MAIN_MENU
        )

    ep_range = get_exact_episode_range(sent_messages_obj) if sent_messages_obj else "Files Range"
    encoded_title = clean_title.replace(" ", "_")
    
    if sent_message_ids:
        first_sent_id = sent_message_ids[0]
        last_sent_id = sent_message_ids[-1]
        
        clean_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧹 ᴄʟᴇᴀɴ / ᴅᴇʟᴇᴛᴇ ᴀʟʟ ғɪʟᴇs", style=enums.ButtonStyle.PRIMARY, callback_data=f"rangechatclean_{first_sent_id}_{last_sent_id}")],
            [InlineKeyboardButton("🔄 ʀᴇɢᴇɴᴇʀᴀᴛᴇ ғɪʟᴇ", style=enums.ButtonStyle.PRIMARY, callback_data=f"regenerate_{encoded_title}")]
        ])
    else:
        clean_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 ʀᴇɢᴇɴᴇʀᴀᴛᴇ ғɪʟᴇ", style=enums.ButtonStyle.PRIMARY, callback_data=f"regenerate_{encoded_title}")]
        ])

    await client.send_message(
        chat_id=user_id,
        text=f"🎉 <b>ғɪʟᴇs ᴅᴇʟɪᴠᴇʀᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
             f"📖 <b>sᴛᴏʀʏ:</b> {clean_title}\n"
             f"🎧 <b>ʀᴀɴɢᴇ:</b> {ep_range} {custom_range_text}\n"
             f"📦 <b>ᴅᴇʟɪᴠᴇʀᴇᴅ:</b> {success_count} Files\n\n"
             f"<i>Click below to clean messages or regenerate files:</i>",
        reply_markup=clean_kb
    )

# ------------------ Regenerate File Callback Handler ------------------
@Client.on_callback_query(filters.regex(r"^regenerate_"))
async def regenerate_file_handler(client, callback_query):
    user_id = callback_query.from_user.id
    try:
        encoded_title = callback_query.data.split("regenerate_")[1]
        story_title = encoded_title.replace("_", " ")

        story = await get_story_by_title(story_title)
        if not story:
            return await callback_query.answer("❌ Story not found in database!", show_alert=True)

        clean_title = story['title'].strip().split("\n")[0]
        custom_ranges = story.get('custom_ranges', [])

        USER_ACTIVE_STORY[user_id] = story
        USER_PAGINATION_PAGE[user_id] = 0

        await callback_query.answer("🔄 Regenerating files...")

        if custom_ranges:
            reply_kb = build_custom_range_reply_keyboard(custom_ranges, page=0)
            await client.send_message(
                chat_id=user_id,
                text=f"📖 <b>sᴛᴏʀʏ:</b> {clean_title}\n\n"
                     f"<i>Please select the range or option to deliver files again:</i>",
                reply_markup=reply_kb
            )
        else:
            first_id = story.get('first_msg_id')
            last_id = story.get('last_msg_id')
            await send_story_files_start(client, user_id, story, first_id, last_id, clean_title)

    except Exception as e:
        print(f"Regenerate Error: {e}")
        await callback_query.answer("❌ Error regenerating files!", show_alert=True)

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
                await asyncio.sleep(0.5)
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
            except Exception as e:
                print(f"Error deleting batch: {e}")

        try:
            await client.send_message(
                chat_id=user_id, 
                text="✅ <b>Your delivered files and chat cleared successfully!</b> 🗑️"
            )
        except Exception:
            pass

    except Exception as e:
        print(f"Clean chat error: {e}")
        await callback_query.answer("❌ Files already deleted!", show_alert=True)

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
                return await message.reply_text("⚠️ <b>Demo not available for this story!</b>")

            demo_ids = story.get("demo_msg_ids", [])
            if not demo_ids:
                return await message.reply_text("❌ <b>Demo files not found!</b>")

            user_id = message.from_user.id
            sent_messages = []

            header_msg = await message.reply_text(
                f"🎬 <b>ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ ғᴏᴏᴛᴀɢᴇ:</b> <code>{story['title']}</code>\n\n"
                f"⏰ <i>This demo will automatically delete in 10 minutes!</i>"
            )
            sent_messages.append(header_msg)

            for msg_id in demo_ids:
                try:
                    copied_msg = await client.copy_message(
                        chat_id=user_id,
                        from_chat_id=CHANNEL_ID,
                        message_id=msg_id,
                        caption=f"🎧 <b>Demo Sample</b> - {story['title']}",
                        protect_content=True
                    )
                    sent_messages.append(copied_msg)
                    await asyncio.sleep(1.5)
                except FloodWait as e:
                    await asyncio.sleep(e.value + 1)
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
                return await message.reply_text("❌ <b>sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ.</b>")

            clean_title = story_title.strip().split("\n")[0]
            encoded_title = clean_title.replace(" ", "_")
            wallet_bal = await get_user_wallet(message.from_user.id)
            
            inline_buttons = []
            
            if story.get('demo_enabled', False):
                inline_buttons.append([InlineKeyboardButton("🎬 ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ", style=enums.ButtonStyle.PRIMARY, callback_data=f"viewdemo_{encoded_title}")])

            inline_buttons.extend([
                [InlineKeyboardButton(f"💳 ᴅɪʀᴇᴄᴛ ᴘᴀʏ (₹{price})", style=enums.ButtonStyle.PRIMARY, callback_data=f"buy_{encoded_title}_{price}")],
                [InlineKeyboardButton(f"👛 ᴘᴀʏ ᴠɪᴀ ᴡᴀʟʟᴇᴛ (Bal: ₹{wallet_bal})", style=enums.ButtonStyle.PRIMARY, callback_data=f"walletpay_{encoded_title}_{price}")]
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
                await message.reply_photo(photo=photo_url, caption=caption_text, reply_markup=btn)
            except Exception:
                await message.reply_text(caption_text, reply_markup=btn)
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
            text=f"🎬 <b>ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ ғᴏᴏᴛᴀɢᴇ:</b> <code>{story['title']}</code>\n\n"
                 f"⏰ <i>This demo preview will automatically delete in 10 minutes!</i>"
        )
        sent_messages.append(header_msg)
        
        for msg_id in demo_ids:
            try:
                copied_msg = await client.copy_message(
                    chat_id=user_id,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg_id,
                    caption=f"🎧 <b>Demo Sample</b> - {story['title']}",
                    protect_content=True
                )
                sent_messages.append(copied_msg)
                await asyncio.sleep(1.5)
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
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
            [InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (Unlocked)", style=enums.ButtonStyle.PRIMARY, url=delivery_link)]
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
        return await message.reply_text("❌ <b>ɪɴᴠᴀʟɪᴅ ғᴏʀᴍᴀᴛ!</b> Please enter in format e.g., <code>1-5</code>")
        
    try:
        start_ep, end_ep = map(int, text.split("-"))
    except ValueError:
        return await message.reply_text("❌ <b>ɴᴜᴍʙᴇʀs ᴏɴʟʏ!</b> Enter numbers like <code>1-5</code>.")
        
    data = START_RANGE_WAITING.get(user_id)
    story = data['story']
    
    db_first = story['first_msg_id']
    db_last = story['last_msg_id']
    
    if start_ep < 1 or start_ep > end_ep:
        return await message.reply_text("❌ <b>ɪɴᴠᴀʟɪᴅ ʀᴀɴɢᴇ!</b> Start number cannot be less than 1 or greater than end number.")

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

# ------------------ Reply Keyboard Action & Pagination Handler ------------------
@Client.on_message(filters.private & filters.text, group=2)
async def handle_range_reply_buttons(client, message):
    user_id = message.from_user.id
    text = message.text.strip()

    if re.search(r"(?i)(stop delivery|sᴛᴏᴘ ᴅᴇʟɪᴠᴇʀʏ|🛑)", text):
        STOP_DELIVERY_USERS.add(user_id)
        return

    if user_id not in USER_ACTIVE_STORY:
        return message.continue_propagation()

    story = USER_ACTIVE_STORY[user_id]
    clean_title = story['title'].strip().split("\n")[0]
    custom_ranges = story.get('custom_ranges', [])
    current_page = USER_PAGINATION_PAGE.get(user_id, 0)

    if text.lower() in ["❌ cancel", "❌ ᴄᴀɴᴄᴇʟ"]:
        USER_ACTIVE_STORY.pop(user_id, None)
        USER_PAGINATION_PAGE.pop(user_id, None)
        return await message.reply_text(
            "❌ <b>ᴘʀᴏᴄᴇss ᴄᴀɴᴄᴇʟʟᴇᴅ.</b>", 
            reply_markup=MAIN_MENU
        )

    elif text == "ɴᴇxᴛ ▶️":
        new_page = current_page + 1
        USER_PAGINATION_PAGE[user_id] = new_page
        reply_kb = build_custom_range_reply_keyboard(custom_ranges, page=new_page)
        return await message.reply_text("📖 <b>sᴇʟᴇᴄᴛ ғɪʟᴇs (ɴᴇxᴛ ᴘᴀɢᴇ):</b>", reply_markup=reply_kb)

    elif text == "◀️ ʙᴀᴄᴋ":
        new_page = max(0, current_page - 1)
        USER_PAGINATION_PAGE[user_id] = new_page
        reply_kb = build_custom_range_reply_keyboard(custom_ranges, page=new_page)
        return await message.reply_text("📖 <b>sᴇʟᴇᴄᴛ ғɪʟᴇs (ᴘʀᴇᴠɪᴏᴜs ᴘᴀɢᴇ):</b>", reply_markup=reply_kb)

    elif text in ["👁️‍🗨️ ᴠɪᴇᴡ ᴀʟʟ", "View All"]:
        USER_PAGINATION_PAGE.pop(user_id, None)
        reply_kb = build_custom_range_reply_keyboard(custom_ranges, page=0, per_page=len(custom_ranges))
        return await message.reply_text("👁️‍🗨️ <b>Aʟʟ Aᴠᴀɪʟᴀʙʟᴇ Fɪʟᴇ Rᴀɴɢᴇs:</b>", reply_markup=reply_kb)

    elif re.search(r"(?i)(full delivery|all files|📦)", text):
        USER_ACTIVE_STORY.pop(user_id, None)
        USER_PAGINATION_PAGE.pop(user_id, None)
        await send_story_files_start(
            client=client,
            user_id=user_id,
            story=story,
            first_id=story['first_msg_id'],
            last_id=story['last_msg_id'],
            clean_title=clean_title
        )

    elif text.startswith("Files "):
        range_name = text.replace("Files ", "").strip()
        target_range = next((r for r in custom_ranges if r['name'] == range_name), None)
        
        if target_range:
            USER_ACTIVE_STORY.pop(user_id, None)
            USER_PAGINATION_PAGE.pop(user_id, None)
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
    
    try:
        registered = await is_user_registered(user.id)
        
        if len(args) > 1 and args[1].startswith("ref_"):
            try:
                referrer_id = int(args[1].split("_")[1])
                
                if referrer_id == user.id:
                    await message.reply_text(
                        "⚠️ <b>Self-referrals are not allowed!</b>\n"
                        "<i>Share your link with friends to earn rewards.</i>"
                    )
                elif not registered:
                    await register_user(user.id, user.first_name, user.username)
                    await users_col.update_one({"user_id": user.id}, {"$set": {"referred_by": referrer_id}})
                    
                    new_bal = await add_wallet_balance(referrer_id, REFER_BONUS)
                    
                    try:
                        await client.send_message(
                            chat_id=referrer_id,
                            text=f"🎉 <b>ɴᴇᴡ ʀᴇғᴇʀʀᴀʟ ᴀʟᴇʀᴛ!</b>\n\n"
                                 f"👤 <b>{user.first_name}</b> (<code>{user.id}</code>) joined via your link!\n"
                                 f"💰 Bonus received: <b>₹{REFER_BONUS:.2f}</b>\n"
                                 f"👛 New Balance: <b>₹{new_bal}</b>"
                        )
                    except Exception:
                        pass
                        
                    try:
                        log_text = (
                            f"<b>🆕 ɴᴇᴡ ᴜsᴇʀ ʀᴇɢɪsᴛᴇʀᴇᴅ (ᴠɪᴀ ʀᴇғᴇʀʀᴀʟ)!</b>\n"
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
                        "⚠️ <b>You are already a registered user!</b>\n"
                        "<i>Referral bonus applies to new users only.</i>"
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
            return await message.reply_text("❌ <b>ɪɴᴠᴀʟɪᴅ ᴏʀ ᴄᴏʀʀᴜᴘᴛᴇᴅ ʟɪɴᴋ!</b>")

        story = await get_story_by_title(story_title)
        if not story:
            return await message.reply_text("❌ <b>sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ ɪɴ ᴅᴀᴛᴀʙᴀsᴇ!</b>")

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
                reply_markup=buy_btn
            )

        first_id = story.get('first_msg_id')
        last_id = story.get('last_msg_id')

        if not first_id or not last_id:
            return await message.reply_text("⚠️ <b>ɴᴏ ғɪʟᴇs ᴀssᴏᴄɪᴀᴛᴇᴅ ᴡɪᴛʜ ᴛʜɪs sᴛᴏʀʏ!</b>\nPlease contact support.")

        custom_ranges = story.get('custom_ranges', [])

        USER_ACTIVE_STORY[user.id] = story
        USER_PAGINATION_PAGE[user.id] = 0

        if custom_ranges:
            reply_kb = build_custom_range_reply_keyboard(custom_ranges, page=0)
            return await message.reply_text(
                f"<b>sᴇʟᴇᴄᴛ ғɪʟᴇs:</b>\n\n"
                f"Which part would you like to receive?\n"
                f"Please use the keyboard options below.",
                reply_markup=reply_kb
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
                        "🚀 ᴏᴘᴇɴ ᴅɪʀᴇᴄᴛ sᴛᴏʀʏ ᴍɪɴɪ ᴀᴘᴘ", style=enums.ButtonStyle.PRIMARY, 
                        web_app=WebAppInfo(url=miniapp_direct_url)
                    )
                ]
            ]
            
            if story.get('demo_enabled', False):
                buttons.append([InlineKeyboardButton("🎬 ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ", style=enums.ButtonStyle.PRIMARY, callback_data=f"viewdemo_{encoded_title}")])

            buttons.append([
                InlineKeyboardButton(
                    f"🛒 ʙᴜʏ ɴᴏᴡ (₹{story['price']})", style=enums.ButtonStyle.PRIMARY,
                    callback_data=f"buy_{encoded_title}_{story['price']}"
                )
            ])
            buttons.append([
                InlineKeyboardButton(
                    f"👛 ᴘᴀʏ ᴠɪᴀ ᴡᴀʟʟᴇᴛ (Bal: ₹{wallet_bal})", style=enums.ButtonStyle.PRIMARY,
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
                return await message.reply_photo(photo=photo_url, caption=caption_text, reply_markup=btn)
            except Exception:
                return await message.reply_text(caption_text, reply_markup=btn)
        else:
            return await message.reply_text("❌ <b>ᴛʜɪs sᴛᴏʀʏ ɪs ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ.</b>", reply_markup=MAIN_MENU)

    # Normal /start Welcome Message
    sent_msg = await message.reply_text("Pʟᴇᴀsᴇ Wᴀɪᴛ...")
    await asyncio.sleep(0.5)

    welcome_text = (
        f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"🌟 <b>sᴛᴏʀʏ sᴇʟʟᴇʀ ʙᴏᴛ</b> 🌟\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"<b>ʜᴇʟʟᴏ {user.first_name}! 👋</b>\n\n"
        f"ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴏᴜʀ ʙᴏᴛ. ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ ᴏᴘᴇɴ ᴛʜᴇ ᴍᴀʀᴋᴇᴛ, ᴄʜᴇᴄᴋ ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ, ᴏʀ ᴠɪᴇᴡ ʏᴏᴜʀ ᴀᴄᴄᴏᴜɴᴛ:"
    )

    start_inline_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛒 ᴏᴘᴇɴ ᴍᴀʀᴋᴇᴛ / sᴛᴏʀᴇ", callback_data="open_market_cb", style=enums.ButtonStyle.PRIMARY)
        ],
        [
            InlineKeyboardButton("💼 ᴍʏ ᴡᴀʟʟᴇᴛ", callback_data="open_wallet_cb", style=enums.ButtonStyle.PRIMARY),
            InlineKeyboardButton("👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ", callback_data="open_account_cb", style=enums.ButtonStyle.PRIMARY)
        ],
        [
            InlineKeyboardButton("🎁 ʀᴇғᴇʀ & ᴇᴀʀɴ", callback_data="open_refer_cb", style=enums.ButtonStyle.PRIMARY)
        ],
        [
            InlineKeyboardButton("📢 ᴜᴘᴅᴀᴛᴇs", url="https://t.me/freestoryhubMR", style=enums.ButtonStyle.PRIMARY),
            InlineKeyboardButton("📞 sᴜᴘᴘᴏʀᴛ", url="https://t.me/pratilipifm0900", style=enums.ButtonStyle.PRIMARY)
        ]
    ])

    await sent_msg.edit_text(welcome_text, reply_markup=start_inline_kb)

# ------------------ Open Market Callback Handler ------------------
@Client.on_callback_query(filters.regex("^open_market_cb$"))
async def open_market_callback(client, callback_query):
    await callback_query.answer("🛒 Market Opened!")
    
    try:
        await callback_query.message.delete()
    except Exception as e:
        print(f"Error deleting welcome msg: {e}")

    await client.send_message(
        chat_id=callback_query.from_user.id,
        text="🛒 <b>ᴍᴀʀᴋᴇᴛ & sᴇᴀʀᴄʜ ᴍᴇɴᴜ</b>\n\n"
             "👇 Select a platform or search for your favorite story using the keyboard below:",
        reply_markup=MAIN_MENU
    )

# ------------------ Helper: Account Details & Pagination Renderer ------------------
async def send_or_edit_account_details(client, user, message_or_cb, page=0, is_callback=False):
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
        total_purchases = len(purchases)
        per_page = 10
        total_pages = (total_purchases + per_page - 1) // per_page
        
        page = max(0, min(page, total_pages - 1))
        USER_ACCOUNT_PAGINATION[user.id] = page

        start_idx = page * per_page
        end_idx = start_idx + per_page
        current_page_items = purchases[start_idx:end_idx]

        acc_text += f"📖 <b>ʏᴏᴜʀ ᴘᴜʀᴄʜᴀsᴇᴅ sᴛᴏʀɪᴇs ({total_purchases}):</b>\n"
        acc_text += f"<i>Page {page + 1} of {total_pages}</i>\n\n"
        
        for item in current_page_items:
            story_title = item.get('story_title', '')
            clean_title = story_title.strip().split("\n")[0]
            encoded_title = clean_title.replace(" ", "_")
            delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"
            
            acc_text += f"• <b>{clean_title}</b>\n"
            buttons.append([InlineKeyboardButton(f"🚀 ᴀᴄᴄᴇss {clean_title}", url=delivery_link)])

        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ ʙᴀᴄᴋ", style=enums.ButtonStyle.PRIMARY, callback_data=f"accpage_{page - 1}"))
        if end_idx < total_purchases:
            nav_buttons.append(InlineKeyboardButton("ɴᴇxᴛ ▶️", style=enums.ButtonStyle.PRIMARY, callback_data=f"accpage_{page + 1}"))

        if nav_buttons:
            buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="close_message", style=enums.ButtonStyle.DANGER)])
    reply_markup = InlineKeyboardMarkup(buttons)

    if is_callback:
        try:
            await message_or_cb.message.edit_text(acc_text, reply_markup=reply_markup)
        except MessageNotModified:
            pass
        except Exception:
            await message_or_cb.message.reply_text(acc_text, reply_markup=reply_markup)
    else:
        await message_or_cb.reply_text(acc_text, reply_markup=reply_markup)

# ------------------ Account Pagination Callback Handler ------------------
@Client.on_callback_query(filters.regex(r"^accpage_"))
async def account_pagination_cb(client, callback_query):
    user = callback_query.from_user
    try:
        page = int(callback_query.data.split("_")[1])
        await send_or_edit_account_details(client, user, callback_query, page=page, is_callback=True)
    except Exception as e:
        print(f"Error in account_pagination_cb: {e}")
    await callback_query.answer()

# ------------------ Callback Handlers for Start Inline Buttons ------------------

@Client.on_callback_query(filters.regex("^open_wallet_cb$"))
async def cb_wallet_handler(client, callback_query):
    user_id = callback_query.from_user.id
    balance = await get_user_wallet(user_id)
    
    text = (
        f"<b>👛 ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ ᴅᴇᴛᴀɪʟs</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"<b>💳 ᴄᴜʀʀᴇɴᴛ ʙᴀʟᴀɴᴄᴇ:</b> ₹{balance}\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 <i>Use wallet balance for 1-click instant purchases.</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ᴀᴅᴅ ᴍᴏɴᴇʏ / ᴛᴏᴘ-ᴜᴘ", callback_data="add_wallet_funds", style=enums.ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="close_message", style=enums.ButtonStyle.DANGER)]
    ])
    await callback_query.message.reply_text(text, reply_markup=kb)
    await callback_query.answer()

@Client.on_callback_query(filters.regex("^open_account_cb$"))
async def cb_account_handler(client, callback_query):
    user = callback_query.from_user
    await send_or_edit_account_details(client, user, callback_query, page=0, is_callback=True)
    await callback_query.answer()

@Client.on_callback_query(filters.regex("^open_refer_cb$"))
async def cb_refer_handler(client, callback_query):
    user_id = callback_query.from_user.id
    refer_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    wallet = await get_user_wallet(user_id)
    total_refs = await get_referred_users_count(user_id)
    
    text = (
        f"🎁 <b><u>ʀᴇғᴇʀ & ᴇᴀʀɴ ᴘʀᴏɢʀᴀᴍ</u></b>\n\n"
        f"Share the bot with your friends and earn <b>₹1.00</b> directly into your wallet for every new user!\n\n"
        f"📊 <b>Your Details:</b>\n"
        f"👥 <b>Total Referred:</b> {total_refs} Users\n"
        f"👛 <b>Wallet Balance:</b> ₹{wallet}\n\n"
        f"🔗 <b>Your Personal Referral Link:</b>\n"
        f"<code>{refer_link}</code>"
    )
    
    share_text = url_quote("✨ Listen to your favorite audio stories and podcasts easily! Join now:")
    share_url = f"https://t.me/share/url?url={url_quote(refer_link)}&text={share_text}"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 sʜᴀʀᴇ ᴡɪᴛʜ ғʀɪᴇɴᴅs", style=enums.ButtonStyle.PRIMARY, url=share_url)],
        [InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="close_message", style=enums.ButtonStyle.DANGER)]
    ])
    await callback_query.message.reply_text(text, reply_markup=kb, disable_web_page_preview=True)
    await callback_query.answer()

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
        [InlineKeyboardButton("➕ ᴀᴅᴅ ᴍᴏɴᴇʏ / ᴛᴏᴘ-ᴜᴘ", callback_data="add_wallet_funds", style=enums.ButtonStyle.PRIMARY)]
    ])
    
    await message.reply_text(text, reply_markup=kb)

@Client.on_callback_query(filters.regex("^add_wallet_funds$"))
async def add_funds_callback(client, callback_query):
    text = (
        "<b>➕ ᴀᴅᴅ ᴍᴏɴᴇʏ ᴛᴏ ᴡᴀʟʟᴇᴛ</b>\n\n"
        "Contact admin or send payment screenshot to top-up your wallet balance automatically."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ ғᴏʀ ᴛᴏᴘᴜᴘ", url="https://t.me/kaluu_help_bot", style=enums.ButtonStyle.PRIMARY)]
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
        f"Share the bot with your friends and earn <b>₹1.00</b> directly into your wallet for every new user!\n\n"
        f"📊 <b>Your Details:</b>\n"
        f"👥 <b>Total Referred:</b> {total_refs} Users\n"
        f"👛 <b>Wallet Balance:</b> ₹{wallet}\n\n"
        f"🔗 <b>Your Personal Referral Link:</b>\n"
        f"<code>{refer_link}</code>"
    )
    
    share_text = url_quote("✨ Listen to your favorite audio stories and podcasts easily! Join now:")
    share_url = f"https://t.me/share/url?url={url_quote(refer_link)}&text={share_text}"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 sʜᴀʀᴇ ᴡɪᴛʜ ғʀɪᴇɴᴅs", style=enums.ButtonStyle.PRIMARY, url=share_url)],
        [InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="close_message", style=enums.ButtonStyle.DANGER)]
    ])
    
    await message.reply_text(text, reply_markup=kb, disable_web_page_preview=True)

# ------------------ Dynamic Button Handlers ------------------

@Client.on_message(filters.regex("^(🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ|🚀 Open Mini App)$") & filters.private)
async def open_miniapp_handler(client, message):
    text = (
        "🚀 <b>ᴍɪɴɪ sᴛᴏʀᴇ ᴀᴘᴘ</b>\n\n"
        "ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴏᴘᴇɴ ᴏᴜʀ ᴏғғɪᴄɪᴀʟ ᴍɪɴɪ ᴀᴘᴘ ᴀɴᴅ ᴇxᴘʟᴏʀᴇ ᴀʟʟ sᴛᴏʀɪᴇs!"
    )
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 ʟᴀᴜɴᴄʜ ᴍɪɴɪ ᴀᴘᴘ", style=enums.ButtonStyle.PRIMARY, web_app=WebAppInfo(url=WEB_APP_URL))],
        [InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="close_message", style=enums.ButtonStyle.DANGER)]
    ])
    await message.reply_text(text, reply_markup=btn)

@Client.on_message(filters.regex("^(📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ|📢 Updates Channel)$") & filters.private)
async def updates_handler(client, message):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ", url="https://t.me/freestoryhubMR", style=enums.ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="close_message", style=enums.ButtonStyle.DANGER)]
    ])
    await message.reply_text("<b>📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ:</b>\n\nᴊᴏɪɴ ᴏᴜʀ ᴄʜᴀɴɴᴇʟ ғᴏʀ ᴛʜᴇ ʟᴀᴛᴇsᴛ ᴜᴘᴅᴀᴛᴇs ᴀɴᴅ ɴᴇᴡ sᴛᴏʀɪᴇs!", reply_markup=kb)

@Client.on_message(filters.regex("^(👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ|👤 My Account)$") & filters.private)
async def account_handler(client, message):
    user = message.from_user
    await send_or_edit_account_details(client, user, message, page=0, is_callback=False)

@Client.on_message(filters.regex("^(📞 sᴜᴘᴘᴏʀᴛ|📞 Support)$") & filters.private)
async def support_handler(client, message):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ", url="https://t.me/pratilipifm0900", style=enums.ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="close_message", style=enums.ButtonStyle.DANGER)]
    ])
    await message.reply_text("<b>📞 ᴄᴜsᴛᴏᴍᴇʀ sᴜᴘᴘᴏʀᴛ:</b>\n\nɪғ ʏᴏᴜ ғᴀᴄᴇ ᴀɴʏ ɪssᴜᴇs, ғᴇᴇʟ ғʀᴇᴇ ᴛᴏ ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ.", reply_markup=kb)
