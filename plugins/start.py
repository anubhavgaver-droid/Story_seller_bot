import json
import asyncio
import time
import re
from pyrogram import Client, filters, enums
from pyrogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    ForceReply,
    WebAppInfo,
    CallbackQuery
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
    get_exact_episode_range
)
from config import BOT_USERNAME, WEB_APP_URL, CHANNEL_ID

# Storage Dictionaries for Clean Chat & Range Input
CLEAN_CHAT_STORAGE = {}
START_RANGE_WAITING = {}

# 1. Main Menu Keyboard Layout (Wallet Button Included)
MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ")],
        [KeyboardButton("💼 ᴍʏ ᴡᴀʟʟᴇᴛ", style=enums.ButtonStyle.SUCCESS), KeyboardButton("👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ", style=enums.ButtonStyle.PRIMARY)],
        [KeyboardButton("🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ", style=enums.ButtonStyle.SUCCESS), KeyboardButton("📻 ᴘᴏᴄᴋᴇᴛ ғᴍ", style=enums.ButtonStyle.DANGER)],
        [KeyboardButton("📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ", style=enums.ButtonStyle.DANGER), KeyboardButton("📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ", style=enums.ButtonStyle.PRIMARY)],
        [KeyboardButton("📞 sᴜᴘᴘᴏʀᴛ", style=enums.ButtonStyle.SUCCESS)]
    ],
    resize_keyboard=True
)

# Custom Filter for WebApp Data
async def web_app_filter(_, __, message):
    return bool(message.web_app_data)

filter_webapp = filters.create(web_app_filter)

# ------------------ Helper: Extract Episode Number from Text/Title ------------------
def extract_episode_number(text: str) -> int:
    """
    Extracts episode integer from text, caption, title, or filename using regex patterns.
    Matches formats like: Episode 1, Ep 01, Ep-1, Episode - 10, #1, 01, etc.
    """
    if not text:
        return None
    
    patterns = [
        r'(?:episode|ep|episodes)\s*[-:]?\s*(\d+)',  # Episode 1, Ep-01, Ep 1
        r'#\s*(\d+)',                                 # #1, #01
        r'(?:part|pt)\s*[-:]?\s*(\d+)',              # Part 1, Pt 01
        r'\bep\s*(\d+)\b',                            # ep1
        r'\b(\d+)\b'                                  # Standalone number fallback
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None

# ------------------ Helper: Extract Title/Metadata from Message ------------------
def get_message_searchable_text(msg) -> str:
    """
    Extracts all possible searchable text from caption, document name, audio title, or video title.
    """
    if not msg:
        return ""
    
    combined_texts = []
    
    # 1. Caption / Message Text
    if msg.caption:
        combined_texts.append(msg.caption)
    if msg.text:
        combined_texts.append(msg.text)
        
    # 2. Audio Title / Performer / File Name
    if msg.audio:
        if msg.audio.title:
            combined_texts.append(msg.audio.title)
        if msg.audio.file_name:
            combined_texts.append(msg.audio.file_name)
        if msg.audio.performer:
            combined_texts.append(msg.audio.performer)

    # 3. Document File Name
    if msg.document and msg.document.file_name:
        combined_texts.append(msg.document.file_name)

    # 4. Video File Name
    if msg.video and msg.video.file_name:
        combined_texts.append(msg.video.file_name)

    # 5. Voice / Audio Caption Fallback
    if msg.voice and msg.caption:
        combined_texts.append(msg.caption)

    return " | ".join(combined_texts)

# ------------------ Helper: Advanced Smart File Delivery Function ------------------
async def send_story_files_start(client, user_id, story, first_id, last_id, clean_title, custom_range_text="", target_start_ep=None, target_end_ep=None):
    sent_messages_obj = []
    sent_message_ids = []
    success_count = 0

    # 1. केवल SINGLE 🔍 EMOJI MESSAGE
    status_msg = await client.send_message(
        chat_id=user_id,
        text="🔍"
    )

    msg_ids_to_fetch = list(range(first_id, last_id + 1))
    
    # Process in chunks of 20 to avoid memory issues
    chunk_size = 20
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
                
                # Fetch text from Caption + Audio Title + Document/File Name
                searchable_text = get_message_searchable_text(msg)
                ep_num = extract_episode_number(searchable_text)

                # Filter based on Target Episode Range if provided
                if target_start_ep is not None and target_end_ep is not None:
                    if ep_num is not None and target_start_ep <= ep_num <= target_end_ep:
                        matching_messages.append((ep_num, msg))
                else:
                    matching_messages.append((ep_num or 0, msg))
        except Exception as e:
            print(f"Error fetching channel messages batch: {e}")

    # Sort matched messages by actual episode number
    if target_start_ep is not None and target_end_ep is not None:
        matching_messages.sort(key=lambda x: x[0])
        messages_to_send = [item[1] for item in matching_messages]
    else:
        messages_to_send = [item[1] for item in matching_messages]

    total_files = len(messages_to_send)

    if total_files == 0:
        await status_msg.edit_text(
            f"❌ <b>ɴᴏ ᴍᴀᴛᴄʜɪɴɢ ᴇᴘɪsᴏᴅᴇs ғᴏᴜɴᴅ!</b>\n\n"
            f"रेंज <b>{custom_range_text}</b> के एपिसोड्स उपलब्ध नहीं हैं।"
        )
        return

    # Deliver matched files to user
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
            await asyncio.sleep(0.4)  # Avoid FloodWait
        except Exception as e:
            print(f"Error copying message {msg.id}: {e}")

    # 2. 🔍 इमोजी वाले मैसेज को डिलीट करें
    try:
        await status_msg.delete()
    except Exception:
        pass

    # Extract exact Episode Range text from delivered files
    ep_range = get_exact_episode_range(sent_messages_obj) if sent_messages_obj else f"Files Range"

    delivery_key = f"{user_id}_{int(time.time())}"
    CLEAN_CHAT_STORAGE[delivery_key] = sent_message_ids

    clean_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧹 ᴄʟᴇᴀɴ / ᴅᴇʟᴇᴛᴇ ᴀʟʟ ғɪʟᴇs", callback_data=f"cleanchat_{delivery_key}")]
    ])

    await client.send_message(
        chat_id=user_id,
        text=f"🎉 <b>ғɪʟᴇs ᴅᴇʟɪᴠᴇʀᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
             f"📖 <b>sᴛᴏʀʏ:</b> {clean_title}\n"
             f"🎧 <b>ʀᴀɴɢᴇ:</b> {ep_range} {custom_range_text}\n"
             f"📦 <b>ᴅᴇʟɪᴠᴇʀᴇᴅ:</b> {success_count} / {total_files} Files\n\n"
             f"👇 <i>सुनने के बाद चैट साफ़ करने के लिए नीचे बटन पर क्लिक करें:</i>",
        reply_markup=clean_kb
    )

