import json
import asyncio
import re
import difflib
import time
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
from database.db import (
    get_stories_by_cat, 
    search_stories_db, 
    get_story_by_title,
    get_all_stories,
    get_user_wallet,
    update_user_wallet,
    add_user_purchase,
    is_story_unlocked
)
from config import WEB_APP_URL, BOT_USERNAME, CHANNEL_ID

# State and Storage Dictionaries
SEARCH_WAITING = {}
CLEAN_CHAT_STORAGE = {}
RANGE_WAITING = {}

# 1. Main Menu Reply Keyboard Layout
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

# ------------------ Core Delivery Helper Function ------------------
async def send_story_files(client, user_id, story, first_id, last_id, clean_title, custom_range_text=""):
    sent_message_ids = []
    success_count = 0
    total_files = (last_id - first_id) + 1

    status_msg = await client.send_message(
        user_id, 
        f"⏳ <b>ғᴇᴛᴄʜɪɴɢ ғɪʟᴇs {custom_range_text}...</b>\n<i>ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...</i>"
    )
    
    for msg_id in range(first_id, last_id + 1):
        try:
            sent_msg = await client.copy_message(
                chat_id=user_id,
                from_chat_id=CHANNEL_ID,
                message_id=msg_id,
                protect_content=True
            )
            sent_message_ids.append(sent_msg.id)
            success_count += 1
            await asyncio.sleep(0.4)  # Prevent FloodWait limits
        except Exception as e:
            print(f"Error copying message {msg_id}: {e}")

    # Add the status notification message to cleanup array
    sent_message_ids.append(status_msg.id)
    
    # Store IDs for clean-up callback
    delivery_key = f"{user_id}_{int(time.time())}"
    CLEAN_CHAT_STORAGE[delivery_key] = sent_message_ids

    # One-Click Clean Keyboard
    clean_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧹 ᴄʟᴇᴀɴ / ᴅᴇʟᴇᴛᴇ ᴀʟʟ ғɪʟᴇs", callback_data=f"cleanchat_{delivery_key}")]
    ])

    await client.send_message(
        chat_id=user_id,
        text=f"🎉 <b>ғɪʟᴇs ᴅᴇʟɪᴠᴇʀᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b> {custom_range_text}\n\n"
             f"📖 <b>sᴛᴏʀʏ:</b> {clean_title}\n"
             f"📦 <b>ᴅᴇʟɪᴠᴇʀᴇᴅ:</b> {success_count} / {total_files} Files\n\n"
             f"👇 <i>सुनने के बाद चैट साफ़ करने के लिए नीचे बटन पर क्लिक करें:</i>",
        reply_markup=clean_kb
    )

# 2. 🚀 OPEN MINI APP Handler
@Client.on_message(filters.regex("^(🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ|🚀 Open Mini App)$") & filters.private)
async def miniapp_button_handler(client, message):
    text = (
        "🚀 <b>ᴍɪɴɪ sᴛᴏʀᴇ ᴀᴘᴘ</b>\n\n"
        "ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴏᴘᴇɴ ᴏᴜʀ ᴏғғɪᴄɪᴀʟ ᴍɪɴɪ ᴀᴘᴘ ᴀɴᴅ ᴇxᴘʟᴏʀᴇ ᴀʟʟ sᴛᴏʀɪᴇs!"
    )
    inner_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 ʟᴀᴜɴᴄʜ ᴍɪɴɪ ᴀᴘᴘ", web_app=WebAppInfo(url=WEB_APP_URL))]
    ])
    await message.reply_text(text, reply_markup=inner_kb)

# 3. 💼 MY WALLET Handler
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
    await message.reply_text(text, reply_markup=kb)

