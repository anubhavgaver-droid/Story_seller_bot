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

# ---------------- CONFIGURATION SETTINGS ----------------
REFER_BONUS = 1.0  # ₹1.00 Per Referral
ADMIN_ID = 123456789  # Telegram Admin User ID
YOUR_UPI_ID = "yourvpa@upi"  # UPI ID
YOUR_PAYEE_NAME = "Free Story Hub"  # UPI Name

# Storage Dictionaries
START_RANGE_WAITING = {}
TOPUP_WAITING = {}
USER_PAGE_STATE = {}

# ------------------ Keyboards ------------------
def get_welcome_inline_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 OPEN MARKET", callback_data="open_market_keyboard")],
        [InlineKeyboardButton("🚀 OPEN MINI APP", web_app={"url": WEB_APP_URL})],
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
    ])

def get_market_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("📚 PRATILIPI FM"), KeyboardButton("📻 POCKET FM")],
            [KeyboardButton("🔎 SEARCH STORY")],
            [KeyboardButton("🔙 BACK TO MAIN MENU")]
        ],
        resize_keyboard=True
    )

async def get_category_reply_keyboard(category_name: str, page=1, per_page=10):
    regex_pattern = re.compile(f"^{re.escape(category_name)}$", re.IGNORECASE)
    all_stories = await stories_col.find({"category": regex_pattern}).to_list(length=1000)

    if not all_stories:
        return None, 0, 0

    total_stories = len(all_stories)
    total_pages = (total_stories + per_page - 1) // per_page
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    page_stories = all_stories[start_idx:start_idx + per_page]

    buttons = [[KeyboardButton(f"📖 {story.get('title', 'Untitled').strip().splitlines()[0]}")] for story in page_stories]

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

# ------------------ Helpers ------------------
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

def get_message_searchable_text(msg) -> str:
    if not msg:
        return ""
    combined_texts = [
        text for text in [
            msg.caption,
            msg.text,
            msg.audio.title if msg.audio else None,
            msg.audio.file_name if msg.audio else None,
            msg.audio.performer if msg.audio else None,
            msg.document.file_name if msg.document else None,
            msg.video.file_name if msg.video else None
        ] if text
    ]
    return " | ".join(combined_texts)

async def send_story_files_start(client, user_id, story, first_id, last_id, clean_title, custom_range_text="", target_start_ep=None, target_end_ep=None):
    sent_messages_obj = []
    sent_message_ids = []
    
    chosen_sticker = SEARCH_RANGE_STICKER_ID if target_start_ep is not None else DELIVERY_STICKER_ID
    status_msg = await client.send_sticker(chat_id=user_id, sticker=chosen_sticker)

    msg_ids_to_fetch = list(range(first_id, last_id + 1))
    matching_messages = []

    for i in range(0, len(msg_ids_to_fetch), 200):
        chunk = msg_ids_to_fetch[i:i + 200]
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
    total_files = len(messages_to_send)

    if total_files == 0:
        try:
            await status_msg.delete()
        except Exception:
            pass
        return await client.send_message(
            chat_id=user_id,
            text=f"❌ <b>ɴᴏ ᴍᴀᴛᴄʜɪɴɢ ᴇᴘɪsᴏᴅᴇs ғᴏᴜɴᴅ!</b>\n\nरेंज <b>{custom_range_text}</b> के एपिसोड्स उपलब्ध नहीं हैं।"
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
            await asyncio.sleep(1.0)
        except Exception as e:
            print(f"Error copying message {msg.id}: {e}")

    try:
        await status_msg.delete()
    except Exception:
        pass

    ep_range = get_exact_episode_range(sent_messages_obj) if sent_messages_obj else "Files Range"
    clean_kb = None

    if sent_message_ids:
        clean_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧹 ᴄʟᴇᴀɴ / ᴅᴇʟᴇᴛᴇ ᴀʟʟ ғɪʟᴇs", callback_data=f"rangechatclean_{sent_message_ids[0]}_{sent_message_ids[-1]}")]
        ])

    await client.send_message(
        chat_id=user_id,
        text=f"🎉 <b>ғɪʟᴇs ᴅᴇʟɪᴠᴇʀᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
             f"📖 <b>sᴛᴏʀʏ:</b> {clean_title}\n"
             f"🎧 <b>ʀᴀɴɢᴇ:</b> {ep_range} {custom_range_text}\n"
             f"📦 <b>ᴅᴇʟɪᴠᴇʀᴇᴅ:</b> {len(sent_messages_obj)} / {total_files} Files\n\n"
             f"👇 <i>सुनने के बाद चैट साफ़ करने के लिए नीचे बटन पर क्लिक करें:</i>",
        reply_markup=clean_kb
    )