# ------------------ Mini App Web Data Receiver ------------------
@Client.on_message(filters.service & filter_webapp & filters.private)
async def web_app_data_handler(client, message):
    try:
        data = json.loads(message.web_app_data.data)
        action = data.get("action")
        story_title = data.get("title")
        price = float(data.get("price", 0))
        
        if action == "buy_story":
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
            desc = story.get('desc', 'ɴᴏ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴀᴠᴀɪʟᴀʙʟᴇ.')

            caption_text = (
                f"🛒 <b>ᴏʀᴅᴇʀ ɪɴɪᴛɪᴀᴛᴇᴅ ғʀᴏᴍ ᴍɪɴɪ ᴀᴘᴘ</b>\n\n"
                f"📖 <b>ᴛɪᴛʟᴇ:</b> {clean_title}\n"
                f"💰 <b>ᴘʀɪᴄᴇ:</b> ₹{price}\n"
                f"👛 <b>ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ:</b> ₹{wallet_bal}\n"
                f"📝 <b>ᴅᴇsᴄ:</b> {desc}\n\n"
                f"👇 <b>Select payment method to complete purchase:</b>"
            )
            
            try:
                await message.reply_photo(photo=photo_url, caption=caption_text, reply_markup=btn, quote=True)
            except Exception:
                await message.reply_text(caption_text, reply_markup=btn, quote=True)
    except Exception as e:
        print(f"WebApp Data Error: {e}")

# ------------------ View Demo Callback Handler (10 Min Auto Delete) ------------------
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

