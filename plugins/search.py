import json
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
from database.db import get_stories_by_cat, search_stories_db, get_story_by_title
from config import WEB_APP_URL

# Search State Dictionary
SEARCH_WAITING = {}

# 1. Main Menu Keyboard (Inline Keyboard Layout)
MAIN_MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ", callback_data="open_miniapp_info")],
    [InlineKeyboardButton("📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ", url="https://t.me/freestoryhubMR")],
    [
        InlineKeyboardButton("🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ", callback_data="btn_search_story"),
        InlineKeyboardButton("📻 ᴘᴏᴄᴋᴇᴛ ғᴍ", callback_data="cat_pocket_fm")
    ],
    [
        InlineKeyboardButton("📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ", callback_data="cat_pratilipi_fm"),
        InlineKeyboardButton("👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ", callback_data="btn_my_account")
    ],
    [InlineKeyboardButton("📞 sᴜᴘᴘᴏʀᴛ", callback_data="btn_support")]
])

# ------------------ Callback Queries Handler (Button Clicks) ------------------
@Client.on_callback_query()
async def callback_handler(client, query: CallbackQuery):
    data = query.data
    user_id = query.from_user.id

    # A. 🚀 Mini App Info -> Inner WebApp Button Display
    if data == "open_miniapp_info":
        await query.answer()
        miniapp_text = (
            "🚀 <b>ᴍɪɴɪ sᴛᴏʀᴇ ᴀᴘᴘ</b>\n\n"
            "ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴏᴘᴇɴ ᴏᴜʀ ᴏғғɪᴄɪᴀʟ ᴍɪɴɪ ᴀᴘᴘ ᴀɴᴅ ᴇxᴘʟᴏʀᴇ ᴀʟʟ sᴛᴏʀɪᴇs!"
        )
        miniapp_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 ʟᴀᴜɴᴄʜ ᴍɪɴɪ ᴀᴘᴘ", web_app=WebAppInfo(url=WEB_APP_URL))],
            [InlineKeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴇɴᴜ", callback_data="back_to_main")]
        ])
        await query.message.edit_text(miniapp_text, reply_markup=miniapp_kb)

    # B. 📻 Pocket FM & 📚 Pratilipi FM Categories
    elif data in ["cat_pocket_fm", "cat_pratilipi_fm"]:
        await query.answer()
        cat_key = "pocket_fm" if data == "cat_pocket_fm" else "pratilipi_fm"
        cat_title = "📻 ᴘᴏᴄᴋᴇᴛ ғᴍ" if cat_key == "pocket_fm" else "📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ"
        
        stories, total_pages = await get_stories_by_cat(cat_key, page=1, limit=50)
        
        if not stories:
            return await query.message.edit_text(f"❌ <b>ɴᴏ sᴛᴏʀɪᴇs ᴀᴠᴀɪʟᴀʙʟᴇ ɪɴ {cat_title}.</b>", reply_markup=MAIN_MENU)
            
        keyboard_buttons = [[KeyboardButton(f"📖 {s['title']}")] for s in stories]
        keyboard_buttons.append([KeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ")])
        
        category_keyboard = ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True)
        await query.message.delete()
        await client.send_message(
            chat_id=query.message.chat.id,
            text=f"<b>📚 ᴀᴠᴀɪʟᴀʙʟᴇ sᴛᴏʀɪᴇs ({cat_title}):</b>\n\nsᴇʟᴇᴄᴛ ʏᴏᴜʀ sᴛᴏʀʏ ғʀᴏᴍ ᴛʜᴇ ʟɪsᴛ ʙᴇʟᴏᴡ:",
            reply_markup=category_keyboard
        )

    # C. 🔎 Search Story Button Click
    elif data == "btn_search_story":
        await query.answer()
        SEARCH_WAITING[user_id] = True
        await client.send_message(
            chat_id=query.message.chat.id,
            text="<b>ɴᴏᴡ ʏᴏᴜ ᴄᴀɴ sᴇᴀʀᴄʜ ʏᴏᴜʀ sᴛᴏʀʏ!</b> 🔍\n\nᴛʏᴘᴇ ᴀɴᴅ sᴇɴᴅ ᴛʜᴇ sᴛᴏʀʏ ɴᴀᴍᴇ:",
            reply_markup=ForceReply(selective=True, placeholder="ᴛʏᴘᴇ sᴛᴏʀʏ ɴᴀᴍᴇ ʜᴇʀᴇ...")
        )

    # D. 📞 Support
    elif data == "btn_support":
        await query.answer()
        support_text = "<b>📞 ᴄᴜsᴛᴏᴍᴇʀ sᴜᴘᴘᴏʀᴛ:</b>\n\nɪғ ʏᴏᴜ ғᴀᴄᴇ ᴀɴʏ ɪssᴜᴇs, ғᴇᴇʟ ғʀᴇᴇ ᴛᴏ ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ."
        support_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ", url="https://t.me/pratilipifm0900")],
            [InlineKeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴇɴᴜ", callback_data="back_to_main")]
        ])
        await query.message.edit_text(support_text, reply_markup=support_kb)

    # E. 🔙 Back to Main Menu
    elif data == "back_to_main":
        await query.answer()
        welcome_text = (
            "<b>━━━━━━━ 🌟 sᴛᴏʀʏ sᴇʟʟᴇʀ ʙᴏᴛ 🌟 ━━━━━━━</b>\n\n"
            "ᴜsᴇ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ sᴇᴀʀᴄʜ ᴏʀ ᴘᴜʀᴄʜᴀsᴇ ʏᴏᴜʀ ғᴀᴠᴏʀɪᴛᴇ sᴛᴏʀɪᴇs."
        )
        await query.message.edit_text(welcome_text, reply_markup=MAIN_MENU)


