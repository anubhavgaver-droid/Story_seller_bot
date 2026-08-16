from pyrogram import Client, filters
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from database.db import get_story_by_title, send_log
from config import BOT_USERNAME

@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    user = message.from_user
    
    # 1. Log Channel Notification (Safe Try-Except)
    try:
        log_text = (
            f"<b>🚀 Bot Started!</b>\n"
            f"<b>Name:</b> {user.first_name}\n"
            f"<b>User ID:</b> <code>{user.id}</code>\n"
            f"<b>Username:</b> @{user.username if user.username else 'None'}"
        )
        await send_log(client, log_text)
    except Exception as e:
        print(f"Log Error: {e}")

    args = message.text.split(maxsplit=1)
    
    # 2. Deep Linking Handling
    if len(args) > 1 and args[1].startswith("story_"):
        story_title = args[1].replace("story_", "").replace("_", " ")
        story = await get_story_by_title(story_title)
        
        if story:
            btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Buy Now", callback_data=f"buy_{story['title']}_{story['price']}")]
            ])
            photo_url = story.get('photo', 'https://picsum.photos/400/200')
            desc = story.get('desc', 'कोई विवरण उपलब्ध नहीं है।')
            
            try:
                return await message.reply_photo(
                    photo=photo_url,
                    caption=f"📖 <b>Title:</b> {story['title']}\n💰 <b>Price:</b> ₹{story['price']}\n📝 <b>Desc:</b> {desc}",
                    reply_markup=btn
                )
            except Exception as e:
                # अगर फ़ोटो लोड न हो तो सिंपल मैसेज भेजेगा
                return await message.reply_text(
                    f"📖 <b>Title:</b> {story['title']}\n💰 <b>Price:</b> ₹{story['price']}\n📝 <b>Desc:</b> {desc}",
                    reply_markup=btn
                )
        else:
            return await message.reply_text("❌ यह स्टोरी उपलब्ध नहीं है।")

    # 3. Normal Start Command Response
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
        f"हेलो {user.first_name}! 👋\n\n"
        "नीचे दिए गए बटन्स का उपयोग करके अपनी स्टोरीज़ खोजें या खरीदें।"
    )
    await message.reply_text(welcome_text, reply_markup=keyboard)