# ------------------ Start Batch Callback Router ------------------
@Client.on_callback_query(filters.regex(r"^(sendall_|sendcustom_|askrange_|cleanchat_)"))
async def start_batch_callback_router(client, callback_query):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    # 1. Send All Episodes Option
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

    # 2. Dynamic Custom Range Selection
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
        
    # 3. Ask Custom Range Option (Manual Input)
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

    # 4. One-Click Clean / Delete Chat
    elif data.startswith("cleanchat_"):
        key = data.split("cleanchat_")[1]
        msg_ids = CLEAN_CHAT_STORAGE.get(key, [])

        if not msg_ids:
            return await callback_query.answer("⚠️ चैट पहले ही साफ़ की जा चुकी है!", show_alert=True)

        await callback_query.answer("🧹 Cleaning files... Please wait!")

        for m_id in msg_ids:
            try:
                await client.delete_messages(chat_id=user_id, message_ids=m_id)
                await asyncio.sleep(0.1)
            except Exception:
                pass

        try:
            await callback_query.message.edit_text("✅ <b>चैट सफलतापूर्वक साफ़ कर दी गई है!</b> 🗑️")
        except Exception:
            pass

        CLEAN_CHAT_STORAGE.pop(key, None)

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
    
    # Directly sends files with Single 🔍 Emoji search status
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
    
    # 1. Registration Logic
    try:
        registered = await is_user_registered(user.id)
        if not registered:
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

    args = message.text.split(maxsplit=1)
    
    # 2. BATCH DELIVERY MECHANISM (get_ENCODED_TITLE)
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

        # Purchase Verification
        unlocked = await is_story_unlocked(user.id, clean_title)
        if not unlocked:
            buy_btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 ʙᴜʏ ɴᴏᴡ", callback_data=f"buy_{encoded_title}_{story['price']}")]
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

        # Interactive Dynamic Range Buttons Option if Admin Created Custom Buttons
        if custom_ranges:
            buttons = []
            for idx, r in enumerate(custom_ranges):
                buttons.append([InlineKeyboardButton(f"📁 {r['name']}", callback_data=f"sendcustom_{encoded_title}:{idx}")])
            
            buttons.append([InlineKeyboardButton(f"📦 All Episodes ({total_files} Files)", callback_data=f"sendall_{encoded_title}")])
            buttons.append([InlineKeyboardButton("🔢 Custom Range (e.g. 1-5)", callback_data=f"askrange_{encoded_title}")])

            choice_kb = InlineKeyboardMarkup(buttons)
            return await message.reply_text(
                f"📚 <b>{clean_title}</b>\n\n"
                f"⚠️ इस स्टोरी में कुल <b>{total_files}</b> फाइल्स उपलब्ध हैं।\n"
                f"कृपया अपना पसंदीदा भाग चुनें या इच्छित रेंज टाइप करें:",
                reply_markup=choice_kb,
                quote=True
            )

        # Fallback if > 100 Files but no Custom Ranges configured
        if total_files > 100:
            choice_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📦 All Episodes ({total_files} Files)", callback_data=f"sendall_{encoded_title}")],
                [InlineKeyboardButton("🔢 Custom Range (e.g. 1-5)", callback_data=f"askrange_{encoded_title}")]
            ])
            return await message.reply_text(
                f"📚 <b>{clean_title}</b>\n\n"
                f"⚠️ इस स्टोरी में कुल <b>{total_files}</b> फाइल्स उपलब्ध हैं।\n"
                f"आप सभी एपिसोड्स एक साथ पाना चाहते हैं या कुछ खास रेंज?",
                reply_markup=choice_kb,
                quote=True
            )

        # Directly send files if <= 100
        await send_story_files_start(client, user.id, story, first_id, last_id, clean_title)
        return

    # 3. DIRECT STORY VIEW FROM DEEP LINK (story_ENCODED_TITLE)
    if len(args) > 1 and args[1].startswith("story_"):
        raw_param = args[1]
        story_title = raw_param.replace("story_", "").replace("_", " ")
        story = await get_story_by_title(story_title)
        
        if story:
            clean_title = story['title'].strip().split("\n")[0]
            encoded_title = clean_title.replace(" ", "_")
            photo_url = story.get('photo', 'https://picsum.photos/400/200')
            desc = story.get('desc', 'ɴᴏ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴀᴠᴀɪʟᴀʙʟᴇ.')
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
                    f"💳 ᴅɪʀᴇᴄᴛ ʙᴜᴜ (₹{story['price']})", 
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
                f"📖 <b>ᴛɪᴛʟᴇ:</b> {clean_title}\n"
                f"💰 <b>ᴘʀɪᴄᴇ:</b> ₹{story['price']}\n"
                f"👛 <b>ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ:</b> ₹{wallet_bal}\n"
                f"📝 <b>ᴅᴇsᴄ:</b> {desc}\n\n"
                f"<i>👇 Choose an option below to view or purchase:</i>"
            )
            
            try:
                return await message.reply_photo(photo=photo_url, caption=caption_text, reply_markup=btn, quote=True)
            except Exception:
                return await message.reply_text(caption_text, reply_markup=btn, quote=True)
        else:
            return await message.reply_text("❌ <b>ᴛʜɪs sᴛᴏʀʏ ɪs ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ.</b>", reply_markup=MAIN_MENU, quote=True)

    # 4. NORMAL /START WELCOME MESSAGE
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
        [InlineKeyboardButton("💬 ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ ғᴏʀ ᴛᴏᴘᴜᴘ", url="https://t.me/kaluu_help_bot")]
    ])
    await callback_query.message.edit_text(text, reply_markup=kb)