# ------------------ Handlers ------------------
@Client.on_callback_query(filters.regex("^close_message$"))
async def close_message_handler(_, callback_query):
    try:
        await callback_query.message.delete()
    except Exception:
        pass
    await callback_query.answer()

@Client.on_callback_query(filters.regex(r"^rangechatclean_"))
async def range_clean_chat_handler(client, callback_query):
    try:
        user_id = callback_query.from_user.id
        _, start_id, end_id = callback_query.data.split("_")
        
        await callback_query.answer("🧹 Cleaning files... Please wait!")

        msg_ids_to_delete = list(range(int(start_id), int(end_id) + 1))
        msg_ids_to_delete.append(callback_query.message.id)

        for i in range(0, len(msg_ids_to_delete), 100):
            try:
                await client.delete_messages(chat_id=user_id, message_ids=msg_ids_to_delete[i:i + 100])
                await asyncio.sleep(0.2)
            except Exception as e:
                print(f"Error deleting batch: {e}")

        await client.send_message(chat_id=user_id, text="✅ <b>आपकी डिलीवरी फाइल्स और चैट सफलतापूर्वक साफ़ कर दी गई हैं!</b> 🗑️")
    except Exception as e:
        print(f"Clean chat error: {e}")
        await callback_query.answer("❌ फाइल्स पहले ही डिलीट हो चुकी हैं!", show_alert=True)

@Client.on_message(filters.service & filter_webapp & filters.private)
async def web_app_data_handler(client, message):
    try:
        data = json.loads(message.web_app_data.data)
        action, story_title, price = data.get("action"), data.get("title"), float(data.get("price", 0))
        
        if action in ["view_demo", "demo", "get_demo"]:
            story = await get_story_by_title(story_title)
            if not story or not story.get("demo_enabled") or not story.get("demo_msg_ids"):
                return await message.reply_text("⚠️ <b>इस स्टोरी का डेमो उपलब्ध नहीं है!</b>", quote=True)

            user_id = message.from_user.id
            header_msg = await message.reply_text(
                f"🎬 <b>ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ ғᴏᴏᴛᴀɢᴇ:</b> <code>{story['title']}</code>\n\n"
                f"⏰ <i>यह डेमो सैंपल 10 मिनट बाद अपने आप डिलीट हो जाएगा!</i>", quote=True
            )
            
            sent_messages = [header_msg]
            for msg_id in story.get("demo_msg_ids", []):
                try:
                    copied_msg = await client.copy_message(chat_id=user_id, from_chat_id=CHANNEL_ID, message_id=msg_id, caption=f"🎧 <b>Demo Sample</b> - {story['title']}")
                    sent_messages.append(copied_msg)
                except Exception as e:
                    print(f"Error copying demo msg {msg_id}: {e}")

            async def auto_delete_task(msgs):
                await asyncio.sleep(600)
                for msg in msgs:
                    try:
                        await msg.delete()
                    except Exception:
                        pass

            asyncio.create_task(auto_delete_task(sent_messages))

        elif action == "buy_story":
            story = await get_story_by_title(story_title)
            if not story:
                return await message.reply_text("❌ <b>sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ.</b>", quote=True)

            clean_title = story_title.strip().splitlines()[0]
            encoded_title = clean_title.replace(" ", "_")
            wallet_bal = await get_user_wallet(message.from_user.id)
            
            inline_buttons = []
            if story.get('demo_enabled', False):
                inline_buttons.append([InlineKeyboardButton("🎬 ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ", callback_data=f"viewdemo_{encoded_title}")])

            inline_buttons.extend([
                [InlineKeyboardButton(f"💳 ᴅɪʀᴇᴄᴛ ᴘᴀʏ (₹{price})", callback_data=f"buy_{encoded_title}_{price}")],
                [InlineKeyboardButton(f"👛 ᴘᴀʏ ᴠɪᴀ ᴡᴀʟʟᴇᴛ (Bal: ₹{wallet_bal})", callback_data=f"walletpay_{encoded_title}_{price}")]
            ])
            
            caption_text = (
                f"🛒 <b>ᴏʀᴅᴇʀ ɪɴɪᴛɪᴀᴛᴇᴅ ғᴏʀᴍ ᴍɪɴɪ ᴀᴘᴘ</b>\n\n"
                f"♨️ <b>Story :</b> {clean_title}\n"
                f"🔰 <b>Status :</b> {story.get('status', 'Completed')}\n"
                f"🖥️ <b>Platform :</b> {story.get('category', 'Pocket FM')}\n"
                f"🧩 <b>Genre :</b> {story.get('genre', 'Drama')}\n"
                f"🎬 <b>Episodes :</b> {story.get('episodes', 'N/A')}\n\n"
                f"░▒▓█ PRICE - ₹{price} █▓▒░\n\n"
                f"👛 <b>ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ:</b> ₹{wallet_bal}\n\n"
                f"👇 <b>Select payment method to complete purchase:</b>"
            )
            
            btn = InlineKeyboardMarkup(inline_buttons)
            try:
                await message.reply_photo(photo=story.get('photo', 'https://picsum.photos/400/200'), caption=caption_text, reply_markup=btn, quote=True)
            except Exception:
                await message.reply_text(caption_text, reply_markup=btn, quote=True)
    except Exception as e:
        print(f"WebApp Data Error: {e}")

