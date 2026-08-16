from pyrogram import Client, filters
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from database.db import get_stories_by_cat, search_stories_db, get_story_by_title

# Search State Dictionary
SEARCH_WAITING = {}

# Main Menu Keyboard
MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📢 Updates Channel")],
        [KeyboardButton("🔎 Search Story"), KeyboardButton("📻 Pocket FM")],
        [KeyboardButton("📚 Pratilipi FM"), KeyboardButton("👤 My Account")],
        [KeyboardButton("📞 Support")]
    ],
    resize_keyboard=True
)

# 1. Pocket FM / Pratilipi FM Category Handler
@Client.on_message(filters.regex("^(📻 Pocket FM|📚 Pratilipi FM)$") & filters.private)
async def category_handler(client, message):
    cat_map = {"📻 Pocket FM": "pocket_fm", "📚 Pratilipi FM": "pratilipi_fm"}
    cat_key = cat_map[message.text]
    
    stories, total_pages = await get_stories_by_cat(cat_key, page=1, limit=50)
    
    if not stories:
        return await message.reply_text(f"❌ {message.text} में कोई स्टोरी उपलब्ध नहीं है।", reply_markup=MAIN_MENU)
        
    keyboard_buttons = [[KeyboardButton(f"📖 {s['title']}")] for s in stories]
    keyboard_buttons.append([KeyboardButton("🔙 Back to Main Menu")])
    
    category_keyboard = ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True)
    await message.reply_text(f"<b>📚 Available Stories ({message.text}):</b>\n\nनीचे दी गई लिस्ट से अपनी स्टोरी चुनें:", reply_markup=category_keyboard)

# 2. Back to Main Menu Handler
@Client.on_message(filters.regex("^(🔙 Back to Main Menu|/start)$") & filters.private)
async def back_to_main_menu(client, message):
    user_id = message.from_user.id
    SEARCH_WAITING.pop(user_id, None)  # Reset search state
    await message.reply_text("<b>🌟 Main Menu:</b>", reply_markup=MAIN_MENU)

# 3. Story Selection Click Handler (📖 Story Title)
@Client.on_message(filters.regex("^📖 ") & filters.private)
async def story_selected_handler(client, message):
    story_title = message.text.replace("📖 ", "").strip()
    story = await get_story_by_title(story_title)
    
    if not story:
        return await message.reply_text("❌ यह स्टोरी उपलब्ध नहीं है।")
        
    clean_title = story['title'].replace(" ", "_")
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("💳 Buy Now", callback_data=f"buy_{clean_title}_{story['price']}")]])
    photo_url = story.get('photo', 'https://picsum.photos/400/200')
    desc = story.get('desc', 'कोई विवरण उपलब्ध नहीं है।')
    
    try:
        await message.reply_photo(
            photo=photo_url,
            caption=f"📖 <b>Title:</b> {story['title']}\n💰 <b>Price:</b> ₹{story['price']}\n📝 <b>Desc:</b> {desc}",
            reply_markup=btn
        )
    except Exception:
        await message.reply_text(
            f"📖 <b>Title:</b> {story['title']}\n💰 <b>Price:</b> ₹{story['price']}\n📝 <b>Desc:</b> {desc}",
            reply_markup=btn
        )

# 4. Search Prompt Handler (State sets True here)
@Client.on_message(filters.regex("^🔎 Search Story$") & filters.private)
async def search_prompt(client, message):
    user_id = message.from_user.id
    SEARCH_WAITING[user_id] = True
    await message.reply_text(
        "<b>Now you can search your story!</b> 🔍\n\nअपनी स्टोरी का नाम लिखकर भेजें:",
        reply_markup=ForceReply(True)
    )

# 5. Search Process (Only triggers when SEARCH_WAITING is Active)
@Client.on_message(
    filters.private 
    & filters.text 
    & ~filters.command(["start", "addstory", "deletestory", "allstories", "cancel"]) 
    & ~filters.regex("^(📢 Updates Channel|👤 My Account|📞 Support|📻 Pocket FM|📚 Pratilipi FM|🔙 Back to Main Menu|📖 |🔎 Search Story)"),
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
    
    # Remove user from state after processing search
    SEARCH_WAITING.pop(user_id, None)
    
    if not stories:
        return await message.reply_text(f"❌ <b>'{query}'</b> नाम से कोई स्टोरी नहीं मिली!", reply_markup=MAIN_MENU)
        
    keyboard_buttons = [[KeyboardButton(f"📖 {s['title']}")] for s in stories]
    keyboard_buttons.append([KeyboardButton("🔙 Back to Main Menu")])
    
    search_keyboard = ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True)
    await message.reply_text(f"🔍 <b>Found Stories matching '{query}':</b>", reply_markup=search_keyboard)
