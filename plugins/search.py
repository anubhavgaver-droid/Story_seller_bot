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
    CallbackQuery,
    ReplyKeyboardRemove
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
from config import BOT_USERNAME, CHANNEL_ID

SEARCH_WAITING = {}
PAGE_LIMIT = 10  # एक बार में दिखाने के लिए स्टोरीज की संख्या


# 1. Main Market / Platform Keyboard
MARKET_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ")],
        [KeyboardButton("🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ")],
        [KeyboardButton("📻 ᴘᴏᴄᴋᴇᴛ ғᴍ"), KeyboardButton("📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ")],
        [KeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴇɴᴜ")]
    ],
    resize_keyboard=True
)

# Helper function to build paginated story list
def build_story_keyboard(stories, page=1, total_pages=1, category_key=None):
    keyboard_buttons = []
    
    # Story selection buttons (Only First Line Title)
    for s in stories:
        clean_title = s['title'].strip().splitlines()[0]
        keyboard_buttons.append([KeyboardButton(f"📖 {clean_title}")])
    
    # Navigation row if pagination applies
    nav_buttons = []
    if page > 1:
        nav_buttons.append(KeyboardButton("⏪ ᴘʀᴇᴠɪᴏᴜs"))
    if page < total_pages:
        nav_buttons.append(KeyboardButton("ɴᴇxᴛ ⏩"))
        
    if nav_buttons:
        keyboard_buttons.append(nav_buttons)
        
    keyboard_buttons.append([KeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴘʟᴀᴛғᴏʀᴍ")])
    return ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True)


# 2. Pocket FM / Pratilipi FM Category Handler
@Client.on_message(filters.regex("^(📻 ᴘᴏᴄᴋᴇᴛ ғᴍ|📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ|📻 Pocket FM|📚 Pratilipi FM|📻 POCKET FM|📚 PRATILIPI FM)$") & filters.private)
async def category_handler(client, message):
    cat_map = {
        "📻 ᴘᴏᴄᴋᴇᴛ ғᴍ": "pocket_fm", "📻 Pocket FM": "pocket_fm", "📻 POCKET FM": "pocket_fm",
        "📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ": "pratilipi_fm", "📚 Pratilipi FM": "pratilipi_fm", "📚 PRATILIPI FM": "pratilipi_fm"
    }
    cat_key = cat_map[message.text]
    stories, total_pages = await get_stories_by_cat(cat_key, page=1, limit=PAGE_LIMIT)
    
    if not stories:
        return await message.reply_text(
            f"❌ <b>ɴᴏ sᴛᴏʀɪᴇs ᴀᴠᴀɪʟᴀʙʟᴇ ɪɴ {message.text.upper()}.</b>", 
            reply_markup=MARKET_MENU, 
            quote=True
        )
        
    category_keyboard = build_story_keyboard(stories, page=1, total_pages=total_pages, category_key=cat_key)
    
    await message.reply_text(
        f"📚 <b>ᴀᴠᴀɪʟᴀʙʟᴇ sᴛᴏʀɪᴇs ({message.text.upper()}):</b>\n\n"
        f"<i>sᴇʟᴇᴄᴛ ʏᴏᴜʀ sᴛᴏʀʏ ʙᴇʟᴏᴡ ᴛᴏ ᴠɪᴇᴡ ᴅᴇᴛᴀɪʟs:</i>", 
        reply_markup=category_keyboard, 
        quote=True
    )


# 3. Back to Menu Handler
@Client.on_message(filters.regex("^(🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴇɴᴜ|🔙 Back to Menu|🔙 BACK TO MENU)$") & filters.private)
async def back_to_menu_handler(client, message):
    user_id = message.from_user.id
    SEARCH_WAITING.pop(user_id, None)

    try:
        temp_msg = await message.reply_text(
            "⏳ <i>ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...</i>", 
            reply_markup=ReplyKeyboardRemove()
        )
        await asyncio.sleep(0.3)
        await temp_msg.delete()
    except Exception:
        pass
    
    user = message.from_user
    welcome_msg = (
        f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"🌟 <b>sᴛᴏʀʏ sᴇʟʟᴇʀ ʙᴏᴛ</b> 🌟\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"<b>ʜᴇʟʟᴏ {user.first_name}! 👋</b>\n\n"
        f"वेलकम! मार्केट ओपन करने या अपना वॉलेट/अकाउंट देखने के लिए नीचे दिए गए बटन पर क्लिक करें:"
    )

    main_inline_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛒 ᴏᴘᴇɴ ᴍᴀʀᴋᴇᴛ / sᴛᴏʀᴇ", callback_data="open_market_cb")
        ],
        [
            InlineKeyboardButton("💼 ᴍʏ ᴡᴀʟʟᴇᴛ", callback_data="open_wallet_cb"),
            InlineKeyboardButton("👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ", callback_data="open_account_cb")
        ],
        [
            InlineKeyboardButton("🎁 ʀᴇғᴇʀ & ᴇᴀʀɴ", callback_data="open_refer_cb")
        ],
        [
            InlineKeyboardButton("📢 ᴜᴘᴅᴀᴛᴇs", url="https://t.me/freestoryhubMR"),
            InlineKeyboardButton("📞 sᴜᴘᴘᴏʀᴛ", url="https://t.me/pratilipifm0900")
        ]
    ])

    await message.reply_text(
        text=welcome_msg,
        reply_markup=main_inline_kb,
        quote=True
    )


