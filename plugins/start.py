from pyrogram import Client, filters
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from database.db import get_story_by_title
from config import *

@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    args = message.text.split(maxsplit=1)
    
    # शेयरेबल लिंक (Deep Link) क्लिक करने पर
    if len(args) > 1 and args[1].startswith("story_"):
        story_title = args[1].replace("story_", "").replace("_", " ")
        story = await get_story_by_title(story_title)
        if story:
            btn = InlineKeyboardMarkup([[InlineKeyboardButton("💳 Buy Now", callback_data=f"buy_{story['title']}_{story['price']}")]])
            return await message.reply_photo(
                photo=story['photo'],
                caption=f"📖 <b>Title:</b> {story['title']}\n💰 <b>Price:</b> ₹{story['price']}\n📝 <b>Desc:</b> {story['desc']}",
                reply_markup=btn
            )
        else:
            return await message.reply_text("❌ यह स्टोरी उपलब्ध नहीं है।")

    # Photo Keyboard Layout
    keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("📢 Updates Channel")],
            [KeyboardButton("🔎 Search Story"), KeyboardButton("📻 Pocket FM")],
            [KeyboardButton("📚 Pratilipi FM"), KeyboardButton("👤 My Account")],
            [KeyboardButton("📞 Support")]
        ],
        resize_keyboard=True
    )
    
    welcome_text = (
        f"<b>━━━━━━━ 🌟 Story Seller Bot 🌟 ━━━━━━━</b>\n\n"
        f"हेलो {message.from_user.first_name}! 👋\n\n"
        "नीचे दिए गए बटन्स का उपयोग करके अपनी स्टोरीज़ खोजें या खरीदें।"
    )
    await message.reply_text(welcome_text, reply_markup=keyboard)