@Client.on_callback_query(filters.regex(r"^viewdemo_"))
async def view_demo_callback(client: Client, callback_query: CallbackQuery):
    try:
        encoded_title = callback_query.data.split("viewdemo_")[1]
        story = await get_story_by_title(encoded_title.replace("_", " "))
        
        if not story or not story.get("demo_enabled") or not story.get("demo_msg_ids"):
            return await callback_query.answer("⚠️ Demo is not available for this story!", show_alert=True)
            
        await callback_query.answer("🎬 Sending Demo files...")
        user_id = callback_query.from_user.id
        
        header_msg = await client.send_message(
            chat_id=user_id,
            text=f"🎬 <b>ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ ғᴏᴏᴛᴀɢᴇ:</b> <code>{story['title']}</code>\n\n⏰ <i>This demo preview will automatically delete in 10 minutes!</i>"
        )
        
        sent_messages = [header_msg]
        for msg_id in story.get("demo_msg_ids", []):
            try:
                copied_msg = await client.copy_message(chat_id=user_id, from_chat_id=CHANNEL_ID, message_id=msg_id, caption=f"🎧 <b>Demo Sample</b> - {story['title']}")
                sent_messages.append(copied_msg)
            except Exception as e:
                print(f"Error copying demo msg {msg_id}: {e}")

        async def auto_delete_task(msgs):
            await asyncio.sleep(600)
            for msg in msgs:
                try:
                    await msg.delete()
                except Exception:
                    pass
                    
        asyncio.create_task(auto_delete_task(sent_messages))
    except Exception as e:
        print(f"Error in view_demo_callback: {e}")
        await callback_query.answer("❌ Failed to send Demo files!", show_alert=True)