# 3.1 Back to Platform Handler
@Client.on_message(filters.regex("^(🔙 ʙᴀᴄᴋ ᴛᴏ ᴘʟᴀᴛғᴏʀᴍ|🔙 Back to Platform|🔙 BACK TO PLATFORM)$") & filters.private)
async def back_to_platform_handler(client, message):
    await message.reply_text(
        "<b>🏠 ᴍᴀɪɴ ᴍᴀʀᴋᴇᴛ / ᴘʟᴀᴛғᴏʀᴍ:</b>\n\n"
        "<i>नीचे दिए गए विकल्पों में से चुनें:</i>",
        reply_markup=MARKET_MENU,
        quote=True
    )


# 4. Story Selection Click Handler
@Client.on_message(filters.regex("^📖 ") & filters.private)
async def story_selected_handler(client, message):
    user_id = message.from_user.id
    story_title = message.text.replace("📖 ", "").strip()
    story = await get_story_by_title(story_title)
    
    if not story:
        return await message.reply_text("❌ <b>ᴛʜɪs sᴛᴏʀʏ ɪs ᴄᴜʀʀᴇɴᴛʟʏ ᴜɴᴀᴠᴀɪʟᴀʙʟᴇ.</b>", quote=True)
        
    clean_title = story['title'].strip().splitlines()[0]
    encoded_title = clean_title.replace(" ", "_")
    wallet_bal = await get_user_wallet(user_id)
    
    inline_buttons = []
    
    if story.get('demo_enabled', False):
        inline_buttons.append([InlineKeyboardButton("🎬 ᴠɪᴇᴡ ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ", callback_data=f"viewdemo_{encoded_title}")])
        
    inline_buttons.extend([
        [InlineKeyboardButton(f"💳 ᴅɪʀᴇᴄᴛ ᴘᴀʏ (₹{story['price']})", callback_data=f"buy_{encoded_title}_{story['price']}")],
        [InlineKeyboardButton(f"👛 ᴘᴀʏ ᴠɪᴀ ᴡᴀʟʟᴇᴛ (ʙᴀʟ: ₹{wallet_bal})", callback_data=f"walletpay_{encoded_title}_{story['price']}")]
    ])
    
    btn = InlineKeyboardMarkup(inline_buttons)
    photo_url = story.get('photo', 'https://picsum.photos/400/200')
    
    caption_text = (
        f"📖 <b>sᴛᴏʀʏ :</b> {clean_title}\n"
        f"🔰 <b>sᴛᴀᴛᴜs :</b> {story.get('status', 'Completed')}\n"
        f"🖥️ <b>ᴘʟᴀᴛғᴏʀᴍ :</b> {story.get('category', 'Pocket FM')}\n"
        f"🎭 <b>ɢᴇɴʀᴇ :</b> {story.get('genre', 'Drama')}\n"
        f"🎧 <b>ᴇᴘɪsᴏᴅᴇs :</b> {story.get('episodes', 'N/A')}\n\n"
        f"░▒▓█ ᴘʀɪᴄᴇ - ₹{story['price']} █▓▒░\n\n"
        f"👛 <b>ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ :</b> ₹{wallet_bal}\n\n"
        f"<i>👇 Select a payment method below:</i>"
    )
    
    try:
        await message.reply_photo(photo=photo_url, caption=caption_text, reply_markup=btn, quote=True)
    except Exception:
        await message.reply_text(caption_text, reply_markup=btn, quote=True)


