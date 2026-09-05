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
    CallbackQuery,
    ReplyKeyboardRemove  # <-- कीबोर्ड क्लोज करने के लिए जोड़ा गया
)
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
from config import WEB_APP_URL, BOT_USERNAME, CHANNEL_ID

# State Storage
SEARCH_WAITING = {}

# Market Reply Keyboard
def get_market_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("📚 PRATILIPI FM"), KeyboardButton("📻 POCKET FM")],
            [KeyboardButton("🔎 SEARCH STORY")],
            [KeyboardButton("🔙 BACK TO MAIN MENU")]
        ],
        resize_keyboard=True
    )

# Welcome Inline Keyboard Layout
def get_welcome_inline_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🛒 OPEN MARKET", callback_data="open_market_keyboard")],
            [InlineKeyboardButton("🚀 OPEN MINI APP", web_app=WebAppInfo(url=WEB_APP_URL))],
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

# 1. Trigger Search Prompt
@Client.on_message(filters.regex("^(🔎 SEARCH STORY|🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ)$") & filters.private)
async def search_prompt_handler(client, message):
    user_id = message.from_user.id
    SEARCH_WAITING[user_id] = True
    
    await message.reply_text(
        "<b>🔎 sᴇᴀʀᴄʜ ʏᴏᴜʀ sᴛᴏʀʏ!</b>\n\n"
        "कृपया जिस स्टोरी को खोजना चाहते हैं उसका नाम लिखकर भेजें:\n"
        "<i>(स्पेलिंग में थोड़ी भूल होने पर भी सही रिजल्ट खोज लिया जाएगा)</i>",
        reply_markup=ForceReply(selective=True, placeholder="Write story name here..."),
        quote=True
    )

# 2. Back to Main Menu Handler (कीबोर्ड क्लोज करने के साथ)
@Client.on_message(filters.regex("^(🔙 BACK TO MAIN MENU|🔙 Back to Main Menu)$") & filters.private)
async def back_to_main_menu(client, message):
    user_id = message.from_user.id
    SEARCH_WAITING.pop(user_id, None)  # सर्च वेटिंग क्लियर करें
    
    # 1. ReplyKeyboardRemove() से रिप्लाई कीबोर्ड हाइड हो जाएगा
    await message.reply_text(
        "🏠 <b>मुख्य मेनू पर वापस आ गए हैं।</b>", 
        reply_markup=ReplyKeyboardRemove(),
        quote=True
    )
    # 2. इनलाइन कीबोर्ड दिखाएं
    await message.reply_text(
        "👇 <b>आगे का विकल्प चुनें:</b>", 
        reply_markup=get_welcome_inline_keyboard()
    )

# 3. Advanced Fuzzy + Database Search Processor
@Client.on_message(
    filters.private 
    & filters.text 
    & ~filters.command(["start", "addstory", "deletestory", "allstories", "cancel", "addmoney", "broadcast"]) 
    & ~filters.regex("^(📚 PRATILIPI FM|📻 POCKET FM|🔎 SEARCH STORY|🔙 BACK TO MAIN MENU|🛒 OPEN MARKET|🚀 OPEN MINI APP|💼 MY WALLET|👤 MY ACCOUNT|🎁 REFER & EARN|📖 )"),
    group=2
)
async def process_story_search(client, message):
    user_id = message.from_user.id
    
    if user_id not in SEARCH_WAITING:
        message.continue_propagation()
        return

    query = message.text.strip()
    SEARCH_WAITING.pop(user_id, None)
    
    # 1. All Stories Fetch for Fuzzy Matching
    all_stories = await get_all_stories()
    matched_stories = []
    
    if all_stories:
        # \n से बचाने के लिए splitlines()[0] का उपयोग
        title_map = {s['title'].strip().splitlines()[0]: s for s in all_stories}
        story_titles = list(title_map.keys())
        
        # Fuzzy String Match (Difflib)
        close_matches = difflib.get_close_matches(query, story_titles, n=15, cutoff=0.35)
        if close_matches:
            matched_stories = [title_map[t] for t in close_matches]
            
    # 2. Database Substring Fallback Search
    if not matched_stories:
        db_stories, _ = await search_stories_db(query, page=1, limit=50)
        matched_stories = db_stories or []
    
    if not matched_stories:
        return await message.reply_text(
            f"❌ <b>ɴᴏ sᴛᴏʀʏ ғᴏᴜɴᴅ ᴍᴀᴛᴄʜɪɴɢ '{query}'!</b>\n\n"
            f"कृपया सही स्पेलिंग लिखकर पुनः प्रयास करें।",
            reply_markup=get_market_reply_keyboard(),
            quote=True
        )
        
    # F-string SyntaxError से बचने के लिए स्वच्छ लूप स्ट्रक्चर
    keyboard_buttons = []
    for s in matched_stories:
        clean_title = s['title'].strip().splitlines()[0]
        keyboard_buttons.append([KeyboardButton(f"📖 {clean_title}")])
        
    keyboard_buttons.append([KeyboardButton("🔙 BACK TO MAIN MENU")])
    
    search_reply_kb = ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True)
    await message.reply_text(
        f"🔍 <b>ғᴏᴜɴᴅ sᴛᴏʀɪᴇs ғᴏʀ '{query}':</b>\n\n"
        f"नीचे दिए गए बटन्स में से अपनी स्टोरी चुनें:", 
        reply_markup=search_reply_kb, 
        quote=True
    )