@Client.on_callback_query(filters.regex(r"^buy_"))
async def direct_buy_callback_handler(_, callback_query: CallbackQuery):
    try:
        data_parts = callback_query.data.split("_")
        price = float(data_parts[-1])
        story_title = " ".join(data_parts[1:-1])

        story = await get_story_by_title(story_title)
        if not story:
            return await callback_query.answer("❌ Story not found!", show_alert=True)

        await callback_query.answer("💳 Generating Direct Payment QR...", show_alert=False)
        clean_title = story['title'].strip().splitlines()[0]
        
        upi_url = f"upi://pay?pa={YOUR_UPI_ID}&pn={quote(YOUR_PAYEE_NAME)}&am={price}&cu=INR&tn={quote('Buy ' + clean_title[:20])}"
        qr_api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=350x350&data={quote(upi_url)}"

        pay_info_text = (
            f"💳 <b><u>DIRECT STORY PAYMENT</u></b>\n\n"
            f"📖 <b>Story:</b> {clean_title}\n"
            f"💰 <b>Amount:</b> ₹{price}\n"
            f"🆔 <b>UPI ID:</b> <code>{YOUR_UPI_ID}</code>\n\n"
            f"📲 <b>कैसे पेमेंट करें?</b>\n"
            f"1️⃣ ऊपर दिए गए QR Code को किसी भी UPI ऐप (GPay, PhonePe, Paytm) से स्कैन करें।\n"
            f"2️⃣ ₹{price} का पेमेंट पूरा करें।\n"
            f"3️⃣ पेमेंट का **Screenshot** और आपकी **User ID** (<code>{callback_query.from_user.id}</code>) एडमिन को भेजें।"
        )

        pay_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📲 PAY VIA UPI APP", url=upi_url)],
            [InlineKeyboardButton("📩 SEND PAYMENT SCREENSHOT", url="https://t.me/pratilipifm0900")],
            [InlineKeyboardButton("❌ CLOSE", callback_data="close_message")]
        ])

        try:
            await callback_query.message.reply_photo(photo=qr_api_url, caption=pay_info_text, reply_markup=pay_kb, quote=True)
        except Exception:
            await callback_query.message.reply_text(pay_info_text, reply_markup=pay_kb, quote=True)

    except Exception as e:
        print(f"Error handling direct buy: {e}")
        await callback_query.answer("❌ Failed to process purchase request!", show_alert=True)

@Client.on_callback_query(filters.regex(r"^walletpay_"))
async def process_wallet_payment(_, callback_query):
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

        clean_title = story['title'].strip().splitlines()[0]
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
        
        access_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (Unlocked)", url=delivery_link)]])
        await callback_query.message.edit_text(success_text, reply_markup=access_btn)

    except Exception as e:
        print(f"Error processing wallet payment: {e}")
        await callback_query.answer("❌ Error processing wallet payment!", show_alert=True)

@Client.on_callback_query(filters.regex(r"^(sendall_|sendcustom_|askrange_|add_topup_funds)"))
async def start_batch_callback_router(client, callback_query):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    if data == "add_topup_funds":
        TOPUP_WAITING[user_id] = True
        await callback_query.message.reply_text(
            f"💳 <b><u>WALLET TOP-UP / ADD FUNDS</u></b>\n\n"
            f"आप अपने वॉलेट में कितना अमाउंट ऐड करना चाहते हैं?\n"
            f"<i>(नीचे अमाउंट लिखें, उदाहरण: <code>10</code>, <code>50</code>, <code>100</code>)</i>",
            reply_markup=ForceReply(selective=True)
        )
        await callback_query.answer()

    elif data.startswith("sendall_"):
        encoded_title = data.split("sendall_")[1]
        story = await get_story_by_title(encoded_title.replace("_", " "))
        if not story:
            return await callback_query.answer("❌ Story not found!", show_alert=True)
            
        await callback_query.message.delete()
        await send_story_files_start(client, user_id, story, story['first_msg_id'], story['last_msg_id'], story['title'].strip().splitlines()[0])
        await callback_query.answer()

    elif data.startswith("sendcustom_"):
        parts = data.split(":")
        encoded_title = parts[0].replace("sendcustom_", "")
        range_idx = int(parts[1])

        story = await get_story_by_title(encoded_title.replace("_", " "))
        if not story or range_idx >= len(story.get('custom_ranges', [])):
            return await callback_query.answer("❌ Invalid Selection!", show_alert=True)

        selected_range = story['custom_ranges'][range_idx]
        await callback_query.message.delete()
        await send_story_files_start(client, user_id, story, selected_range['first_id'], selected_range['last_id'], story['title'].strip().splitlines()[0], custom_range_text=f"({selected_range['name']})")
        await callback_query.answer()
        
    elif data.startswith("askrange_"):
        encoded_title = data.split("askrange_")[1]
        story = await get_story_by_title(encoded_title.replace("_", " "))
        if not story:
            return await callback_query.answer("❌ Story not found!", show_alert=True)
        
        START_RANGE_WAITING[user_id] = {"story": story, "encoded_title": encoded_title}
        total_episodes = (story['last_msg_id'] - story['first_msg_id']) + 1
        
        await callback_query.message.reply_text(
            f"🔢 <b>Enter Episode Range (1 - {total_episodes}):</b>\n\n"
            f"कृपया रेंज दर्ज करें कि आपको कहाँ से कहाँ तक एपिसोड चाहिए।\n"
            f"<i>(उदाहरण के लिए लिखें: <code>1-5</code> या <code>110-120</code>)</i>",
            reply_markup=ForceReply(selective=True)
        )
        await callback_query.answer()

