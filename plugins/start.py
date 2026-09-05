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
    users_col,
    stories_col
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
USER_PAGE_STATE = {}

# 1. Main Welcome Message Inline Keyboard
def get_welcome_inline_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🛒 OPEN MARKET", callback_data="open_market_keyboard")
            ],
            [
                InlineKeyboardButton("🚀 OPEN MINI APP", web_app=WebAppInfo(url=WEB_APP_URL))
            ],
            [
                InlineKeyboardButton("💼 MY WALLET", callback_data="menu_wallet"),
                InlineKeyboardButton("👤 MY ACCOUNT", callback_data="menu_account")
            ],
            [
                InlineKeyboardButton("🎁 REFER & EARN", callback_data="menu_refer"),
                InlineKeyboardButton("📢 UPDATES", url="https://t.me/freestoryhubMR")
            ],
            [
                InlineKeyboardButton("📞 SUPPORT", url="https://t.me/pratilipifm0900"),
                InlineKeyboardButton("❌ CLOSE", callback_data="close_message")
            ]
        ]
    )

# 2. Market Reply Keyboard
def get_market_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("📚 PRATILIPI FM"), KeyboardButton("📻 POCKET FM")],
            [KeyboardButton("🔎 SEARCH STORY")],
            [KeyboardButton("🔙 BACK TO MAIN MENU")]
        ],
        resize_keyboard=True
    )

# 3. Category Pagination Keyboard Generator
async def get_category_reply_keyboard(category_name: str, page=1, per_page=10):
    regex_pattern = re.compile(f"^{category_name}$", re.IGNORECASE)
    all_stories = await stories_col.find({"category": regex_pattern}).to_list(length=1000)

    if not all_stories:
        return None, 0, 0

    total_stories = len(all_stories)
    total_pages = (total_stories + per_page - 1) // per_page
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_stories = all_stories[start_idx:end_idx]

    buttons = []
    
    # Story Buttons
    for story in page_stories:
        title = story.get("title", "Untitled Story").strip().split("\n")[0]
        buttons.append([KeyboardButton(f"📖 {title}")])

    # Navigation Row inside Reply Keyboard
    nav_row = []
    prefix = "POCKET" if "pocket" in category_name.lower() else "PRATILIPI"
    
    if page > 1:
        nav_row.append(KeyboardButton(f"⬅️ {prefix} PREV"))
    
    nav_row.append(KeyboardButton(f"📄 PAGE {page}/{total_pages}"))
    
    if page < total_pages:
        nav_row.append(KeyboardButton(f"NEXT {prefix} ➡️"))

    buttons.append(nav_row)
    buttons.append([KeyboardButton("🔙 BACK TO MAIN MENU")])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True), total_stories, total_pages


# Custom Filter for WebApp Data
async def web_app_filter(_, __, message):
    return bool(message.web_app_data)

filter_webapp = filters.create(web_app_filter)

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

# ------------------ Helper: Advanced Smart File Delivery Function ------------------
async def send_story_files_start(client, user_id, story, first_id, last_id, clean_title, custom_range_text="", target_start_ep=None, target_end_ep=None):
    sent_messages_obj = []
    sent_message_ids = []
    success_count = 0

    chosen_sticker = SEARCH_RANGE_STICKER_ID if target_start_ep is not None else DELIVERY_STICKER_ID

    status_msg = await client.send_sticker(
        chat_id=user_id,
        sticker=chosen_sticker
    )

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
        try:
            await status_msg.delete()
        except Exception:
            pass

        return await client.send_message(
            chat_id=user_id,
            text=f"❌ <b>ɴᴏ ᴍᴀᴛᴄʜɪɴɢ ᴇᴘɪsᴏᴅᴇs ғᴏᴜɴᴅ!</b>\n\n"
                 f"रेंज <b>{custom_range_text}</b> के एपिसोड्स उपलब्ध नहीं हैं।"
        )

    for msg in messages_to_send:
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
            await asyncio.sleep(1.1)
        except Exception as e:
            print(f"Error copying message {msg.id}: {e}")

    try:
        await status_msg.delete()
    except Exception:
        pass

    ep_range = get_exact_episode_range(sent_messages_obj) if sent_messages_obj else f"Files Range"

    if sent_message_ids:
        first_sent_id = sent_message_ids[0]
        last_sent_id = sent_message_ids[-1]
        
        clean_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧹 ᴄʟᴇᴀɴ / ᴅᴇʟᴇᴛᴇ ᴀʟʟ ғɪʟᴇs", callback_data=f"rangechatclean_{first_sent_id}_{last_sent_id}")]
        ])
    else:
        clean_kb = None

    await client.send_message(
        chat_id=user_id,
        text=f"🎉 <b>ғɪʟᴇs ᴅᴇʟɪᴠᴇʀᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
             f"📖 <b>sᴛᴏʀʏ:</b> {clean_title}\n"
             f"🎧 <b>ʀᴀɴɢᴇ:</b> {ep_range} {custom_range_text}\n"
             f"📦 <b>ᴅᴇʟɪᴠᴇʀᴇᴅ:</b> {success_count} / {total_files} Files\n\n"
             f"👇 <i>सुनने के बाद चैट साफ़ करने के लिए नीचे बटन पर क्लिक करें:</i>",
        reply_markup=clean_kb
    )

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

