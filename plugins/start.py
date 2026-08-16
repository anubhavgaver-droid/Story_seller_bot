from pyrogram import Client, filters
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from database.db import get_story_by_title, send_log, is_user_registered, register_user
from config import BOT_USERNAME

# group=-1 से /start कमांड को Highest Priority मिलती है
@Client.on_message(filters.command("start") & filters.private, group=-1)
async def start_handler(client, message):
    user = message.from_user
    
    # 1. Registration & Logging Check (नए और पुराने यूज़र का फ़िल्टर)
    registered = await is_user_registered(user.id)
    if not registered:
        # नया यूज़र: रजिस्टर करें और लॉग भेजें
        await register_user(user.id, user.first_name, user.username)
        try:
            log_text = (
                f"<b>🆕 New User Registered!</b>\n"
                f"<b>Name:</b> {user.first_name}\n"
                f"<b>User ID:</b> <code>{user.id}</code>\n"
                f"<b>Username:</b> @{user.username if user.username else 'None'}"
            )
            await send_log(client, log_text)
        except Exception as e:
            print(f"Log Error: {e}")

    args = message.text.split(maxsplit=1)
    
    # 2. Deep Linking Handling (Direct Link Clicked)
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
            except Exception:
                return await message.reply_text(
                    f"📖 <b>Title:</b> {story['title']}\n💰 <b>Price:</b> ₹{story['price']}\n📝 <b>Desc:</b> {desc}",
                    reply_markup=btn
                )
        else:
            return await message.reply_text("❌ यह स्टोरी उपलब्ध नहीं है।")

    # 3. Main Menu Layout
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


# ------------------ Dynamic Button Handlers ------------------

@Client.on_message(filters.regex("^📢 Updates Channel$") & filters.private)
async def updates_handler(client, message):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url="https://t.me/YourChannelUsername")]
    ])
    await message.reply_text("<b>📢 Updates Channel:</b>\n\nहमारे लेटेस्ट अपडेट्स और नई स्टोरीज़ के लिए चैनल जॉइन करें!", reply_markup=kb)

@Client.on_message(filters.regex("^👤 My Account$") & filters.private)
async def account_handler(client, message):
    user = message.from_user
    acc_text = (
        f"<b>👤 Account Details:</b>\n\n"
        f"<b>Name:</b> {user.first_name}\n"
        f"<b>User ID:</b> <code>{user.id}</code>\n"
        f"<b>Username:</b> @{user.username if user.username else 'N/A'}\n"
        f"<b>Status:</b> Active User ⚡"
    )
    await message.reply_text(acc_text)

@Client.on_message(filters.regex("^📞 Support$") & filters.private)
async def support_handler(client, message):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Contact Support", url="https://t.me/YourAdminUsername")]
    ])
    await message.reply_text("<b>📞 Customer Support:</b>\n\nअगर आपको कोई समस्या आ रही है, तो सपोर्ट से संपर्क करें।", reply_markup=kb)
