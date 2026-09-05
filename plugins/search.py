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

# Database Imports
from database.db import (
    get_stories_by_cat, 
    search_stories_db, 
    get_story_by_title,
    get_all_stories,
    get_user_wallet,
    update_user_wallet,
    add_user_purchase,
    is_story_unlocked,
    stories_col
)

# Config Imports
from config import WEB_APP_URL, BOT_USERNAME, CHANNEL_ID

SEARCH_WAITING = {}

# Main Bottom Reply Keyboard Menu
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

# 1. 📻 Pocket FM / 📚 Pratilipi FM Click Handler (Modifies Reply Keyboard)
@Client.on_message(filters.regex("^(📻 ᴘᴏᴄᴋᴇᴛ ғᴍ|📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ|📻 Pocket FM|📚 Pratilipi FM)$") & filters.private)
async def category_handler(client, message):
    cat_type = "Pratilipi" if "pratilipi" in message.text.lower() else "Pocket"
    cursor = stories_col.find({"category": re.compile(cat_type, re.IGNORECASE)})
    stories = await cursor.to_list(length=100)
    
    if not stories:
        return await message.reply_text(
            f"❌ <b>ɴᴏ sᴛᴏʀɪᴇs ᴀᴠᴀɪʟᴀʙʟᴇ ɪɴ {message.text}.</b>", 
            reply_markup=MAIN_MENU, 
            quote=True
        )
        
    # Build Reply Keyboard with Stories
    keyboard_buttons = []
    for story in stories:
        clean_title = story.get('title', 'Untitled').strip().split('\n')[0]
        keyboard_buttons.append([KeyboardButton(f"📖 {clean_title}")])
        
    keyboard_buttons.append([KeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ")])
    
    category_keyboard = ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True)
    await message.reply_text(
        f"📚 <b>{message.text} Stories:</b>\n\nNeeche diye gaye keyboard se story select karein:", 
        reply_markup=category_keyboard, 
        quote=True
    )

# 2. 🔙 Back to Main Menu Handler
@Client.on_message(filters.regex("^(🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ|🔙 Back to Main Menu)$") & filters.private)
async def back_to_main_menu(client, message):
    user_id = message.from_user.id
    SEARCH_WAITING.pop(user_id, None)
    await message.reply_text("<b>🌟 ᴍᴀɪɴ ᴍᴇɴᴜ:</b>", reply_markup=MAIN_MENU, quote=True)

# 3. 🔎 Search Prompt Handler
@Client.on_message(filters.regex("^(🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ|🔎 Search Story)$") & filters.private)
async def search_prompt(client, message):
    user_id = message.from_user.id
    SEARCH_WAITING[user_id] = True
    
    await message.reply_text(
        "<b>ɴᴏᴡ ʏᴏᴜ ᴄᴀɴ sᴇᴀʀᴄʜ ʏᴏᴜʀ sᴛᴏʀʏ!</b> 🔍\n\n"
        "ᴛʏᴘᴇ ᴀɴᴅ sᴇɴᴅ ᴛʜᴇ sᴛᴏʀʏ ɴᴀᴍᴇ:\n"
        "<i>(स्पेलिंग थोड़ी गलत होने पर भी बॉट सही रिजल्ट ढूंढ लेगा)</i>",
        reply_markup=ForceReply(selective=True, placeholder="ᴛʏᴘᴇ sᴛᴏʀʏ ɴᴀᴍᴇ ʜᴇʀᴇ..."),
        quote=True
    )

# 4. Search Execution -> Modifies Reply Keyboard with Matched Stories
@Client.on_message(
    filters.private 
    & filters.text 
    & ~filters.command(["start", "addstory", "deletestory", "allstories", "cancel", "addmoney", "broadcast", "refreshstories"]) 
    & ~filters.regex("^(🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ|💼 ᴍʏ ᴡᴀʟʟᴇᴛ|📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ|👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ|📞 sᴜᴘᴘᴏʀᴛ|📻 ᴘᴏᴄᴋᴇᴛ ғᴍ|📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ|🎁 ʀᴇғᴇʀ & ᴇᴀʀɴ|🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ|📖 |🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ|🚀 Open Mini App|💼 My Wallet|📢 Updates Channel|👤 My Account|📞 Support|📻 Pocket FM|📚 Pratilipi FM|🔙 Back to Main Menu|🔎 Search Story)"),
    group=2
)
async def process_search(client, message):
    user_id = message.from_user.id
    
    if user_id not in SEARCH_WAITING:
        message.continue_propagation()
        return

    query = message.text.strip()
    SEARCH_WAITING.pop(user_id, None)
    
    all_stories = await get_all_stories()
    matched_stories = []
    
    if all_stories:
        title_map = {s['title'].strip().splitlines()[0]: s for s in all_stories}
        story_titles = list(title_map.keys())
        
        close_matches = difflib.get_close_matches(query, story_titles, n=15, cutoff=0.35)
        if close_matches:
            matched_stories = [title_map[t] for t in close_matches]
            
    if not matched_stories:
        db_stories, _ = await search_stories_db(query, page=1, limit=50)
        matched_stories = db_stories or []
    
    if not matched_stories:
        return await message.reply_text(f"❌ <b>ɴᴏ sᴛᴏʀʏ ғᴏᴜɴᴅ ᴡɪᴛʜ ɴᴀᴍᴇ '{query}'!</b>", reply_markup=MAIN_MENU, quote=True)
        
    keyboard_buttons = [[KeyboardButton(f"📖 {s['title'].strip().splitlines()[0]}")] for s in matched_stories]
    keyboard_buttons.append([KeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ")])
    
    search_keyboard = ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True)
    await message.reply_text(f"🔍 <b>ғᴏᴜɴᴅ sᴛᴏʀɪᴇs ᴍᴀᴛᴄʜɪɴɢ '{query}':</b>", reply_markup=search_keyboard, quote=True)

# 5. Story Selection Click Handler (From Reply Keyboard)
@Client.on_message(filters.regex("^📖 ") & filters.private)
async def story_selected_handler(client, message):
    user_id = message.from_user.id
    story_title = message.text.replace("📖 ", "").strip()
    story = await get_story_by_title(story_title)
    
    if not story:
        return await message.reply_text("❌ <b>ᴛʜɪs sᴛᴏʀʏ ɪs ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ.</b>", quote=True)
        
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
    
    caption_text = (
        f"♨️ <b>Story :</b> {clean_title}\n"
        f"🔰 <b>Status :</b> {story.get('status', 'Completed')}\n"
        f"🖥️ <b>Platform :</b> {story.get('category', 'Pocket FM')}\n"
        f"🧩 <b>Genre :</b> {story.get('genre', 'Drama')}\n"
        f"🎬 <b>Episodes :</b> {story.get('episodes', 'N/A')}\n\n"
        f"░▒▓█ PRICE - ₹{story['price']} █▓▒░\n\n"
        f"👛 <b>ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ:</b> ₹{wallet_bal}\n\n"
        f"<i>Select payment method below:</i>"
    )
    
    try:
        await message.reply_photo(photo=photo_url, caption=caption_text, reply_markup=btn, quote=True)
    except Exception:
        await message.reply_text(caption_text, reply_markup=btn, quote=True)
