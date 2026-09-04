import re
from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_USERNAME, CHANNEL, TUTORIAL_VIDEO_URL


async def send_story_to_channel(client: Client, story_data: dict):
    """
    जब भी /addstory विजार्ड से स्टोरी सेव होगी,
    यह फ़ंक्शन स्टोर चैनल पर Buy Now (Direct Telegram Mini App Link), 
    Tutorial और Direct Bot Order बटन के साथ पोस्ट भेजेगा।
    """
    if not CHANNEL:
        print("⚠️ CHANNEL_ID config.py में सेट नहीं है!")
        return None

    try:
        title = story_data.get('title', 'New Story')
        price = story_data.get('price', 0)
        photo = story_data.get('photo', None)
        
        # New Schema Fields Extraction
        status = story_data.get('status', 'Completed')
        platform = story_data.get('category', 'Pocket FM')
        genre = story_data.get('genre', 'Drama')
        episodes = story_data.get('episodes', 'N/A')

        clean_title = title.strip().split("\n")[0]
        encoded_title = clean_title.replace(" ", "_")

        # Telegram Mini App Direct Link Format
        miniapp_url = f"https://t.me/{BOT_USERNAME}/Store?startapp=story_{encoded_title}"
        bot_direct_url = f"https://t.me/{BOT_USERNAME}?start=story_{encoded_title}"

        # Buttons Setup
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🛒 ʙᴜʏ ɴᴏᴡ", url=miniapp_url),
                InlineKeyboardButton("📖 ᴛᴜᴛᴏʀɪᴀʟ", url=TUTORIAL_VIDEO_URL)
            ],
            [
                InlineKeyboardButton("⚡ ᴅɪʀᴇᴄᴛ ʙᴏᴛ ᴏʀᴅᴇʀ", url=bot_direct_url)
            ]
        ])

        # Post Caption Layout with New Schema
        post_caption = (
            f"♨️ <b>Story :</b> {clean_title}\n"
            f"🔰 <b>Status :</b> {status}\n"
            f"🖥️ <b>Platform :</b> {platform}\n"
            f"🧩 <b>Genre :</b> {genre}\n"
            f"🎬 <b>Episodes :</b> {episodes}\n\n"
            f"░▒▓█ PRICE - ₹{price} █▓▒░\n\n"
            f"👇 <i>नीचे दिए गए बटन पर क्लिक करके स्टोरी अनलॉक करें:</i>"
        )

        # Send Post (Photo / Text)
        if photo:
            sent_msg = await client.send_photo(
                chat_id=CHANNEL,
                photo=photo,
                caption=post_caption,
                reply_markup=buttons
            )
        else:
            sent_msg = await client.send_message(
                chat_id=CHANNEL,
                text=post_caption,
                reply_markup=buttons
            )

        return sent_msg

    except Exception as e:
        print(f"❌ Channel Post Error: {e}")
        return None