# 5. View Demo Callback Handler
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
            return await callback_query.answer("❌ No demo files found!", show_alert=True)
            
        await callback_query.answer("🎬 Sending demo preview... Check your chat!")
        user_id = callback_query.from_user.id
        sent_messages = []
        
        header_msg = await client.send_message(
            chat_id=user_id,
            text=f"🎬 <b>ᴅᴇᴍᴏ ᴘʀᴇᴠɪᴇᴡ ғᴏʀ:</b> <code>{story['title'].strip().splitlines()[0]}</code>\n\n"
                 f"⏰ <i>This demo preview will automatically auto-delete in 10 minutes!</i>"
        )
        sent_messages.append(header_msg)
        
        for msg_id in demo_ids:
            try:
                copied_msg = await client.copy_message(
                    chat_id=user_id,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg_id,
                    caption=f"🎧 <b>ᴅᴇᴍᴏ sᴀᴍᴘʟᴇ</b> - {story['title'].strip().splitlines()[0]}"
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
        await callback_query.answer("❌ Failed to send demo preview!", show_alert=True)


# 6. Wallet Deduction Payment Callback Handler
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
                f"❌ Insufficient Balance!\n\nRequired: ₹{price}\nAvailable: ₹{current_balance}\n\nPlease add money to your wallet.",
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
            f"📖 <b>sᴛᴏʀʏ :</b> {clean_title}\n"
            f"💸 <b>ᴅᴇᴅᴜᴄᴛᴇᴅ :</b> ₹{price}\n"
            f"👛 <b>ʀᴇᴍᴀɪɴɪɴɢ ʙᴀʟᴀɴᴄᴇ :</b> ₹{new_balance}\n\n"
            f"👇 <i>Click below to unlock and access your story files:</i>"
        )
        
        access_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (ᴜɴʟᴏᴄᴋᴇᴅ)", url=delivery_link)]
        ])
        
        await callback_query.message.edit_text(success_text, reply_markup=access_btn)

    except Exception as e:
        print(f"Error in process_wallet_payment: {e}")
        await callback_query.answer("❌ Error processing wallet payment!", show_alert=True)


# 7. Search Prompt Handler
@Client.on_message(filters.regex("^(🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ|🔎 Search Story|🔎 SEARCH STORY)$") & filters.private)
async def search_prompt(client, message):
    user_id = message.from_user.id
    SEARCH_WAITING[user_id] = True
    
    await message.reply_text(
        "🔎 <b>sᴇᴀʀᴄʜ ʏᴏᴜʀ ғᴀᴠᴏʀɪᴛᴇ sᴛᴏʀʏ!</b>\n\n"
        "<i>Type and send the story title below:</i>\n"
        "<code>(अगर स्पेलिंग में थोड़ी गलती भी होगी, तो बॉट सही रिजल्ट ढूंढ लेगा)</code>",
        reply_markup=ForceReply(selective=True, placeholder="TYPE STORY NAME HERE..."),
        quote=True
    )


# 8. Enhanced Fuzzy Search Process Logic
@Client.on_message(
    filters.private 
    & filters.text 
    & ~filters.command(["start", "addstory", "deletestory", "allstories", "cancel", "addmoney", "broadcast", "refreshstories"]) 
    & ~filters.regex("^(🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ|🚀 OPEN MINI APP|💼 ᴍʏ ᴡᴀʟʟᴇᴛ|📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ|👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ|📞 sᴜᴘᴘᴏʀᴛ|📻 ᴘᴏᴄᴋᴇᴛ ғᴍ|📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ|🎁 ʀᴇғᴇʀ & ᴇᴀʀɴ|🎁 Refer & Earn|🛑 sᴛᴏᴘ ᴅᴇʟɪᴠᴇʀʏ|🛑 Stop Delivery|stop delivery|🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴇɴᴜ|🔙 Back to Menu|🔙 BACK TO MENU|🔙 ʙᴀᴄᴋ ᴛᴏ ᴘʟᴀᴛғᴏʀᴍ|🔙 Back to Platform|🔙 BACK TO PLATFORM|📖 |🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ|🔎 SEARCH STORY|🚀 Open Mini App|💼 My Wallet|📢 Updates Channel|👤 My Account|📞 Support|📻 Pocket FM|📚 Pratilipi FM|🔎 Search Story|⏪ ᴘʀᴇᴠɪᴏᴜs|ɴᴇxᴛ ⏩)$"),
    group=2
)
async def process_search(client, message):
    user_id = message.from_user.id
    
    if user_id not in SEARCH_WAITING:
        message.continue_propagation()
        return

    query = message.text.strip()
    SEARCH_WAITING.pop(user_id, None)
    
    # Fetch all stories for Fuzzy Matching
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
        return await message.reply_text(
            f"❌ <b>ɴᴏ sᴛᴏʀʏ ғᴏᴜɴᴅ ᴍᴀᴛᴄʜɪɴɢ '{query}'!</b>", 
            reply_markup=MARKET_MENU, 
            quote=True
        )
        
    keyboard_buttons = [[KeyboardButton(f"📖 {s['title'].strip().splitlines()[0]}")] for s in matched_stories]
    keyboard_buttons.append([KeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴘʟᴀᴛғᴏʀᴍ")])
    
    search_keyboard = ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True)
    await message.reply_text(
        f"🔍 <b>ғᴏᴜɴᴅ sᴛᴏʀɪᴇs ᴍᴀᴛᴄʜɪɴɢ '{query}':</b>", 
        reply_markup=search_keyboard, 
        quote=True
    )
