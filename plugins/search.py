from pyrogram import Client, filters
from pyrogram.types import ForceReply, InlineKeyboardMarkup, InlineKeyboardButton
from database.db import get_stories_by_cat, search_stories_db

def build_story_keyboard(stories, current_page, total_pages, category=None, query=None):
    buttons = []
    for s in stories:
        buttons.append([InlineKeyboardButton(f"📖 {s['title']} - ₹{s['price']}", callback_data=f"view_{s['title']}")])
    
    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{category or 'search'}_{current_page - 1}"))
    nav_row.append(InlineKeyboardButton(f"📄 {current_page}/{total_pages}", callback_data="noop"))
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{category or 'search'}_{current_page + 1}"))
    
    if nav_row:
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)

@Client.on_message(filters.regex("^🔎 Search Story$"))
async def search_prompt(client, message):
    await message.reply_text(
        "<b>Now you can search your story!</b> 🔍\n\nअपनी स्टोरी का नाम लिखकर भेजें:",
        reply_markup=ForceReply(True)
    )

@Client.on_message(filters.regex("^(📻 Pocket FM|📚 Pratilipi FM)$"))
async def category_handler(client, message):
    cat_map = {"📻 Pocket FM": "pocket_fm", "📚 Pratilipi FM": "pratilipi_fm"}
    cat_key = cat_map[message.text]
    stories, total_pages = await get_stories_by_cat(cat_key, page=1, limit=10)
    
    if not stories:
        return await message.reply_text("❌ इस कैटेगरी में कोई स्टोरी उपलब्ध नहीं है।")
        
    markup = build_story_keyboard(stories, 1, total_pages, category=cat_key)
    await message.reply_text(f"<b>📚 Available Stories ({message.text}):</b>", reply_markup=markup)

@Client.on_message(filters.private & ~filters.command(["start", "addstory"]))
async def process_search(client, message):
    if message.reply_to_message and "search your story" in message.reply_to_message.text.lower():
        query = message.text.strip()
        stories, total_pages = await search_stories_db(query, page=1, limit=10)
        
        if not stories:
            return await message.reply_text(f"❌ <b>'{query}'</b> नाम से कोई स्टोरी नहीं मिली!")
            
        markup = build_story_keyboard(stories, 1, total_pages, query=query)
        await message.reply_text(f"🔍 <b>Found Stories matching '{query}':</b>", reply_markup=markup)

@Client.on_callback_query(filters.regex("^back_to_menu$"))
async def back_menu(client, callback):
    await callback.message.delete()
    await callback.answer("Main Menu")