# ------------------ Direct Buy Callback Handler ------------------
@Client.on_callback_query(filters.regex(r"^buy_"))
async def direct_buy_callback_handler(client, callback_query: CallbackQuery):
    try:
        data_parts = callback_query.data.split("_")
        price = float(data_parts[-1])
        story_title = " ".join(data_parts[1:-1])

        story = await get_story_by_title(story_title)
        if not story:
            return await callback_query.answer("❌ Story not found!", show_alert=True)

        await callback_query.answer("💳 Redirecting to payment options...", show_alert=False)
        clean_title = story['title'].strip().split("\n")[0]
        
        pay_info_text = (
            f"💳 <b><u>DIRECT PAYMENT INITIATED</u></b>\n\n"
            f"📖 <b>Story:</b> {clean_title}\n"
            f"💰 <b>Amount Due:</b> ₹{price}\n\n"
            f"<i>To pay directly via QR / UPI or manual transfer, please contact support or add funds to your wallet using the My Wallet option!</i>"
        )
        await callback_query.message.reply_text(pay_info_text, quote=True)
    except Exception as e:
        print(f"Error handling direct buy: {e}")
        await callback_query.answer("❌ Failed to process purchase request!", show_alert=True)

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

# ------------------ Start Batch Callback Router ------------------
@Client.on_callback_query(filters.regex(r"^(sendall_|sendcustom_|askrange_)"))
async def start_batch_callback_router(client, callback_query):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    if data.startswith("sendall_"):
        encoded_title = data.split("sendall_")[1]
        story_title = encoded_title.replace("_", " ")
        story = await get_story_by_title(story_title)
        if not story:
            return await callback_query.answer("❌ Story not found!", show_alert=True)
            
        await callback_query.message.delete()
        clean_title = story['title'].strip().split("\n")[0]
        await send_story_files_start(client, user_id, story, story['first_msg_id'], story['last_msg_id'], clean_title)
        await callback_query.answer()

    elif data.startswith("sendcustom_"):
        parts = data.split(":")
        encoded_title = parts[0].replace("sendcustom_", "")
        range_idx = int(parts[1])

        story_title = encoded_title.replace("_", " ")
        story = await get_story_by_title(story_title)
        if not story:
            return await callback_query.answer("❌ Story not found!", show_alert=True)

        custom_ranges = story.get('custom_ranges', [])
        if range_idx >= len(custom_ranges):
            return await callback_query.answer("❌ Invalid Range Selected!", show_alert=True)

        selected_range = custom_ranges[range_idx]
        range_name = selected_range['name']
        f_id = selected_range['first_id']
        l_id = selected_range['last_id']

        await callback_query.message.delete()
        clean_title = story['title'].strip().split("\n")[0]
        await send_story_files_start(client, user_id, story, f_id, l_id, clean_title, custom_range_text=f"({range_name})")
        await callback_query.answer()
        
    elif data.startswith("askrange_"):
        encoded_title = data.split("askrange_")[1]
        story_title = encoded_title.replace("_", " ")
        story = await get_story_by_title(story_title)
        if not story:
            return await callback_query.answer("❌ Story not found!", show_alert=True)
        
        START_RANGE_WAITING[user_id] = {
            "story": story,
            "encoded_title": encoded_title
        }
        
        total_episodes = (story['last_msg_id'] - story['first_msg_id']) + 1
        
        await callback_query.message.reply_text(
            f"🔢 <b>Enter Episode Range (1 - {total_episodes}):</b>\n\n"
            f"कृपया रेंज दर्ज करें कि आपको कहाँ से कहाँ तक एपिसोड चाहिए।\n"
            f"<i>(उदाहरण के लिए लिखें: <code>1-5</code> या <code>110-120</code>)</i>",
            reply_markup=ForceReply(selective=True)
        )
        await callback_query.answer()

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

    # Deep-Link Logic (Files Delivery & Story Viewing)
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

        if custom_ranges:
            buttons = []
            for idx, r in enumerate(custom_ranges):
                buttons.append([InlineKeyboardButton(f"📁 {r['name']}", callback_data=f"sendcustom_{encoded_title}:{idx}")])
            
            buttons.append([InlineKeyboardButton(f"📦 All Episodes ({total_files} Files)", callback_data=f"sendall_{encoded_title}")])

            choice_kb = InlineKeyboardMarkup(buttons)
            return await message.reply_text(
                f"📚 <b>{clean_title}</b>\n\n"
                f"⚠️ इस स्टोरी में कुल <b>{total_files}</b> फाइल्स उपलब्ध हैं।\n"
                f"कृपया अपना पसंदीदा भाग चुनें या इच्छित रेंज टाइप करें:",
                reply_markup=choice_kb,
                quote=True
            )

        if total_files > 100:
            choice_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📦 All Episodes ({total_files} Files)", callback_data=f"sendall_{encoded_title}")]
            ])
            return await message.reply_text(
                f"📚 <b>{clean_title}</b>\n\n"
                f"⚠️ इस स्टोरी में कुल <b>{total_files}</b> फाइल्स उपलब्ध हैं।\n"
                f"आप सभी एपिसोड्स एक साथ पाना चाहते हैं या कुछ खास रेंज?",
                reply_markup=choice_kb,
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
            return await message.reply_text("❌ <b>ᴛʜɪs sᴛᴏʀʏ ɪs ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ.</b>", reply_markup=get_welcome_inline_keyboard(), quote=True)

    # Normal /start Welcome Message
    welcome_text = (
        f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"🌟 <b>STORY SELLER BOT</b> 🌟\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"<b>HELLO {user.first_name}! 👋</b>\n\n"
        f"नीचे दिए गए बटन्स का उपयोग करके मेनू नेविगेट करें। मार्किट ओपन करने के लिए <b>🛒 OPEN MARKET</b> पर क्लिक करें।"
    )
    await message.reply_text(welcome_text, reply_markup=get_welcome_inline_keyboard(), quote=True)


# ------------------ Inline Menu Callbacks Handler ------------------
@Client.on_callback_query(filters.regex(r"^(open_market_keyboard|menu_wallet|menu_account|menu_refer)$"))
async def inline_callback_handler(client, callback_query: CallbackQuery):
    data = callback_query.data
    user_id = callback_query.from_user.id
    user = callback_query.from_user
    msg = callback_query.message

    if data == "open_market_keyboard":
        await callback_query.answer("🛒 Market Keyboard Opened!")
        await client.send_message(
            chat_id=user_id,
            text="👇 <b>Marketplace Open:</b> नीचे दिए गए कीबोर्ड बटन्स से अपनी पसंद का प्लेटफॉर्म या स्टोरी चुनें:",
            reply_markup=get_market_reply_keyboard()
        )

    # ------------ 1. SEPARATE WALLET MENU ------------
    elif data == "menu_wallet":
        await callback_query.answer()
        balance = await get_user_wallet(user_id)
        total_refs = await get_referred_users_count(user_id)

        wallet_text = (
            f"💼 <b><u>YOUR WALLET DASHBOARD</u></b>\n\n"
            f"👤 <b>User:</b> {user.first_name}\n"
            f"🆔 <b>User ID:</b> <code>{user.id}</code>\n\n"
            f"💰 <b>Current Balance:</b> ₹{balance:.2f}\n"
            f"👥 <b>Total Referral Earnings:</b> ₹{total_refs * REFER_BONUS:.2f}\n\n"
            f"💡 <b>वॉलेट बैलेंस कैसे बढ़ाएं?</b>\n"
            f"1️⃣ <b>Refer & Earn:</b> अपने रेफरल लिंक से दोस्तों को जोड़ें और प्रति यूज़र ₹1 पाएँ।\n"
            f"2️⃣ <b>Top-Up / Add Money:</b> एडमिन से संपर्क करके क्यूआर या यूपीआई से बैलेंस ऐड करवाएं।"
        )
        
        wallet_buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ ADD FUNDS / TOP-UP", url="https://t.me/pratilipifm0900")],
            [InlineKeyboardButton("🎁 REFER & EARN", callback_data="menu_refer")],
            [InlineKeyboardButton("❌ CLOSE", callback_data="close_message")]
        ])
        
        await msg.reply_text(wallet_text, reply_markup=wallet_buttons, quote=True)

    # ------------ 2. SEPARATE ACCOUNT MENU ------------
    elif data == "menu_account":
        await callback_query.answer()
        balance = await get_user_wallet(user_id)
        purchases = await get_user_purchases(user_id)
        total_refs = await get_referred_users_count(user_id)

        acc_text = (
            f"<b>👤 ʏᴏᴜʀ ᴀᴄᴄᴏᴜɴᴛ & ᴘᴜʀᴄʜᴀsᴇs:</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<b>👤 ɴᴀᴍᴇ:</b> {user.first_name}\n"
            f"<b>🆔 ᴜsᴇʀ ɪᴅ:</b> <code>{user.id}</code>\n"
            f"<b>👛 ᴡᴀʟʟᴇᴛ ʙᴀʟᴀɴᴄᴇ:</b> ₹{balance:.2f}\n"
            f"<b>👥 Total Referrals:</b> {total_refs} Users\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>📚 ʏᴏᴜʀ ᴘᴜʀᴄʜᴀsᴇᴅ sᴛᴏʀɪᴇs:</b>\n"
        )
        buttons = []
        if not purchases:
            acc_text += "❌ <i>आपने अभी तक कोई स्टोरी परचेस नहीं की है।</i>"
        else:
            for item in purchases:
                story = await get_story_by_title(item['story_title'])
                if story:
                    clean_title = story['title'].strip().split("\n")[0]
                    encoded_title = clean_title.replace(" ", "_")
                    delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"
                    acc_text += f"• <b>{clean_title}</b>\n"
                    buttons.append([InlineKeyboardButton(f"🚀 ᴀᴄᴄᴇss {clean_title}", url=delivery_link)])

        buttons.append([InlineKeyboardButton("❌ Close", callback_data="close_message")])
        await msg.reply_text(acc_text, reply_markup=InlineKeyboardMarkup(buttons), quote=True)

    elif data == "menu_refer":
        await callback_query.answer()
        refer_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
        wallet = await get_user_wallet(user_id)
        total_refs = await get_referred_users_count(user_id)
        
        ref_text = (
            f"🎁 <b><u>ʀᴇғᴇʀ & ᴇᴀʀɴ ᴘʀᴏɢʀᴀᴍ</u></b>\n\n"
            f"अपने दोस्तों को बॉट शेयर करें और हर नए यूज़र पर पाएँ <b>₹1.00</b>!\n\n"
            f"👥 <b>Total Referred:</b> {total_refs} Users\n"
            f"👛 <b>Wallet Balance:</b> ₹{wallet:.2f}\n\n"
            f"🔗 <b>आपका लिंक:</b>\n<code>{refer_link}</code>"
        )
        await msg.reply_text(ref_text, quote=True)


