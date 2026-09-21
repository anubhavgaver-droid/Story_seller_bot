import re
from pyrogram import Client, enums 
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_USERNAME, CHANNEL, TUTORIAL_VIDEO_URL, POCKET_FM_CHANNEL, PRATILIPI_FM_CHANNEL


async def send_story_to_channel(client: Client, story_data: dict):
    """
    जब भी /addstory विजार्ड से स्टोरी सेव होगी,
    यह फ़ंक्शन category/platform चेक करके सही चैनल (Pocket FM या Pratilipi FM) पर
    Buy Now, Free Link (if available), Tutorial और Direct Bot Order बटन के साथ पोस्ट भेजेगा।
    """
    try:
        # ---------------- 1. Category/Platform-wise Channel Selector ----------------
        platform_name = str(story_data.get('platform') or story_data.get('category') or "").lower().strip()

        if "pocket" in platform_name:
            target_channel = POCKET_FM_CHANNEL
        elif "pratilipi" in platform_name:
            target_channel = PRATILIPI_FM_CHANNEL
        else:
            # Fallback Channel ID if no match found
            target_channel = CHANNEL

        if not target_channel:
            print("⚠️ Target Channel ID config.py में सेट नहीं है!")
            return None

        # ---------------- 2. Story Data Extraction ----------------
        title = story_data.get('title', 'New Story')
        price = story_data.get('price', 0)
        photo = story_data.get('photo', None)
        
        status = story_data.get('status', 'Completed')
        platform_display = story_data.get('platform') or story_data.get('category') or 'Pocket FM'
        genre = story_data.get('genre', 'Drama')
        episodes = story_data.get('episodes', 'N/A')
        free_link = story_data.get('free_link', None)

        clean_title = title.strip().split("\n")[0]
        encoded_title = clean_title.replace(" ", "_")

        # ---------------- 3. Link & Buttons Setup ----------------
        miniapp_url = f"https://t.me/{BOT_USERNAME}/Store?startapp=story_{encoded_title}"
        bot_direct_url = f"https://t.me/{BOT_USERNAME}?start=story_{encoded_title}"

        button_rows = [
            [
                InlineKeyboardButton("🛒 ʙᴜʏ ɴᴏᴡ", style=enums.ButtonStyle.PRIMARY, url=miniapp_url),
                InlineKeyboardButton("📖 ᴛᴜᴛᴏʀɪᴀʟ", style=enums.ButtonStyle.PRIMARY, url=TUTORIAL_VIDEO_URL)
            ]
        ]

        # अगर Admin ने Free Link दिया है तो "Only for free user" का बटन ऐड होगा
        if free_link and (free_link.startswith("http://") or free_link.startswith("https://")):
            button_rows.append([
                InlineKeyboardButton("🎁 ᴏɴʟʏ ғᴏʀ ғʀᴇᴇ ᴜsᴇʀ", style=enums.ButtonStyle.PRIMARY, url=free_link)
            ])

        # Direct Bot Order Button
        button_rows.append([
            InlineKeyboardButton("⚡ ᴅɪʀᴇᴄᴛ ʙᴏᴛ ᴏʀᴅᴇʀ", style=enums.ButtonStyle.PRIMARY, url=bot_direct_url)
        ])

        buttons = InlineKeyboardMarkup(button_rows)

        # ---------------- 4. Post Caption Layout ----------------
        post_caption = (
            f"♨️ <b>Story :</b> {clean_title}\n"
            f"🔰 <b>Status :</b> {status}\n"
            f"🖥️ <b>Platform :</b> {platform_display}\n"
            f"🧩 <b>Genre :</b> {genre}\n"
            f"🎬 <b>Episodes :</b> {episodes}\n\n"
            f"░▒▓█ PRICE - ₹{price} █▓▒░\n\n"
            f"👇 <i>नीचे दिए गए बटन पर क्लिक करके स्टोरी अनलॉक करें:</i>"
        )

        # ---------------- 5. Send Post to Dynamic Target Channel ----------------
        if photo:
            sent_msg = await client.send_photo(
                chat_id=target_channel,
                photo=photo,
                caption=post_caption,
                reply_markup=buttons
            )
        else:
            sent_msg = await client.send_message(
                chat_id=target_channel,
                text=post_caption,
                reply_markup=buttons
            )

        print(f"✅ Post successfully sent to Channel ID: {target_channel} ({platform_display})")
        return sent_msg

    except Exception as e:
        print(f"❌ Channel Post Error: {e}")
        return None
