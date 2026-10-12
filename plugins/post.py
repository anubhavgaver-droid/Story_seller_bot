import re
import asyncio
from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, ForceReply

# Config file imports
from config import (
    BOT_USERNAME, 
    CHANNEL, 
    TUTORIAL_VIDEO_URL, 
    POCKET_FM_CHANNEL, 
    PRATILIPI_FM_CHANNEL,
    ADMIN_ID
)

# Database helper function imports
from db import get_all_stories, get_story_by_title

# State Trackers for Repost Wizards
REPOST_CANCEL_STATE = {}
SINGLE_REPOST_STATE = {}


# ---------------- 1. SINGLE STORY POST FUNCTION ----------------
async def send_story_to_channel(client: Client, story_data: dict, delay_seconds: int = 0):
    """
    जब भी /addstory से नई स्टोरी सेव होगी या रीपोस्ट होगी,
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


# ---------------- 2. ADMIN REPOST CANCEL COMMAND ----------------
@Client.on_message(filters.command("cancel") & filters.user(ADMIN_ID) & filters.private, group=2)
async def cancel_repost_command(client: Client, message: Message):
    user_id = message.from_user.id
    if REPOST_CANCEL_STATE.get(user_id) or user_id in SINGLE_REPOST_STATE:
        REPOST_CANCEL_STATE[user_id] = False
        SINGLE_REPOST_STATE.pop(user_id, None)
        await message.reply_text("🛑 <b>प्रोसेस को रद्द (Cancel) कर दिया गया है!</b>")
    else:
        message.continue_propagation()


# ---------------- 3. NEW FEATURE: REPOST SINGLE STORY COMMAND ----------------
@Client.on_message(filters.command("repoststory") & filters.user(ADMIN_ID) & filters.private)
async def start_repost_single_story(client: Client, message: Message):
    """
    किसी एक पर्टिकुलर स्टोरी को दोबारा चैनल पर रीपोस्ट करने के लिए कमांड।
    """
    user_id = message.from_user.id
    SINGLE_REPOST_STATE[user_id] = True
    await message.reply_text(
        "📢 <b>ʀᴇᴘᴏsᴛ sɪɴɢʟᴇ sᴛᴏʀʏ WIZARD:</b>\n\n"
        "जिस स्टोरी को आप दोबारा रीपोस्ट करना चाहते हैं, उसका <b>Exact Title (सही नाम)</b> दर्ज करें:\n"
        "<i>(रद्द करने के लिए /cancel टाइप करें)</i>",
        reply_markup=ForceReply(True)
    )


# ---------------- 4. ADMIN AUTO-REPOST ALL COMMAND ----------------
@Client.on_message(filters.command("repost") & filters.user(ADMIN_ID))
async def handle_repost_command(client: Client, message: Message):
    user_id = message.from_user.id
    REPOST_CANCEL_STATE[user_id] = True

    status_msg = await message.reply_text("🔎 डेटाबेस से सभी स्टोरीज़ फ़ैच की जा रही हैं...")
    
    all_stories = await get_all_stories()
    
    if not all_stories:
        REPOST_CANCEL_STATE.pop(user_id, None)
        await status_msg.edit_text("❌ डेटाबेस में कोई स्टोरीज़ नहीं मिलीं!")
        return

    total_stories = len(all_stories)
    await status_msg.edit_text(
        f"🔄 कुल **{total_stories}** स्टोरीज़ मिलीं। रीपोस्टिंग शुरू हो रही है...\n"
        f"⏱️ हर पोस्ट के बीच **3 मिनट (180s)** का गैप रहेगा।\n\n"
        f"<i>(रोकने के लिए /cancel टाइप करें)</i>"
    )

    for index, story in enumerate(all_stories, start=1):
        if not REPOST_CANCEL_STATE.get(user_id, True):
            REPOST_CANCEL_STATE.pop(user_id, None)
            await status_msg.edit_text(
                f"🛑 <b>रीपोस्टिंग रोक दी गई!</b>\n"
                f"📊 `{index - 1}/{total_stories}` स्टोरीज़ पोस्ट होने के बाद प्रोसेस कैंसिल हुआ।"
            )
            return

        try:
            print(f"[{index}/{total_stories}] Reposting: {story.get('title')}")
            await send_story_to_channel(client, story)
            
            if index % 3 == 0 or index == total_stories:
                await status_msg.edit_text(
                    f"📊 **रीपोस्टिंग प्रोग्रेस:** `{index}/{total_stories}` स्टोरीज़ पोस्ट हो चुकी हैं..."
                )

            if index < total_stories:
                for _ in range(180):
                    if not REPOST_CANCEL_STATE.get(user_id, True):
                        break
                    await asyncio.sleep(1)

        except Exception as e:
            print(f"❌ Error reposting story {story.get('title')}: {e}")
            await asyncio.sleep(10)

    REPOST_CANCEL_STATE.pop(user_id, None)
    await status_msg.edit_text(
        f"🎉 **रीपोस्टिंग पूर्ण हुई!**\nसभी **{total_stories}** स्टोरीज़ नए बोट यूज़रनेम के साथ चैनल पर पोस्ट हो चुकी हैं।"
    )


# ---------------- 5. MASTER INPUT LISTENER FOR SINGLE REPOST ----------------
@Client.on_message(filters.private & filters.user(ADMIN_ID) & ~filters.command(["start", "repost", "repoststory", "cancel"]), group=2)
async def single_repost_input_handler(client: Client, message: Message):
    user_id = message.from_user.id

    if user_id in SINGLE_REPOST_STATE:
        story_title = message.text.strip().split("\n")[0]
        SINGLE_REPOST_STATE.pop(user_id, None)

        status_msg = await message.reply_text(f"🔍 <b>'{story_title}'</b> को डेटाबेस में खोजा जा रहा है...")

        # डेटाबेस से टाइटल के आधार पर स्टोरी ढूंढें
        story = await get_story_by_title(story_title)

        if not story:
            return await status_msg.edit_text(
                f"❌ <b>'{story_title}' नाम से कोई स्टोरी नहीं मिली!</b>\n"
                f"कृपया सही नाम के साथ दोबारा `/repoststory` कमांड चलाएं।"
            )

        # स्टोरी मिल गई, अब चैनल पर भेजें
        await status_msg.edit_text(f"📤 <b>'{story.get('title')}'</b> को चैनल पर रीपोस्ट किया जा रहा है...")
        
        sent = await send_story_to_channel(client, story)

        if sent:
            await status_msg.edit_text(
                f"✅ <b>सफलतापूर्वक रीपोस्ट हो गया!</b>\n\n"
                f"📖 <b>Story:</b> {story.get('title')}\n"
                f"🖥️ <b>Platform:</b> {story.get('platform') or story.get('category')}\n"
                f"<i>नए बोट लिंक के साथ पोस्ट चैनल पर भेज दी गई है।</i>"
            )
        else:
            await status_msg.edit_text("❌ पोस्ट भेजने में कोई एरर आ गई है। कृपया कंसोल (Logs) चेक करें।")
        return

    message.continue_propagation()