# 4. Pocket FM / Pratilipi FM Category Handler
@Client.on_message(filters.regex("^(📻 ᴘᴏᴄᴋᴇᴛ ғᴍ|📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ|📻 Pocket FM|📚 Pratilipi FM)$") & filters.private)
async def category_handler(client, message):
    cat_map = {
        "📻 ᴘᴏᴄᴋᴇᴛ ғᴍ": "pocket_fm", "📻 Pocket FM": "pocket_fm",
        "📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ": "pratilipi_fm", "📚 Pratilipi FM": "pratilipi_fm"
    }
    cat_key = cat_map[message.text]
    stories, total_pages = await get_stories_by_cat(cat_key, page=1, limit=50)
    
    if not stories:
        return await message.reply_text(f"❌ <b>ɴᴏ sᴛᴏʀɪᴇs ᴀᴠᴀɪʟᴀʙʟᴇ ɪɴ {message.text}.</b>", reply_markup=MAIN_MENU)
        
    keyboard_buttons = [[KeyboardButton(f"📖 {s['title'].strip().splitlines()[0]}")] for s in stories]
    keyboard_buttons.append([KeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ")])
    
    category_keyboard = ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True)
    await message.reply_text(f"<b>📚 ᴀᴠᴀɪʟᴀʙʟᴇ sᴛᴏʀɪᴇs ({message.text}):</b>\n\nsᴇʟᴇᴄᴛ ʏᴏᴜʀ sᴛᴏʀʏ ғᴏʀ ᴅᴇᴛᴀɪʟs:", reply_markup=category_keyboard)

# 5. Back to Main Menu Handler
@Client.on_message(filters.regex("^(🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ|🔙 Back to Main Menu)$") & filters.private)
async def back_to_main_menu(client, message):
    user_id = message.from_user.id
    SEARCH_WAITING.pop(user_id, None)
    RANGE_WAITING.pop(user_id, None)
    await message.reply_text("<b>🌟 ᴍᴀɪɴ ᴍᴇɴᴜ:</b>", reply_markup=MAIN_MENU)

# 6. Story Selection Click Handler
@Client.on_message(filters.regex("^📖 ") & filters.private)
async def story_selected_handler(client, message):
    user_id = message.from_user.id
    story_title = message.text.replace("📖 ", "").strip()
    story = await get_story_by_title(story_title)
    
    if not story:
        return await message.reply_text("❌ <b>ᴛʜɪs sᴛᴏʀʏ ɪs ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ.</b>")
        
    clean_title = story['title'].strip().splitlines()[0]
    encoded_title = clean_title.replace(" ", "_")
    wallet_bal = await get_user_wallet(user_id)
    
    inline_buttons = []
    
    if story.get('demo_enabled', False):
        inline_buttons.append([InlineKeyboardButton("🎬 ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ", callback_data=f"viewdemo_{encoded_title}")])
        
    inline_buttons.extend([
        [InlineKeyboardButton(f"💳 ᴅɪʀᴇᴄᴛ ᴘᴀʏ (₹{story['price']})", callback_data=f"buy_{encoded_title}_{story['price']}")],
        [InlineKeyboardButton(f"👛 ᴘᴀʏ ᴠɪᴀ ᴡᴀʟʟᴇᴛ (Bal: ₹{wallet_bal})", callback_data=f"walletpay_{encoded_title}_{story['price']}")]
    ])
    
    btn = InlineKeyboardMarkup(inline_buttons)
    photo_url = story.get('photo', 'https://picsum.photos/400/200')
    desc = story.get('desc', 'ɴᴏ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴀᴠᴀɪʟᴀʙʟᴇ.')
    
    caption_text = (
        f"📖 <b>ᴛɪᴛʟᴇ:</b> {clean_title}\n"
        f"💰 <b>ᴘʀɪᴄᴇ:</b> ₹{story['price']}\n"
        f"👛 <b>ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ:</b> ₹{wallet_bal}\n"
        f"📝 <b>ᴅᴇsᴄ:</b> {desc}\n\n"
        f"<i>Select payment method below:</i>"
    )
    
    try:
        await message.reply_photo(photo=photo_url, caption=caption_text, reply_markup=btn)
    except Exception:
        await message.reply_text(caption_text, reply_markup=btn)

# 6.1 View Demo Callback Handler
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

# 7. Wallet Deduction Payment Callback Handler
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

        clean_title = story['title'].strip().splitlines()[0]
        encoded_title = clean_title.replace(" ", "_")
        delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"

        new_balance = current_balance - price
        await update_user_wallet(user_id, new_balance)
        await add_user_purchase(user_id, clean_title, story_link=delivery_link)

        await callback_query.answer("🎉 Purchase successful!", show_alert=True)
        
        success_text = (
            f"✅ <b>ᴘᴜʀᴄʜᴀsᴇ sᴜᴄᴄᴇssғᴜʟ!</b>\n\n"
            f"📖 <b>sᴛᴏʀʏ:</b> {clean_title}\n"
            f"💸 <b>ᴅᴇᴅᴜᴄᴛᴇᴅ:</b> ₹{price}\n"
            f"👛 <b>ʀᴇᴍᴀɪɴɪɴɢ ʙᴀʟᴀɴᴄᴇ:</b> ₹{new_balance}\n\n"
            f"👇 Click below to access your story:"
        )
        
        access_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (Unlocked)", url=delivery_link)]
        ])
        
        await callback_query.message.edit_text(success_text, reply_markup=access_btn)

    except Exception as e:
        print(f"Error in process_wallet_payment: {e}")
        await callback_query.answer("❌ Error processing wallet payment!", show_alert=True)

