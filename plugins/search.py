import json
import asyncio
import re
import difflib
import time
from pyrogram import Client, filters, enums
from pyrogram.types import (
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

ITEMS_PER_PAGE = 10
SEARCH_WAITING = {}

# 1. Main Inline Menu Markup (Shared Layout)
MAIN_MENU_INLINE = InlineKeyboardMarkup([
    [InlineKeyboardButton("💼 ᴍʏ ᴡᴀʟʟᴇᴛ", callback_data="btn_wallet"), InlineKeyboardButton("👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ", callback_data="btn_account")],
    [InlineKeyboardButton("🎁 ʀᴇғᴇʀ & ᴇᴀʀɴ", callback_data="btn_refer")],
    [InlineKeyboardButton("📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ", url="https://t.me/freestoryhubMR"), InlineKeyboardButton("📞 sᴜᴘᴘᴏʀᴛ", callback_data="btn_support")],
    [InlineKeyboardButton("🛒 ᴏᴘᴇɴ ᴍᴀʀᴋᴇᴛᴘʟᴀᴄᴇ", callback_data="open_marketplace_kb")]
])

# ------------------ Helper: Dynamic 10-10 Pagination Keyboard ------------------
def get_fm_paginated_keyboard(category_name, stories_list, page=0):
    total_items = len(stories_list)
    total_pages = max(1, (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    current_batch = stories_list[start_idx:end_idx]
    
    prefix = "prat" if "pratilipi" in category_name.lower() else "pock"
    keyboard = []
    
    for story in current_batch:
        clean_title = story.get('title', 'Untitled').strip().split('\n')[0]
        encoded = clean_title.replace(" ", "_")
        keyboard.append([InlineKeyboardButton(f"📖 {clean_title}", callback_data=f"getstory_{encoded}")])
        
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"{prefix}_pg_{page - 1}"))
    
    nav_row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"{prefix}_pg_{page + 1}"))
        
    if nav_row:
        keyboard.append(nav_row)
        
    keyboard.append([
        InlineKeyboardButton("👁️ View All", callback_data=f"viewall_{prefix}"),
        InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main_menu")
    ])
    
    return InlineKeyboardMarkup(keyboard)

# 2. Search Prompt Trigger
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

# 3. Fuzzy Search Engine (Inline Output Format)
@Client.on_message(
    filters.private 
    & filters.text 
    & ~filters.command(["start", "addstory", "deletestory", "allstories", "cancel", "addmoney", "broadcast", "refreshstories"]) 
    & ~filters.regex("^(🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ|💼 ᴍʏ ᴡᴀʟʟᴇᴛ|📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ|👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ|📞 sᴜᴘᴘᴏʀᴛ|📻 ᴘᴏᴄᴋᴇᴛ ғᴍ|📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ|🎁 ʀᴇғᴇʀ & ᴇᴀʀɴ|🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ|🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ)"),
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
        return await message.reply_text(f"❌ <b>ɴᴏ sᴛᴏʀʏ ғᴏᴜɴᴅ ᴡɪᴛʜ ɴᴀᴍᴇ '{query}'!</b>", reply_markup=MAIN_MENU_INLINE, quote=True)
        
    # Inline Result Buttons
    inline_buttons = []
    for s in matched_stories:
        clean_title = s['title'].strip().splitlines()[0]
        encoded = clean_title.replace(" ", "_")
        inline_buttons.append([InlineKeyboardButton(f"📖 {clean_title}", callback_data=f"getstory_{encoded}")])
        
    inline_buttons.append([InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main_menu")])
    
    search_keyboard = InlineKeyboardMarkup(inline_buttons)
    await message.reply_text(f"🔍 <b>ғᴏᴜɴᴅ sᴛᴏʀɪᴇs ᴍᴀᴛᴄʜɪɴɢ '{query}':</b>", reply_markup=search_keyboard, quote=True)

# 4. Inline Callback for Story Selection
@Client.on_callback_query(filters.regex(r"^getstory_"))
async def get_story_callback_handler(client, callback: CallbackQuery):
    encoded_title = callback.data.split("getstory_")[1]
    story_title = encoded_title.replace("_", " ")
    story = await get_story_by_title(story_title)
    
    if not story:
        return await callback.answer("❌ Story not found!", show_alert=True)
        
    user_id = callback.from_user.id
    clean_title = story['title'].strip().splitlines()[0]
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
        await callback.message.reply_photo(photo=photo_url, caption=caption_text, reply_markup=btn)
    except Exception:
        await callback.message.reply_text(caption_text, reply_markup=btn)
    await callback.answer()
