import re
import asyncio
from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from config import (
    BOT_USERNAME, 
    CHANNEL, 
    TUTORIAL_VIDEO_URL, 
    POCKET_FM_CHANNEL, 
    PRATILIPI_FM_CHANNEL,
    ADMIN_ID
)
from database.db import get_all_stories


# ---------------- 1. SINGLE STORY POST FUNCTION ----------------
async def send_story_to_channel(client: Client, story_data: dict, delay_seconds: int = 0):
    """
    जब भी /addstory से नई स्टोरी सेव होगी या ऑटो-रीपोस्ट होगी,
    यह फ़ंक्शन सही प्लेटफॉर्म चैनल (Pocket FM / Pratilipi FM) पर
    Buy Now, Free Link, Tutorial और Direct Bot Order बटन के साथ पोस्ट भेजेगा।
    """
    try:
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

        # dynamic Bot Username: config से लें या कनेक्टेड बोट से फ़ैच करें
        bot_username = BOT_USERNAME
        if not bot_username or bot_username == "YOUR_BOT_USERNAME":
            me = await client.get_me()
            bot_username = me.username

        # Target Channel Selector
        platform_name = str(story_data.get('platform') or story_data.get('category') or "").lower().strip()

        if "pocket" in platform_name:
            target_channel = POCKET_FM_CHANNEL
        elif "pratilipi" in platform_name:
            target_channel = PRATILIPI_FM_CHANNEL
        else:
            target_channel = CHANNEL

        if not target_channel:
            print("⚠️ Target Channel ID config.py में सेट नहीं है!")
            return None

        # Story Data Extraction
        title = story_data.get('title', 'New Story')
        price = story_data.get('price', 0)
        photo = story_data.get('photo', None)
        
        status = story_data.get('status', 'Completed')
        platform_display = story_data.get('platform') or story_data.get('category') or 'Pocket FM'
        genre = story_data.get('genre', 'Drama')
        episodes = story_data.get('episodes', 'N/A')
        free_link = story_data.get('free_link', None)

        clean_title = title.strip().split("\n")[0]
        
        # Unique Link Parameter setup
        story_param = story_data.get('story_param') or f"story_{clean_title.replace(' ', '_')}"

        # Link & Buttons Setup (Uses Active Bot Username)
        miniapp_url = f"https://t.me/{bot_username}/Store?startapp={story_param}"
        bot_direct_url = f"https://t.me/{bot_username}?start={story_param}"

        button_rows = [
            [
                InlineKeyboardButton("🛒 ʙᴜʏ ɴᴏᴡ", style=enums.ButtonStyle.PRIMARY, url=miniapp_url),
                InlineKeyboardButton("📖 ᴛᴜᴛᴏʀɪᴀʟ", style=enums.ButtonStyle.PRIMARY, url=TUTORIAL_VIDEO_URL)
            ]
        ]

        if free_link and (str(free_link).startswith("http://") or str(free_link).startswith("https://")):
            button_rows.append([
                InlineKeyboardButton("🎁 ᴏɴʟʏ ғᴏʀ ғʀᴇᴇ ᴜsᴇʀ", style=enums.ButtonStyle.PRIMARY, url=free_link)
            ])

        button_rows.append([
            InlineKeyboardButton("⚡ ᴅɪʀᴇᴄᴛ ʙᴏᴛ ᴏʀᴅᴇʀ", style=enums.ButtonStyle.PRIMARY, url=bot_direct_url)
        ])

        buttons = InlineKeyboardMarkup(button_rows)

        # Caption Layout
        post_caption = (
            f"♨️ <b>Story :</b> {clean_title}\n"
            f"🔰 <b>Status :</b> {status}\n"
            f"🖥️ <b>Platform :</b> {platform_display}\n"
            f"🧩 <b>Genre :</b> {genre}\n"
            f"🎬 <b>Episodes :</b> {episodes}\n\n"
            f"░▒▓█ PRICE - ₹{price} █▓▒░\n\n"
            f"👇 <i>नीचे दिए गए बटन पर क्लिक करके स्टोरी अनलॉक करें:</i>"
        )

        # Send Message / Photo
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

        print(f"✅ Post successfully sent for [{clean_title}] to Channel: {target_channel}")
        return sent_msg

    except Exception as e:
        print(f"❌ Channel Post Error for [{story_data.get('title')}]: {e}")
        return None


# ---------------- 2. ADMIN AUTO-REPOST HANDLER COMMAND ----------------
@Client.on_message(filters.command("repost") & filters.user(ADMIN_ID))
async def handle_repost_command(client: Client, message: Message):
    """
    जब नया बोट टोकन सेट करें, तो एडमिन बोट को /repost कमांड देगा।
    बोट DB से सभी स्टोरीज़ निकाल कर 3 मिनट के टाइम-गैप (180s) में
    नए बोट लिंक्स के साथ ऑटो-रीपोस्ट करेगा।
    """
    status_msg = await message.reply_text("🔎 डेटाबेस से सभी स्टोरीज़ फ़ैच की जा रही हैं...")
    
    # 1. डेटाबेस से सभी स्टोरीज़ निकालें
    all_stories = await get_all_stories()
    
    if not all_stories:
        await status_msg.edit_text("❌ डेटाबेस में कोई स्टोरीज़ नहीं मिलीं!")
        return

    total_stories = len(all_stories)
    await status_msg.edit_text(
        f"🔄 कुल **{total_stories}** स्टोरीज़ मिलीं। रीपोस्टिंग शुरू हो रही है...\n"
        f"⏱️ स्पैम/बैन सुरक्षा के लिए हर पोस्ट के बीच **3 मिनट (180s)** का गैप रहेगा।"
    )

    # 2. Sequential Loop with Sleep Delay
    for index, story in enumerate(all_stories, start=1):
        try:
            print(f"[{index}/{total_stories}] Reposting: {story.get('title')}")
            
            # नई लिंक के साथ चैनल पर पोस्ट भेजें
            await send_story_to_channel(client, story)
            
            # हर 3 पोस्ट बाद या आखिरी पोस्ट पर स्टेटस मैसेज अपडेट करें
            if index % 3 == 0 or index == total_stories:
                await status_msg.edit_text(
                    f"📊 **रीपोस्टिंग प्रोग्रेस:** `{index}/{total_stories}` स्टोरीज़ पोस्ट हो चुकी हैं..."
                )

            # आखिरी पोस्ट के बाद डिले न लगाएं
            if index < total_stories:
                await asyncio.sleep(180)  # 3 मिनट (180 सेकंड) का डिले

        except Exception as e:
            print(f"❌ Error reposting story {story.get('title')}: {e}")
            await asyncio.sleep(10)  # एरर आने पर 10 सेकंड रुक कर आगे बढ़ें

    await status_msg.edit_text(
        f"🎉 **रीपोस्टिंग पूर्ण हुई!**\nसभी **{total_stories}** स्टोरीज़ नए बोट यूज़रनेम के साथ चैनल पर सफलतापूर्वक पोस्ट हो चुकी हैं।"
    )
