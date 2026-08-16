from pyrogram import Client, filters
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from database.db import get_stories_by_cat, search_stories_db, get_story_by_title

# Search State Dictionary
SEARCH_WAITING = {}

# Main Menu Keyboard (Small Caps Layout)
MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ")],
        [KeyboardButton("🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ"), KeyboardButton("📻 ᴘᴏᴄᴋᴇᴛ ғᴍ")],
        [KeyboardButton("📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ"), KeyboardButton("👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ")],
        [KeyboardButton("📞 sᴜᴘᴘᴏʀᴛ")]
    ],
    resize_keyboard=True
)

# 1. Pocket FM / Pratilipi FM Category Handler
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
        
    keyboard_buttons = [[KeyboardButton(f"📖 {s['title']}")] for s in stories]
    keyboard_buttons.append([KeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ")])
    
    category_keyboard = ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True)
    await message.reply_text(f"<b>📚 ᴀᴠᴀɪʟᴀʙʟᴇ sᴛᴏʀɪᴇs ({message.text}):</b>\n\nsᴇʟᴇᴄᴛ ʏᴏᴜʀ sᴛᴏʀʏ ғʀᴏᴍ ᴛʜᴇ ʟɪsᴛ ʙᴇʟᴏᴡ:", reply_markup=category_keyboard)

# 2. Back to Main Menu Handler
@Client.on_message(filters.regex("^(🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ|🔙 Back to Main Menu)$") & filters.private)
async def back_to_main_menu(client, message):
    user_id = message.from_user.id
    SEARCH_WAITING.pop(user_id, None)  # Reset search state
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
        await message.reply_photo(
            photo=photo_url,
            caption=caption_text,
            reply_markup=btn
        )
    except Exception:
        await message.reply_text(
            caption_text,
            reply_markup=btn
        )

# 4. Search Prompt Handler (With Selective ForceReply & Small Caps Placeholder)
@Client.on_message(filters.regex("^(🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ|🔎 Search Story)$") & filters.private)
async def search_prompt(client, message):
    user_id = message.from_user.id
    SEARCH_WAITING[user_id] = True
    
    await message.reply_text(
        "<b>ɴᴏᴡ ʏᴏᴜ ᴄᴀɴ sᴇᴀʀᴄʜ ʏᴏᴜʀ sᴛᴏʀʏ!</b> 🔍\n\n"
        "ᴛʏᴘᴇ ᴀɴᴅ sᴇɴᴅ ᴛʜᴇ sᴛᴏʀʏ ɴᴀᴍᴇ:",
        reply_markup=ForceReply(selective=True, placeholder="ᴛʏᴘᴇ sᴛᴏʀʏ ɴᴀᴍᴇ ʜᴇʀᴇ...")
    )

# 5. Clean Search Process
@Client.on_message(
    filters.private 
    & filters.text 
    & ~filters.command(["start", "addstory", "deletestory", "allstories", "cancel"]) 
    & ~filters.regex("^(📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ|👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ|📞 sᴜᴘᴘᴏʀᴛ|📻 ᴘᴏᴄᴋᴇᴛ ғᴍ|📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ|🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ|📖 |🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ|📢 Updates Channel|👤 My Account|📞 Support|📻 Pocket FM|📚 Pratilipi FM|🔙 Back to Main Menu|🔎 Search Story)"),
    group=2
)
async def process_search(client, message):
    user_id = message.from_user.id
    
    # Check if user actually pressed the search button
    if user_id not in SEARCH_WAITING:
        message.continue_propagation()
        return

    query = message.text.strip()
    stories, total_pages = await search_stories_db(query, page=1, limit=50)
    
    # Reset search state after process
    SEARCH_WAITING.pop(user_id, None)
    
    if not stories:
        return await message.reply_text(f"❌ <b>ɴᴏ sᴛᴏʀʏ ғᴏᴜɴᴅ ᴡɪᴛʜ ɴᴀᴍᴇ '{query}'!</b>", reply_markup=MAIN_MENU)
        
    keyboard_buttons = [[KeyboardButton(f"📖 {s['title']}")] for s in stories]
    keyboard_buttons.append([KeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ")])
    
    search_keyboard = ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True)
    await message.reply_text(f"🔍 <b>ғᴏᴜɴᴅ sᴛᴏʀɪᴇs ᴍᴀᴛᴄʜɪɴɢ '{query}':</b>", reply_markup=search_keyboard)
