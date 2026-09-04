import re
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_USERNAME, WEB_APP_URL, CHANNEL, TUTORIAL_VIDEO_URL

async def send_story_to_channel(client: Client, story_data: dict):
    """
    जब भी ऐडमिन विजार्ड (/addstory) से नई स्टोरी सेव होगी, 
    यह फ़ंक्शन स्टोरी चैनल पर Buy Now बटन के साथ पोस्ट ऑटो-पब्लिश करेगा।
    """
    if not CHANNEL:
        print("⚠️ STORE_CHANNEL_ID config.py में सेट नहीं है!")
        return None

    try:
        title = story_data.get('title', 'New Story')
        price = story_data.get('price', 0)
        desc = story_data.get('desc', 'No Description Available.')
        photo = story_data.get('photo', None)

        clean_title = title.strip().split("\n")[0].replace(" ", "_")
        clean_title = re.sub(r'[^\w\s_]', '', clean_title)

        # 1. Mini App & Direct Bot Start Deep Links
        miniapp_url = f"{WEB_APP_URL}?startapp=story_{clean_title}" if WEB_APP_URL else f"https://t.me/{BOT_USERNAME}/app?startapp=story_{clean_title}"
        bot_direct_url = f"https://t.me/{BOT_USERNAME}?start=story_{clean_title}"

        # 2. Premium Buttons Layout
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🛒 ʙᴜʏ ɴᴏᴡ", url=miniapp_url),
                InlineKeyboardButton("📖 ᴛᴜᴛᴏʀɪᴀʟ", url=TUTORIAL_VIDEO_URL)
            ],
            [
                InlineKeyboardButton("⚡ ᴅɪʀᴇᴄᴛ ʙᴏᴛ ᴏʀᴅᴇʀ", url=bot_direct_url)
            ]
        ])

        # 3. Post Caption Text Format
        post_caption = (
            f"🔥 <b>ɴᴇᴡ sᴛᴏʀʏ ᴀʟᴇʀᴛ!</b> 🔥\n\n"
            f"📖 <b>ᴛɪᴛʟᴇ:</b> {title}\n"
            f"💰 <b>ᴘʀɪᴄᴇ:</b> ₹{price}\n\n"
            f"📝 <b>ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:</b>\n{desc}\n\n"
            f"👇 <i>नीचे दिए गए बटन पर क्लिक करके स्टोरी अनलॉक करें:</i>"
        )

        # 4. Post to Channel
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
        print(f"❌ Error Auto-Posting to Channel: {e}")
        return None