# 2. Back to Main Menu Text Handler (Keyboard Button Click)
@Client.on_message(filters.regex("^(🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ|🔙 Back to Main Menu)$") & filters.private)
async def back_to_main_menu(client, message):
    user_id = message.from_user.id
    SEARCH_WAITING.pop(user_id, None)
    await message.reply_text("<b>🌟 ᴍᴀɪɴ ᴍᴇɴᴜ:</b>", reply_markup=MAIN_MENU)


# 3. Story Selection Click Handler (📖 Story Title)
@Client.on_message(filters.regex("^📖 ") & filters.private)
async def story_selected_handler(client, message):
    story_title = message.text.replace("📖 ", "").strip()
    story = await get_story_by_title(story_title)
    
    if not story:
        return await message.reply_text("❌ <b>ᴛʜɪs sᴛᴏʀʏ ɪs ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ.</b>")
        
    clean_title = story['title'].replace(" ", "_")
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("💳 ʙᴜʏ ɴᴏᴡ", callback_data=f"buy_{clean_title}_{story['price']}")]])
    photo_url = story.get('photo', 'https://picsum.photos/400/200')
    desc = story.get('desc', 'ɴᴏ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴀᴠᴀɪʟᴀʙʟᴇ.')
    
    caption_text = f"📖 <b>ᴛɪᴛʟᴇ:</b> {story['title']}\n💰 <b>ᴘʀɪᴄᴇ:</b> ₹{story['price']}\n📝 <b>ᴅᴇsᴄ:</b> {desc}"
    
    try:
        await message.reply_photo(photo=photo_url, caption=caption_text, reply_markup=btn)
    except Exception:
        await message.reply_text(caption_text, reply_markup=btn)


# 4. Clean Search Process
@Client.on_message(
    filters.private 
    & filters.text 
    & ~filters.command(["start", "addstory", "deletestory", "allstories", "cancel"]) 
    & ~filters.regex("^(📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ|👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ|📞 sᴜᴘᴘᴏʀᴛ|📻 ᴘᴏᴄᴋᴇᴛ ғᴍ|📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ|🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ|📖 |🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ)"),
    group=2
)
async def process_search(client, message):
    user_id = message.from_user.id
    
    if user_id not in SEARCH_WAITING:
        message.continue_propagation()
        return

    query = message.text.strip()
    stories, total_pages = await search_stories_db(query, page=1, limit=50)
    
    SEARCH_WAITING.pop(user_id, None)
    
    if not stories:
        return await message.reply_text(f"❌ <b>ɴᴏ sᴛᴏʀʏ ғᴏᴜɴᴅ ᴡɪᴛʜ ɴᴀᴍᴇ '{query}'!</b>", reply_markup=MAIN_MENU)
        
    keyboard_buttons = [[KeyboardButton(f"📖 {s['title']}")] for s in stories]
    keyboard_buttons.append([KeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ")])
    
    search_keyboard = ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True)
    await message.reply_text(f"🔍 <b>ғᴏᴜɴᴅ sᴛᴏʀɪᴇs ᴍᴀᴛᴄʜɪɴɢ '{query}':</b>", reply_markup=search_keyboard)