@Client.on_message(filters.private & filters.text, group=3)
async def process_topup_amount_input(_, message):
    user_id = message.from_user.id
    if user_id not in TOPUP_WAITING:
        return message.continue_propagation()
        
    try:
        amount = float(message.text.strip())
        if amount <= 0:
            return await message.reply_text("❌ **कृपया ₹1 या उससे अधिक का अमाउंट दर्ज करें!**", quote=True)
    except ValueError:
        return await message.reply_text("❌ **केवल नंबर दर्ज करें (जैसे 10, 50, 100)**", quote=True)

    TOPUP_WAITING.pop(user_id, None)

    upi_url = f"upi://pay?pa={YOUR_UPI_ID}&pn={quote(YOUR_PAYEE_NAME)}&am={amount}&cu=INR&tn={quote('Wallet TopUp')}"
    qr_api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=350x350&data={quote(upi_url)}"

    caption_text = (
        f"⚡ <b><u>WALLET TOP-UP QR CODE</u></b>\n\n"
        f"💰 <b>Top-Up Amount:</b> ₹{amount:.2f}\n"
        f"🆔 <b>UPI ID:</b> <code>{YOUR_UPI_ID}</code>\n\n"
        f"📌 <b>पेमेंट करने के निर्देश:</b>\n"
        f"1️⃣ नीचे दिए गए QR Code को किसी भी UPI App (Paytm, PhonePe, GPay) से स्कैन करें।\n"
        f"2️⃣ <b>₹{amount:.2f}</b> का पेमेंट पूरा करें।\n"
        f"3️⃣ पेमेंट का **Screenshot** लें और अपनी <b>User ID:</b> <code>{user_id}</code> के साथ एडमिन को भेजें。\n\n"
        f"⏳ <i>स्क्रीनशॉट मिलने के 2 मिनट के अंदर आपका वॉलेट बैलेंस अपडेट कर दिया जाएगा।</i>"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 DIRECT PAY VIA UPI APP", url=upi_url)],
        [InlineKeyboardButton("📩 SEND SCREENSHOT TO ADMIN", url="https://t.me/pratilipifm0900")],
        [InlineKeyboardButton("❌ CLOSE", callback_data="close_message")]
    ])

    try:
        await message.reply_photo(photo=qr_api_url, caption=caption_text, reply_markup=kb, quote=True)
    except Exception:
        await message.reply_text(caption_text, reply_markup=kb, quote=True)

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
        
    data = START_RANGE_WAITING.pop(user_id, None)
    story = data['story']
    
    if start_ep < 1 or start_ep > end_ep:
        return await message.reply_text("❌ <b>अमान्य रेंज!</b> शुरुआत का नंबर 1 से कम या अंत वाले नंबर से बड़ा नहीं हो सकता।", quote=True)

    await send_story_files_start(
        client=client, 
        user_id=user_id, 
        story=story, 
        first_id=story['first_msg_id'], 
        last_id=story['last_msg_id'], 
        clean_title=story['title'].strip().splitlines()[0], 
        custom_range_text=f"(Episodes {start_ep} - {end_ep})",
        target_start_ep=start_ep,
        target_end_ep=end_ep
    )