# 8. Unified Callback Router (All Episodes, Range Ask & Clean Chat)
@Client.on_callback_query(filters.regex(r"^(sendall_|askrange_|cleanchat_)"))
async def batch_callback_router(client, callback_query):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    # Send All Episodes Option
    if data.startswith("sendall_"):
        encoded_title = data.split("sendall_")[1]
        story_title = encoded_title.replace("_", " ")
        story = await get_story_by_title(story_title)
        if not story:
            return await callback_query.answer("❌ Story not found!", show_alert=True)
            
        await callback_query.message.edit_text("⏳ <b>Preparing to send all files... Please wait!</b>")
        clean_title = story['title'].strip().splitlines()[0]
        await send_story_files(client, user_id, story, story['first_msg_id'], story['last_msg_id'], clean_title)
        await callback_query.answer()
        
    # Ask Custom Range Option
    elif data.startswith("askrange_"):
        encoded_title = data.split("askrange_")[1]
        story_title = encoded_title.replace("_", " ")
        story = await get_story_by_title(story_title)
        if not story:
            return await callback_query.answer("❌ Story not found!", show_alert=True)
        
        RANGE_WAITING[user_id] = {
            "story": story,
            "encoded_title": encoded_title
        }
        
        total_episodes = (story['last_msg_id'] - story['first_msg_id']) + 1
        
        await callback_query.message.reply_text(
            f"🔢 <b>Enter Episode Range (1 - {total_episodes}):</b>\n\n"
            f"कृपया रेंज दर्ज करें कि आपको कहाँ से कहाँ तक एपिसोड चाहिए।\n"
            f"<i>(उदाहरण के लिए लिखें: <code>110-120</code> या <code>1-50</code>)</i>",
            reply_markup=ForceReply(selective=True)
        )
        await callback_query.answer()

    # One-Click Clean / Close Chat Callback
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

# 9. Direct File Batch & Range Delivery Handler (/start get_...)
@Client.on_message(filters.command("start") & filters.private, group=-1)
async def batch_start_handler(client, message):
    user = message.from_user
    args = message.text.split(maxsplit=1)
    
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

        clean_title = story['title'].strip().splitlines()[0]

        # Verify access rights
        unlocked = await is_story_unlocked(user.id, clean_title)
        if not unlocked:
            buy_btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 ʙᴜʏ ɴᴏᴡ", callback_data=f"buy_{encoded_title}_{story['price']}")]
            ])
            return await message.reply_text(
                f"🔒 <b>ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ!</b>\n\nYou haven't purchased <b>{clean_title}</b> yet.",
                reply_markup=buy_btn
            )

        first_id = story.get('first_msg_id')
        last_id = story.get('last_msg_id')

        if not first_id or not last_id:
            return await message.reply_text("⚠️ <b>ɴᴏ ғɪʟᴇs ᴀssᴏᴄɪᴀᴛᴇᴅ ᴡɪᴛʜ ᴛʜɪs sᴛᴏʀʏ!</b>")

        total_files = (last_id - first_id) + 1

        # Check if files exceed 100
        if total_files > 100:
            choice_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📦 All Episodes ({total_files} Files)", callback_data=f"sendall_{encoded_title}")],
                [InlineKeyboardButton("🔢 Custom Range (e.g. 110-120)", callback_data=f"askrange_{encoded_title}")]
            ])
            return await message.reply_text(
                f"📚 <b>{clean_title}</b>\n\n"
                f"⚠️ इस स्टोरी में कुल <b>{total_files}</b> एपिसोड्स हैं।\n"
                f"आप सभी एक साथ मँगवाना चाहते हैं या अपनी पसंद की रेंज?",
                reply_markup=choice_kb
            )

        # Directly send files if 100 or less
        await send_story_files(client, user.id, story, first_id, last_id, clean_title)
        return

# 10. Search Prompt Handler
@Client.on_message(filters.regex("^(🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ|🔎 Search Story)$") & filters.private)
async def search_prompt(client, message):
    user_id = message.from_user.id
    SEARCH_WAITING[user_id] = True
    
    await message.reply_text(
        "<b>ɴᴏᴡ ʏᴏᴜ ᴄᴀɴ sᴇᴀʀᴄʜ ʏᴏᴜʀ sᴛᴏʀʏ!</b> 🔍\n\n"
        "ᴛʏᴘᴇ ᴀɴᴅ sᴇɴᴅ ᴛʜᴇ sᴛᴏʀʏ ɴᴀᴍᴇ:\n"
        "<i>(स्पेलिंग थोड़ी गलत होने पर भी बॉट सही रिजल्ट ढूंढ लेगा)</i>",
        reply_markup=ForceReply(selective=True, placeholder="ᴛʏᴘᴇ sᴛᴏʀʏ ɴᴀᴍᴇ ʜᴇʀᴇ...")
    )