# ------------------ Dynamic Button Handlers ------------------

@Client.on_message(filters.regex("^(🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ|🚀 Open Mini App)$") & filters.private)
async def open_miniapp_handler(client, message):
    text = (
        "🚀 <b>ᴍɪɴɪ sᴛᴏʀᴇ ᴀᴘᴘ</b>\n\n"
        "ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴏᴘᴇɴ ᴏᴜʀ ᴏғғɪᴄɪᴀʟ ᴍɪɴɪ ᴀᴘᴘ ᴀɴᴅ ᴇxᴘʟᴏʀᴇ ᴀʟʟ sᴛᴏʀɪᴇs!"
    )
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 ʟᴀᴜɴᴄʜ ᴍɪɴɪ ᴀᴘᴘ", web_app=WebAppInfo(url=WEB_APP_URL))]
    ])
    await message.reply_text(text, reply_markup=btn, quote=True)

@Client.on_message(filters.regex("^(📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ|📢 Updates Channel)$") & filters.private)
async def updates_handler(client, message):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ", url="https://t.me/freestoryhubMR")]
    ])
    await message.reply_text("<b>📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ:</b>\n\nᴊᴏɪɴ ᴏᴜʀ ᴄʜᴀɴɴᴇʟ ғᴏʀ ᴛʜᴇ ʟᴀᴛᴇsᴛ ᴜᴘᴅᴀᴛᴇs ᴀɴᴅ ɴᴇᴡ sᴛᴏʀɪᴇs!", reply_markup=kb, quote=True)

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
    
    if not purchases:
        acc_text += "❌ <b>ʏᴏᴜ ʜᴀᴠᴇɴ'ᴛ ᴘᴜʀᴄʜᴀsᴇᴅ ᴀɴʏ sᴛᴏʀɪᴇs ʏᴇᴛ.</b>"
        return await message.reply_text(acc_text, quote=True)
    
    acc_text += "📖 <b>ʏᴏᴜʀ ᴘᴜʀᴄʜᴀsᴇᴅ sᴛᴏʀɪᴇs:</b>\n\n"
    buttons = []
    
    for item in purchases:
        story = await get_story_by_title(item['story_title'])
        if story:
            clean_title = story['title'].strip().split("\n")[0]
            encoded_title = clean_title.replace(" ", "_")
            delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"
            
            acc_text += f"• <b>{clean_title}</b>\n"
            buttons.append([InlineKeyboardButton(f"🚀 ᴀᴄᴄᴇss {clean_title}", url=delivery_link)])
            
    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
    await message.reply_text(acc_text, reply_markup=reply_markup, quote=True)

@Client.on_message(filters.regex("^(📞 sᴜᴘᴘᴏʀᴛ|📞 Support)$") & filters.private)
async def support_handler(client, message):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ", url="https://t.me/pratilipifm0900")]
    ])
    await message.reply_text("<b>📞 ᴄᴜsᴛᴏᴍᴇʀ sᴜᴘᴘᴏʀᴛ:</b>\n\nɪғ ʏᴏᴜ ғᴀᴄᴇ ᴀɴʏ ɪssᴜᴇs, ғᴇᴇʟ ғʀᴇᴇ ᴛᴏ ᴄᴏɴᴛᴀᴄᴛ support.", reply_markup=kb, quote=True)