@Client.on_message(filters.command("addbal") & filters.private)
async def admin_add_balance_cmd(client, message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split()
    if len(args) < 3:
        return await message.reply_text("⚠️ <b>Format:</b> <code>/addbal <user_id> <amount></code>")

    try:
        target_user_id = int(args[1])
        amount = float(args[2])
        
        new_bal = await add_wallet_balance(target_user_id, amount)
        await message.reply_text(f"✅ Successful! User <code>{target_user_id}</code> Wallet Balance Updated: <b>₹{new_bal}</b>")

        try:
            await client.send_message(
                chat_id=target_user_id,
                text=f"🎉 <b><u>WALLET TOP-UP SUCCESSFUL!</u></b>\n\n"
                     f"💰 <b>Added Amount:</b> ₹{amount:.2f}\n"
                     f"👛 <b>Current Wallet Balance:</b> ₹{new_bal:.2f}\n\n"
                     f"आप अपनी पसंद की स्टोरीज खरीदने के लिए वॉलेट बैलेंस का उपयोग कर सकते हैं!"
            )
        except Exception:
            pass
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")

@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    user = message.from_user
    args = message.text.split(maxsplit=1)
    
    # Referral Logic
    try:
        registered = await is_user_registered(user.id)
        if len(args) > 1 and args[1].startswith("ref_"):
            try:
                referrer_id = int(args[1].split("_")[1])
                if referrer_id == user.id:
                    await message.reply_text("⚠️ <b>Hey dude, don't try to use your own referral link!</b>", quote=True)
                elif not registered:
                    await register_user(user.id, user.first_name, user.username)
                    await users_col.update_one({"user_id": user.id}, {"$set": {"referred_by": referrer_id}})
                    new_bal = await add_wallet_balance(referrer_id, REFER_BONUS)
                    
                    try:
                        await client.send_message(
                            chat_id=referrer_id,
                            text=f"🎉 <b>ɴᴇᴡ ʀᴇғᴇʀʀᴀʟ ᴀʟᴇʀᴛ!</b>\n\n👤 <b>{user.first_name}</b> (<code>{user.id}</code>) ने जॉइन किया!\n💰 Bonus: <b>₹{REFER_BONUS:.2f}</b>\n👛 Balance: <b>₹{new_bal}</b>"
                        )
                    except Exception:
                        pass
                else:
                    await message.reply_text("⚠️ <b>You are already an existing user!</b>", quote=True)
            except Exception as ref_err:
                print(f"Referral processing error: {ref_err}")
        elif not registered:
            await register_user(user.id, user.first_name, user.username)
    except Exception as db_err:
        print(f"Database Error in /start registration: {db_err}")

    # Deep-Link Delivery Logic
    if len(args) > 1 and args[1].startswith("get_"):
        story_title = args[1].replace("get_", "").replace("_", " ")
        story = await get_story_by_title(story_title)
        
        if not story:
            return await message.reply_text("❌ <b>sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ ɪɴ ᴅᴀᴛᴀʙᴀsᴇ!</b>", quote=True)

        clean_title = story['title'].strip().splitlines()[0]
        if not await is_story_unlocked(user.id, clean_title):
            buy_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 ʙᴜʏ ɴᴏᴡ", callback_data=f"buy_{args[1].replace('get_', '')}_{story['price']}")]])
            return await message.reply_text(f"🔒 <b>ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ!</b>\n\nPlease buy <b>{clean_title}</b> first.", reply_markup=buy_btn, quote=True)

        first_id, last_id = story.get('first_msg_id'), story.get('last_msg_id')
        if not first_id or not last_id:
            return await message.reply_text("⚠️ <b>ɴᴏ ғɪʟᴇs ᴀssᴏᴄɪᴀᴛᴇᴅ ᴡɪᴛʜ ᴛʜɪs sᴛᴏʀʏ!</b>", quote=True)

        total_files = (last_id - first_id) + 1
        custom_ranges = story.get('custom_ranges', [])

        if custom_ranges:
            buttons = [[InlineKeyboardButton(f"📁 {r['name']}", callback_data=f"sendcustom_{args[1].replace('get_', '')}:{idx}")] for idx, r in enumerate(custom_ranges)]
            buttons.append([InlineKeyboardButton(f"📦 All Episodes ({total_files} Files)", callback_data=f"sendall_{args[1].replace('get_', '')}")])
            return await message.reply_text(f"📚 <b>{clean_title}</b>\n\nफाइल्स उपलब्ध: <b>{total_files}</b>\nअपनी पसंद का विकल्प चुनें:", reply_markup=InlineKeyboardMarkup(buttons), quote=True)

        return await send_story_files_start(client, user.id, story, first_id, last_id, clean_title)

    if len(args) > 1 and args[1].startswith("story_"):
        story = await get_story_by_title(args[1].replace("story_", "").replace("_", " "))
        if story:
            clean_title = story['title'].strip().splitlines()[0]
            encoded_title = clean_title.replace(" ", "_")
            wallet_bal = await get_user_wallet(user.id)
            
            buttons = [[InlineKeyboardButton("🚀 ᴏᴘᴇɴ ᴅɪʀᴇᴄᴛ sᴛᴏʀʏ ᴍɪɴɪ ᴀᴘᴘ", web_app={"url": f"{WEB_APP_URL}?tgWebAppStartParam={args[1]}"})]]
            if story.get('demo_enabled', False):
                buttons.append([InlineKeyboardButton("🎬 ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ", callback_data=f"viewdemo_{encoded_title}")])

            buttons.extend([
                [InlineKeyboardButton(f"🛒 ʙᴜʏ ɴᴏᴡ (₹{story['price']})", callback_data=f"buy_{encoded_title}_{story['price']}")],
                [InlineKeyboardButton(f"👛 ᴘᴀʏ ᴠɪᴀ ᴡᴀʟʟᴇᴛ (Bal: ₹{wallet_bal})", callback_data=f"walletpay_{encoded_title}_{story['price']}")]
            ])

            caption_text = (
                f"♨️ <b>Story :</b> {clean_title}\n"
                f"🔰 <b>Status :</b> {story.get('status', 'Completed')}\n"
                f"🖥️ <b>Platform :</b> {story.get('category', 'Pocket FM')}\n"
                f"🧩 <b>Genre :</b> {story.get('genre', 'Drama')}\n"
                f"🎬 <b>Episodes :</b> {story.get('episodes', 'N/A')}\n\n"
                f"░▒▓█ PRICE - ₹{story['price']} █▓▒░\n\n"
                f"👛 <b>ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ:</b> ₹{wallet_bal}"
            )
            try:
                return await message.reply_photo(photo=story.get('photo', 'https://picsum.photos/400/200'), caption=caption_text, reply_markup=InlineKeyboardMarkup(buttons), quote=True)
            except Exception:
                return await message.reply_text(caption_text, reply_markup=InlineKeyboardMarkup(buttons), quote=True)

    welcome_text = (
        f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"🌟 <b>STORY SELLER BOT</b> 🌟\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"<b>HELLO {user.first_name}! 👋</b>\n\n"
        f"मार्किट ओपन करने के लिए <b>🛒 OPEN MARKET</b> बटन पर क्लिक करें।"
    )
    await message.reply_text(welcome_text, reply_markup=get_welcome_inline_keyboard(), quote=True)

@Client.on_callback_query(filters.regex(r"^(open_market_keyboard|menu_wallet|menu_account|menu_refer)$"))
async def inline_callback_handler(client, callback_query: CallbackQuery):
    data, user_id, user, msg = callback_query.data, callback_query.from_user.id, callback_query.from_user, callback_query.message

    if data == "open_market_keyboard":
        await callback_query.answer()
        await client.send_message(chat_id=user_id, text="👇 <b>Marketplace Open:</b> नीचे दिए गए बटन्स से चुनें:", reply_markup=get_market_reply_keyboard())

    elif data == "menu_wallet":
        await callback_query.answer()
        balance = await get_user_wallet(user_id)
        total_refs = await get_referred_users_count(user_id)

        wallet_text = (
            f"💼 <b><u>YOUR WALLET DASHBOARD</u></b>\n\n"
            f"👤 <b>User:</b> {user.first_name}\n"
            f"🆔 <b>User ID:</b> <code>{user.id}</code>\n\n"
            f"💰 <b>Current Balance:</b> ₹{balance:.2f}\n"
            f"👥 <b>Total Referral Earnings:</b> ₹{total_refs * REFER_BONUS:.2f}"
        )
        wallet_buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ ADD FUNDS / TOP-UP", callback_data="add_topup_funds")],
            [InlineKeyboardButton("🎁 REFER & EARN", callback_data="menu_refer")],
            [InlineKeyboardButton("❌ CLOSE", callback_data="close_message")]
        ])
        await msg.reply_text(wallet_text, reply_markup=wallet_buttons, quote=True)

    elif data == "menu_account":
        await callback_query.answer()
        balance = await get_user_wallet(user_id)
        purchases = await get_user_purchases(user_id)
        total_refs = await get_referred_users_count(user_id)

        acc_text = (
            f"<b>👤 ʏᴏᴜʀ ᴀᴄᴄᴏᴜɴᴛ & ᴘᴜʀᴄʜᴀsᴇs:</b>\n━━━━━━━━━━━━━━━━━━━\n"
            f"<b>👤 ɴᴀᴍᴇ:</b> {user.first_name}\n"
            f"<b>🆔 ᴜsᴇʀ ɪᴅ:</b> <code>{user.id}</code>\n"
            f"<b>👛 ᴡᴀʟʟᴇᴛ ʙᴀʟᴀɴᴄᴇ:</b> ₹{balance:.2f}\n"
            f"<b>👥 Total Referrals:</b> {total_refs} Users\n━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>📚 ʏᴏᴜʀ ᴘᴜʀᴄʜᴀsᴇᴅ sᴛᴏʀɪᴇs:</b>\n"
        )
        buttons = []
        if not purchases:
            acc_text += "❌ <i>आपने कोई स्टोरी परचेस नहीं की है।</i>"
        else:
            for item in purchases:
                story = await get_story_by_title(item['story_title'])
                if story:
                    clean_title = story['title'].strip().splitlines()[0]
                    buttons.append([InlineKeyboardButton(f"🚀 ᴀᴄᴄᴇss {clean_title}", url=f"https://t.me/{BOT_USERNAME}?start=get_{clean_title.replace(' ', '_')}")])

        buttons.append([InlineKeyboardButton("❌ Close", callback_data="close_message")])
        await msg.reply_text(acc_text, reply_markup=InlineKeyboardMarkup(buttons), quote=True)

    elif data == "menu_refer":
        await callback_query.answer()
        refer_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
        wallet = await get_user_wallet(user_id)
        total_refs = await get_referred_users_count(user_id)
        
        ref_text = (
            f"🎁 <b><u>ʀᴇғᴇʀ & ᴇᴀʀɴ ᴘʀᴏɢʀᴀᴍ</u></b>\n\n"
            f"प्रति रेफरल पाएँ <b>₹1.00</b>!\n\n"
            f"👥 <b>Total Referred:</b> {total_refs} Users\n"
            f"👛 <b>Wallet Balance:</b> ₹{wallet:.2f}\n\n"
            f"🔗 <b>आपका लिंक:</b>\n<code>{refer_link}</code>"
        )
        await msg.reply_text(ref_text, quote=True)