# ------------------ Reply Keyboard Text Handler ------------------
@Client.on_message(filters.private & filters.text & ~filters.command(["start"]))
async def reply_keyboard_router(client, message):
    text = message.text.strip()
    user_id = message.from_user.id

    # 1. Pocket FM Handler
    if text in ["📻 POCKET FM", "NEXT POCKET ➡️", "⬅️ POCKET PREV"]:
        current_page = USER_PAGE_STATE.get(user_id, {}).get("pocket_page", 1)
        if text == "NEXT POCKET ➡️":
            current_page += 1
        elif text == "⬅️ POCKET PREV":
            current_page = max(1, current_page - 1)
        else:
            current_page = 1

        USER_PAGE_STATE[user_id] = {"pocket_page": current_page}
        kb, total, total_pages = await get_category_reply_keyboard("Pocket FM", page=current_page)
        
        if not kb:
            return await message.reply_text("❌ Pocket FM की कोई स्टोरी उपलब्ध नहीं है!")
        
        await message.reply_text(
            f"📻 <b>Pocket FM Stories</b> (Page {current_page}/{total_pages})\nTotal: {total} Stories\n\n👇 अपनी पसंद की स्टोरी चुनें:",
            reply_markup=kb
        )

    # 2. Pratilipi FM Handler
    elif text in ["📚 PRATILIPI FM", "NEXT PRATILIPI ➡️", "⬅️ PRATILIPI PREV"]:
        current_page = USER_PAGE_STATE.get(user_id, {}).get("pratilipi_page", 1)
        if text == "NEXT PRATILIPI ➡️":
            current_page += 1
        elif text == "⬅️ PRATILIPI PREV":
            current_page = max(1, current_page - 1)
        else:
            current_page = 1

        USER_PAGE_STATE[user_id] = {"pratilipi_page": current_page}
        kb, total, total_pages = await get_category_reply_keyboard("Pratilipi FM", page=current_page)
        
        if not kb:
            return await message.reply_text("❌ Pratilipi FM की कोई स्टोरी उपलब्ध नहीं है!")
        
        await message.reply_text(
            f"📚 <b>Pratilipi FM Stories</b> (Page {current_page}/{total_pages})\nTotal: {total} Stories\n\n👇 अपनी पसंद की स्टोरी चुनें:",
            reply_markup=kb
        )

    # 3. Search Story Handler
    elif text == "🔎 SEARCH STORY":
        await message.reply_text("🔎 **स्टोरी सर्च करने के लिए:**\n\nकृपया जिस स्टोरी को खोजना चाहते हैं उसका नाम लिखकर भेजें!")

    # 4. Back to Main Menu (With Reply Keyboard Removal)
    elif text == "🔙 BACK TO MAIN MENU":
        welcome_text = (
            f"🏠 **मुख्य मेनू:**\n\n"
            f"मार्किट फिर से खोलने के लिए **🛒 OPEN MARKET** इनलाइन बटन दबाएं।"
        )
        
        # चरण 1: Reply Keyboard को हटाएँ
        remove_msg = await message.reply_text("🔄...", reply_markup=ReplyKeyboardRemove())
        
        # चरण 2: मुख्य Inline Menu भेजें
        await message.reply_text(welcome_text, reply_markup=get_welcome_inline_keyboard())
        
        # चरण 3: अस्थायी मैसेंजर डिलीट करें
        try:
            await remove_msg.delete()
        except Exception:
            pass

    # 5. Direct Story Click (📖 Story Title)
    elif text.startswith("📖 "):
        story_title = text.replace("📖 ", "").strip()
        story = await get_story_by_title(story_title)

        if not story:
            return await message.reply_text("❌ <b>स्टोरी की जानकारी नहीं मिली!</b>", quote=True)

        clean_title = story['title'].strip().split("\n")[0]
        encoded_title = clean_title.replace(" ", "_")
        wallet_bal = await get_user_wallet(user_id)
        photo_url = story.get('photo', 'https://picsum.photos/400/200')

        buttons = []
        if story.get('demo_enabled', False):
            buttons.append([InlineKeyboardButton("🎬 ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ", callback_data=f"viewdemo_{encoded_title}")])

        buttons.append([InlineKeyboardButton(f"🛒 ʙᴜʏ ɴᴏᴡ (₹{story.get('price', 0)})", callback_data=f"buy_{encoded_title}_{story.get('price', 0)}")])
        buttons.append([InlineKeyboardButton(f"👛 ᴘᴀʏ ᴠɪᴀ ᴡᴀʟʟᴇᴛ (Bal: ₹{wallet_bal})", callback_data=f"walletpay_{encoded_title}_{story.get('price', 0)}")])

        caption_text = (
            f"♨️ <b>Story :</b> {clean_title}\n"
            f"🔰 <b>Status :</b> {story.get('status', 'Completed')}\n"
            f"🖥️ <b>Platform :</b> {story.get('category', 'Pocket FM')}\n"
            f"🧩 <b>Genre :</b> {story.get('genre', 'Drama')}\n"
            f"🎬 <b>Episodes :</b> {story.get('episodes', 'N/A')}\n\n"
            f"░▒▓█ PRICE - ₹{story.get('price', 0)} █▓▒░\n\n"
            f"👛 <b>ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ:</b> ₹{wallet_bal}\n\n"
            f"<i>👇 खरीद या देखने के लिए नीचे बटन चुनें:</i>"
        )

        try:
            await message.reply_photo(photo=photo_url, caption=caption_text, reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            await message.reply_text(caption_text, reply_markup=InlineKeyboardMarkup(buttons))