# 11. Process Custom Range Input Text from User
@Client.on_message(filters.private & filters.text, group=3)
async def process_range_input(client, message):
    user_id = message.from_user.id
    if user_id not in RANGE_WAITING:
        return message.continue_propagation()
        
    text = message.text.strip()
    if "-" not in text:
        return await message.reply_text("❌ <b>गलत फॉर्मेट!</b> कृपया सही फॉर्मेट में लिखें, जैसे: <code>110-120</code>")
        
    try:
        start_ep, end_ep = map(int, text.split("-"))
    except ValueError:
        return await message.reply_text("❌ <b>केवल नंबर लिखें</b> (जैसे <code>110-120</code>)।")
        
    data = RANGE_WAITING.get(user_id)
    story = data['story']
    
    db_first = story['first_msg_id']
    db_last = story['last_msg_id']
    total_story_episodes = (db_last - db_first) + 1
    
    # Boundary Validations
    if start_ep < 1 or start_ep > end_ep:
        return await message.reply_text("❌ <b>अमान्य रेंज!</b> शुरुआत का नंबर 1 से कम या अंत वाले नंबर से बड़ा नहीं हो सकता।")
        
    if start_ep > total_story_episodes or end_ep > total_story_episodes:
        return await message.reply_text(
            f"❌ <b>रेंज सीमा से बाहर है!</b>\n\n"
            f"इस स्टोरी में केवल <b>{total_story_episodes}</b> एपिसोड्स उपलब्ध हैं।\n"
            f"कृपया <code>1</code> से <code>{total_story_episodes}</code> के बीच की सीमा दर्ज करें।"
        )

    # State Reset
    RANGE_WAITING.pop(user_id, None)

    # Calculate DB IDs
    target_first = db_first + (start_ep - 1)
    target_last = db_first + (end_ep - 1)
    
    clean_title = story['title'].strip().splitlines()[0]
    
    await send_story_files(
        client, 
        user_id, 
        story, 
        target_first, 
        target_last, 
        clean_title, 
        custom_range_text=f"(Episodes {start_ep} - {end_ep})"
    )

# 12. Enhanced Fuzzy Search Process
@Client.on_message(
    filters.private 
    & filters.text 
    & ~filters.command(["start", "addstory", "deletestory", "allstories", "cancel", "addmoney"]) 
    & ~filters.regex("^(🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ|💼 ᴍʏ ᴡᴀʟʟᴇᴛ|📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ|👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ|📞 sᴜᴘᴘᴏʀᴛ|📻 ᴘᴏᴄᴋᴇᴛ ғᴍ|📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ|🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ|📖 |🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ|🚀 Open Mini App|💼 My Wallet|📢 Updates Channel|👤 My Account|📞 Support|📻 Pocket FM|📚 Pratilipi FM|🔙 Back to Main Menu|🔎 Search Story)"),
    group=2
)
async def process_search(client, message):
    user_id = message.from_user.id
    
    if user_id not in SEARCH_WAITING:
        message.continue_propagation()
        return

    query = message.text.strip()
    SEARCH_WAITING.pop(user_id, None)
    
    # 1. Fetch all stories for Fuzzy Matching
    all_stories = await get_all_stories()
    matched_stories = []
    
    if all_stories:
        title_map = {s['title'].strip().splitlines()[0]: s for s in all_stories}
        story_titles = list(title_map.keys())
        
        # Fuzzy Match using difflib
        close_matches = difflib.get_close_matches(query, story_titles, n=15, cutoff=0.35)
        
        if close_matches:
            matched_stories = [title_map[t] for t in close_matches]
            
    # Fallback to Database Substring Search
    if not matched_stories:
        db_stories, _ = await search_stories_db(query, page=1, limit=50)
        matched_stories = db_stories or []
    
    if not matched_stories:
        return await message.reply_text(f"❌ <b>ɴᴏ sᴛᴏʀʏ ғᴏᴜɴᴅ ᴡɪᴛʜ ɴᴀᴍᴇ '{query}'!</b>", reply_markup=MAIN_MENU)
        
    keyboard_buttons = [[KeyboardButton(f"📖 {s['title'].strip().splitlines()[0]}")] for s in matched_stories]
    keyboard_buttons.append([KeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ 模ᴇɴᴜ")])
    
    search_keyboard = ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True)
    await message.reply_text(f"🔍 <b>ғᴏᴜɴᴅ sᴛᴏʀɪᴇs ᴍᴀᴛᴄʜɪɴɢ '{query}':</b>", reply_markup=search_keyboard)