@Client.on_message(filters.private & filters.text & ~filters.command(["start", "addbal"]))
async def reply_keyboard_router(client, message):
    text = message.text.strip()
    user_id = message.from_user.id

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
        await message.reply_text(f"📻 <b>Pocket FM Stories</b> (Page {current_page}/{total_pages})\nTotal: {total} Stories", reply_markup=kb)

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
        await message.reply_text(f"📚 <b>Pratilipi FM Stories</b> (Page {current_page}/{total_pages})\nTotal: {total} Stories", reply_markup=kb)

    elif text == "🔎 SEARCH STORY":
        await message.reply_text("🔎 **स्टोरी सर्च करने के लिए:**\n\nकृपया जिस स्टोरी को खोजना चाहते हैं उसका नाम लिखकर भेजें!")

    elif text == "🔙 BACK TO MAIN MENU":
        remove_msg = await message.reply_text("🔄...", reply_markup=ReplyKeyboardRemove())
        await message.reply_text("🏠 **मुख्य मेनू:**", reply_markup=get_welcome_inline_keyboard())
        try:
            await remove_msg.delete()
        except Exception:
            pass

    elif text.startswith("📖 "):
        story_title = text.replace("📖 ", "").strip()
        story = await get_story_by_title(story_title)

        if not story:
            return await message.reply_text("❌ <b>स्टोरी की जानकारी नहीं मिली!</b>", quote=True)

        clean_title = story['title'].strip().splitlines()[0]
        encoded_title = clean_title.replace(" ", "_")
        wallet_bal = await get_user_wallet(user_id)

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
            f"👛 <b>ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ:</b> ₹{wallet_bal}"
        )

        try:
            await message.reply_photo(photo=story.get('photo', 'https://picsum.photos/400/200'), caption=caption_text, reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            await message.reply_text(caption_text, reply_markup=InlineKeyboardMarkup(buttons))
