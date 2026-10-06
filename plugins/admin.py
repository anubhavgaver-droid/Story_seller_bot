import re
import random
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from config import ADMIN_ID, BOT_USERNAME, WEB_APP_URL, CHANNEL_ID
from database.db import (
    add_story_db, 
    delete_story_db, 
    get_all_stories, 
    send_log,
    add_wallet_balance,
    stories_col,
    users_col
)
from plugins.post import send_story_to_channel
from plugins.notification import notify_story_buyers

# State Trackers
ADD_STATE = {}
DELETE_STATE = {}
UPDATE_STATE = {}
ONGOING_STATE = {}
COMPLETE_STATE = {}
EDIT_NAME_STATE = {}
EDIT_EPISODES_STATE = {}
CHANGE_STATUS_STATE = {}

def extract_msg_id(text: str):
    """Link या Message ID में से Numeric Message ID निकालने का Helper फ़ंक्शन"""
    if not text:
        return None
    text = str(text).strip()
    if text.isdigit():
        return int(text)
    match = re.search(r"/(\d+)$", text)
    return int(match.group(1)) if match else None

# ------------------ ADMIN REFRESH COMMAND FOR ALL STORIES ------------------
@Client.on_message(filters.command("refreshstories") & filters.user(ADMIN_ID) & filters.private, group=1)
async def refresh_all_stories(client, message):
    status_msg = await message.reply_text("🔄 <b>Processing all stories in database... Please wait.</b>")
    
    updated_count = 0
    total_stories = 0

    try:
        async for story in stories_col.find():
            total_stories += 1
            first_id = story.get("first_msg_id")
            last_id = story.get("last_msg_id")
            
            update_data = {}
            
            # Total Files Calculation
            if first_id and last_id and last_id >= first_id:
                calc_files = (last_id - first_id) + 1
                update_data["total_files"] = f"{calc_files} files"
            elif not story.get("total_files"):
                update_data["total_files"] = "24 files"
            
            # Episodes fix
            if not story.get("episodes"):
                update_data["episodes"] = "30 Episodes"
                
            # Demo Sync Setup
            if "demo_enabled" not in story:
                update_data["demo_enabled"] = False
            if "demo_msg_ids" not in story:
                update_data["demo_msg_ids"] = []

            # Update DB
            if update_data:
                await stories_col.update_one(
                    {"_id": story["_id"]}, 
                    {"$set": update_data}
                )
                updated_count += 1

        await status_msg.edit_text(
            f"✅ <b>Refresh Completed Successfully!</b>\n\n"
            f"📊 <b>Total Stories Checked:</b> {total_stories}\n"
            f"🛠 <b>Fixed/Updated:</b> {updated_count}\n\n"
            f"<i>Ab Mini App aur Bot dono me sabhi stories ka data fix aur sync ho gaya hai.</i>"
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ <b>Error occurred:</b> `{str(e)}`")

# ------------------ ADMIN ADD MONEY TO USER WALLET ------------------
@Client.on_message(filters.command("addmoney") & filters.user(ADMIN_ID) & filters.private, group=1)
async def add_money_handler(client, message):
    args = message.text.split()
    
    if len(args) < 3:
        usage_text = (
            "⚠ <b>ɪɴᴠᴀʟɪᴅ ᴄᴏᴍᴍᴀɴᴅ ғᴏʀᴍᴀᴛ!</b>\n\n"
            "<b>ᴜsᴀɢᴇ:</b>\n"
            "<code>/addmoney <user_id> <amount></code>\n\n"
            "<b>ᴇxᴀᴍᴘʟᴇs:</b>\n"
            "• <code>/addmoney 123456789 100</code> (Adds ₹100)\n"
            "• <code>/addmoney 123456789 -50</code> (Deducts ₹50)"
        )
        return await message.reply_text(usage_text)

    try:
        target_user_id = int(args[1])
        amount = float(args[2])
    except ValueError:
        return await message.reply_text("❌ <b>Invalid User ID or Amount! Numbers only enter karein.</b>")

    new_balance = await add_wallet_balance(target_user_id, amount)

    success_msg = (
        f"✅ <b>ᴡᴀʟʟᴇᴛ ᴜᴘᴅᴀᴛᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
        f"👤 <b>ᴜsᴇʀ ɪᴅ:</b> <code>{target_user_id}</code>\n"
        f"💰 <b>ᴀᴅᴅᴇᴅ/ᴅᴇᴅᴜᴄᴛᴇᴅ:</b> ₹{amount}\n"
        f"👛 <b>ɴᴇᴡ Total ʙᴀʟᴀɴᴄᴇ:</b> ₹{new_balance}"
    )
    await message.reply_text(success_msg)

    user_notify_text = (
        f"🎉 <b>ᴡᴀʟʟᴇᴛ ᴄʀᴇᴅɪᴛᴇᴅ!</b>\n\n"
        f"💰 <b>ᴀᴍᴏᴜɴᴛ ᴀᴅᴅᴇᴅ:</b> ₹{amount}\n"
        f"👛 <b>Total ʙᴀʟᴀɴᴄᴇ:</b> ₹{new_balance}\n\n"
        f"<i>Now you can buy any story using your wallet in Mini App or Bot!</i>"
    )
    try:
        await client.send_message(chat_id=target_user_id, text=user_notify_text)
    except Exception as e:
        await message.reply_text(f"⚠️ Balance update ho gaya, lekin User ko message delivery fail ho gayi: {e}")

    log_text = (
        f"<b>💼 ᴀᴅᴍɪɴ ᴡᴀʟʟᴇᴛ ᴛᴏᴘ-ᴜᴘ</b>\n\n"
        f"👤 <b>Target User ID:</b> <code>{target_user_id}</code>\n"
        f"💸 <b>Amount:</b> ₹{amount}\n"
        f"👛 <b>Updated Total:</b> ₹{new_balance}"
    )
    try:
        await send_log(client, log_text)
    except Exception:
        pass

# 1. Cancel Command
@Client.on_message(filters.command("cancel") & filters.user(ADMIN_ID) & filters.private, group=1)
async def cancel_action(client, message):
    user_id = message.from_user.id
    states = [ADD_STATE, DELETE_STATE, UPDATE_STATE, ONGOING_STATE, COMPLETE_STATE, EDIT_NAME_STATE, EDIT_EPISODES_STATE, CHANGE_STATUS_STATE]
    if any(user_id in state for state in states):
        for st in states:
            st.pop(user_id, None)
        await message.reply_text("❌ <b>ᴘʀᴏᴄᴇss ᴄᴀɴᴄᴇʟʟᴇᴅ!</b>")
    else:
        await message.reply_text("❓ ʏᴏᴜ ʜᴀᴠᴇ ɴᴏ ᴀᴄᴛɪᴠᴇ ᴘʀᴏᴄᴇss.")

# 2. View All Stories List
@Client.on_message(filters.command("allstories") & filters.user(ADMIN_ID) & filters.private, group=1)
async def list_stories(client, message):
    stories = await get_all_stories()
    if not stories:
        return await message.reply_text("📂 <b>ɴᴏ sᴛᴏʀɪᴇs ғᴏᴜɴᴅ ɪɴ ᴛʜᴇ ᴅᴀᴛᴀʙᴀsᴇ.</b>")
        
    text = "<b>📚 sᴀᴠᴇᴅ sᴛᴏʀɪᴇs ʟɪsᴛ:</b>\n\n"
    for idx, s in enumerate(stories, start=1):
        clean_title = s['title'].strip().split("\n")[0].replace(" ", "_")
        bot_link = f"https://t.me/{BOT_USERNAME}?start=story_{clean_title}"
        f_id = s.get('first_msg_id', 'N/A')
        l_id = s.get('last_msg_id', 'N/A')
        episodes = s.get('episodes', 'N/A')
        status = s.get('status', 'Completed')
        genre = s.get('genre', 'Drama')
        free_link = s.get('free_link', 'None')
        demo_status = "✅ Enabled" if s.get('demo_enabled', False) else "❌ Disabled"
        demo_files = s.get('demo_msg_ids', [])
        ranges_count = len(s.get('custom_ranges', []))
        
        text += (
            f"{idx}. <b>{s['title']}</b> | ₹{s['price']} | <i>{s['category']}</i>\n"
            f"   🔰 <b>Status:</b> {status} | 🧩 <b>Genre:</b> {genre}\n"
            f"   🎬 <b>Episodes:</b> {episodes}\n"
            f"   🔗 <b>Free Link:</b> {free_link}\n"
            f"   📦 <b>Batch Range:</b> Message {f_id} to {l_id}\n"
            f"   🎯 <b>Custom Buttons:</b> {ranges_count} Ranges Configured\n"
            f"   🎧 <b>Demo Status:</b> {demo_status} (IDs: {demo_files})\n"
            f"   🔗 <b>sʜᴀʀᴇ ʟɪɴᴋ:</b> <code>{bot_link}</code>\n\n"
        )
    
    if len(text) > 4000:
        for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
            await message.reply_text(chunk, disable_web_page_preview=True)
    else:
        await message.reply_text(text, disable_web_page_preview=True)

# ------------------ NEW FEATURE 1: EDIT STORY NAME ------------------
@Client.on_message(filters.command("editname") & filters.user(ADMIN_ID) & filters.private, group=1)
async def start_edit_name(client, message):
    EDIT_NAME_STATE[message.from_user.id] = {'step': 'OLD_NAME'}
    await message.reply_text(
        "✏️ <b>ᴇᴅɪᴛ sᴛᴏʀʏ ɴᴀᴍᴇ WIZARD:</b>\n\n"
        "जिस स्टोरी का नाम बदलना है, उसका <b>पुराना (Old) Title</b> दर्ज करें:\n"
        "<i>(टाइप करें /cancel रद्द करने के लिए)</i>",
        reply_markup=ForceReply(True)
    )

# ------------------ NEW FEATURE 2: CHANGE EPISODES / RANGES ------------------
@Client.on_message(filters.command("setepisodes") & filters.user(ADMIN_ID) & filters.private, group=1)
async def start_edit_episodes(client, message):
    EDIT_EPISODES_STATE[message.from_user.id] = {'step': 'STORY_NAME'}
    await message.reply_text(
        "🎬 <b>ᴇᴅɪᴛ sᴛᴏʀʏ ᴇᴘɪsᴏᴅᴇs WIZARD:</b>\n\n"
        "जिस स्टोरी का एपिसोड काउंट/टेक्स्ट अलग से बदलना है, उसका <b>Exact Title</b> दर्ज करें:\n"
        "<i>(टाइप करें /cancel रद्द करने के लिए)</i>",
        reply_markup=ForceReply(True)
    )

# ------------------ NEW FEATURE 3: SWITCH STATUS (Ongoing / Completed) ------------------
@Client.on_message(filters.command("changestatus") & filters.user(ADMIN_ID) & filters.private, group=1)
async def start_change_status(client, message):
    CHANGE_STATUS_STATE[message.from_user.id] = {'step': 'STORY_NAME'}
    await message.reply_text(
        "🔄 <b>ᴄʜᴀɴɢᴇ sᴛᴏʀʏ sᴛᴀᴛᴜs WIZARD:</b>\n\n"
        "जिस स्टोरी का स्टेटस बदलना (Ongoing ↔ Completed) है, उसका <b>Exact Title</b> दर्ज करें:\n"
        "<i>(टाइप करें /cancel रद्द करने के लिए)</i>",
        reply_markup=ForceReply(True)
    )

@Client.on_callback_query(filters.regex("^setstatus_") & filters.user(ADMIN_ID))
async def status_selected_callback(client, callback):
    user_id = callback.from_user.id
    if user_id not in CHANGE_STATUS_STATE:
        return await callback.answer("Session Expired!", show_alert=True)

    new_status = callback.data.split("setstatus_")[1]
    story_id = CHANGE_STATUS_STATE[user_id]['story_id']
    title = CHANGE_STATUS_STATE[user_id]['title']

    await stories_col.update_one({"_id": story_id}, {"$set": {"status": new_status}})
    CHANGE_STATUS_STATE.pop(user_id, None)

    await callback.message.reply_text(
        f"✅ <b>sᴛᴀᴛᴜs ᴜᴘᴅᴀᴛᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
        f"📖 <b>Story:</b> {title}\n"
        f"🔰 <b>New Status:</b> <code>{new_status}</code>\n\n"
        f"<i>Mini App और Bot दोनों में स्टेटस अपडेट हो गया है।</i>"
    )
    await callback.answer()

# 3. Delete Story Command Start
@Client.on_message(filters.command("deletestory") & filters.user(ADMIN_ID) & filters.private, group=1)
async def start_delete(client, message):
    user_id = message.from_user.id
    DELETE_STATE[user_id] = True
    await message.reply_text(
        "🗑️️ <b>ᴅᴇʟᴇᴛᴇ sᴛᴏʀɪᴇs ᴡɪᴢᴀʀᴅ:</b>\n\n"
        "ᴇɴᴛᴇʀ ᴛʜᴇ <b>ᴇxᴀᴄᴛ ᴛɪᴛʟᴇ</b> ᴏғ ᴛʜᴇ sᴛᴏʀʏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴅᴇʟᴇᴛᴇ:\n"
        "<i>(ᴛʏᴘᴇ /cancel ᴛᴏ ᴀʙᴏʀᴛ)</i>",
        reply_markup=ForceReply(True)
    )

# 4. Add Story Command Start
@Client.on_message(filters.command("addstory") & filters.user(ADMIN_ID) & filters.private, group=1)
async def start_add(client, message):
    ADD_STATE[message.from_user.id] = {}
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📻 Pocket FM", callback_data="setcat_Pocket FM")],
        [InlineKeyboardButton("📚 Pratilipi FM", callback_data="setcat_Pratilipi FM")],
        [InlineKeyboardButton("🎧 Kuku FM", callback_data="setcat_Kuku FM")]
    ])
    await message.reply_text("<b>[sᴛᴇᴘ 1/10]</b> sᴇʟᴇᴄᴛ ᴛʜᴇ sᴛᴏʀʏ ᴄᴀᴛᴇɢᴏʀʏ:\n<i>(ᴛʏᴘᴇ /cancel ᴛᴏ ᴀʙᴏʀᴛ)</i>", reply_markup=kb)

# 5. Category Selection Callback
@Client.on_callback_query(filters.regex("^setcat_") & filters.user(ADMIN_ID))
async def cat_selected(client, callback):
    user_id = callback.from_user.id
    if user_id not in ADD_STATE:
        return await callback.answer("Session expired! Please start with /addstory", show_alert=True)
        
    category_val = callback.data.split("setcat_")[1]
    ADD_STATE[user_id]['category'] = category_val
    ADD_STATE[user_id]['platform'] = category_val
    
    genre_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎭 Drama", callback_data="setgenre_Drama"), InlineKeyboardButton("💖 Romance", callback_data="setgenre_Romance")],
        [InlineKeyboardButton("⚡ Action", callback_data="setgenre_Action"), InlineKeyboardButton("🔍 Thriller", callback_data="setgenre_Thriller")],
        [InlineKeyboardButton("👻 Horror", callback_data="setgenre_Horror"), InlineKeyboardButton("🔮 Fantasy", callback_data="setgenre_Fantasy")]
    ])
    
    await callback.message.reply_text("<b>[sᴛᴇᴘ 2/10]</b> 🧩 <b>sᴇʟᴇᴄᴛ sᴛᴏʀʏ ɢᴇɴʀᴇ:</b>", reply_markup=genre_kb)
    await callback.answer()

# 5.1 Genre Selection Callback
@Client.on_callback_query(filters.regex("^setgenre_") & filters.user(ADMIN_ID))
async def genre_selected(client, callback):
    user_id = callback.from_user.id
    if user_id not in ADD_STATE:
        return await callback.answer("Session expired!", show_alert=True)

    genre_val = callback.data.split("setgenre_")[1]
    ADD_STATE[user_id]['genre'] = genre_val
    ADD_STATE[user_id]['step'] = 'TITLE'
    await callback.message.reply_text("<b>[sᴛᴇᴘ 3/10]</b> 📖 ᴇɴᴛᴇʀ ᴛʜᴇ sᴛᴏʀʏ ᴛɪᴛʟᴇ:", reply_markup=ForceReply(True))
    await callback.answer()

# 5.2 Skip Free Link Callback
@Client.on_callback_query(filters.regex("^skip_free_link$") & filters.user(ADMIN_ID))
async def skip_free_link_handler(client, callback):
    user_id = callback.from_user.id
    if user_id in ADD_STATE and ADD_STATE[user_id].get("step") == "FREE_LINK":
        ADD_STATE[user_id]["free_link"] = None
        ADD_STATE[user_id]["step"] = "ASK_DEMO"
        
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Yes (Enable Demo)", callback_data="setdemo_yes"),
                InlineKeyboardButton("❌ No (Disable Demo)", callback_data="setdemo_no")
            ]
        ])
        await callback.message.reply_text(
            "⏩ <b>Free Link Skipped!</b>\n\n"
            "<b>[sᴛᴇᴘ 9/10]</b> क्या आप इस स्टोरी के लिए <b>🎬 View Demo</b> चालू रखना चाहते हैं?", 
            reply_markup=kb
        )
    await callback.answer()

# 6. Demo Option Selection Callback (Yes / No)
@Client.on_callback_query(filters.regex("^setdemo_") & filters.user(ADMIN_ID))
async def demo_option_selected(client, callback):
    user_id = callback.from_user.id
    if user_id not in ADD_STATE:
        return await callback.answer("Session expired!", show_alert=True)

    choice = callback.data.split("setdemo_")[1]
    ADD_STATE[user_id]['demo_enabled'] = (choice == "yes")
        
    ADD_STATE[user_id]['step'] = 'FIRST_MSG'
    await callback.message.reply_text("<b>[sᴛᴇᴘ 9/10]</b> DB Channel से स्टोरी की <b>FIRST Message ID / Link</b> भेजें:", reply_markup=ForceReply(True))
    await callback.answer()

# 6.1 Range Selection Callbacks
@Client.on_callback_query(filters.regex("^(setrange_|add_more_range|finish_ranges)") & filters.user(ADMIN_ID))
async def range_callbacks(client, callback):
    user_id = callback.from_user.id
    data = callback.data

    if user_id not in ADD_STATE:
        return await callback.answer("Session Expired!", show_alert=True)

    if data in ["setrange_yes", "add_more_range"]:
        ADD_STATE[user_id]['step'] = 'RANGE_NAME'
        await callback.message.reply_text(
            "✏ <b>Button Name दर्ज करें:</b>\n"
            "<i>(उदाहरण: Ep 1 to 50, Part 1, या Episode 51-100)</i>",
            reply_markup=ForceReply(True)
        )
        await callback.answer()

    elif data in ["setrange_no", "finish_ranges"]:
        story_data = ADD_STATE[user_id]
        ADD_STATE.pop(user_id, None)
        await finalize_add_story(client, callback.message, story_data)
        await callback.answer()

# Helper Function: Finalize & Save Story to Database
async def finalize_add_story(client, message, data):
    first = data['first_msg_id']
    last = data['last_msg_id']
    demo_msg_ids = []

    if data.get('demo_enabled', False):
        middle_range = list(range(first + 1, last))
        if len(middle_range) >= 2:
            demo_msg_ids = random.sample(middle_range, 2)
        elif len(middle_range) == 1:
            demo_msg_ids = middle_range
        else:
            demo_msg_ids = [first, last]
            
    data['demo_enabled'] = data.get('demo_enabled', False)
    data['demo_msg_ids'] = demo_msg_ids

    clean_title = data['title'].strip().split("\n")[0].replace(" ", "_")
    data['link'] = f"https://t.me/{BOT_USERNAME}?start=get_{clean_title}"

    await add_story_db(data)
    
    try:
        await send_story_to_channel(client, data)
    except Exception as e:
        print(f"⚠ Auto post failed: {e}")

    bot_share_link = f"https://t.me/{BOT_USERNAME}?start=story_{clean_title}"
    total_files = data['last_msg_id'] - data['first_msg_id'] + 1
    demo_status = "✅ Enabled (Auto Synced to Mini App)" if data.get('demo_enabled', False) else "❌ Disabled"
    ranges_count = len(data.get('custom_ranges', []))
    free_link_text = data.get('free_link') if data.get('free_link') else "N/A"

    log_msg = (
        f"<b>➕ ɴᴇᴡ sᴛᴏʀʏ ᴀᴅᴅᴇᴅ!</b>\n\n"
        f"♨️ <b>Story :</b> {data['title']}\n"
        f"🔰 <b>Status :</b> {data.get('status', 'Completed')}\n"
        f"🖥️️ <b>Platform :</b> {data.get('category', 'Pocket FM')}\n"
        f"🧩 <b>Genre :</b> {data.get('genre', 'Drama')}\n"
        f"🎬 <b>Episodes :</b> {data.get('episodes', 'N/A')}\n"
        f"🔗 <b>Free Link :</b> {free_link_text}\n\n"
        f"░▒▓█ PRICE - ₹{data['price']} █▓▒░\n\n"
        f"<b>🎬 Demo Status:</b> {demo_status}\n"
        f"<b>🎧 Demo IDs:</b> {demo_msg_ids}\n"
        f"<b>📦 Files:</b> {total_files} (Msg {data['first_msg_id']} to {data['last_msg_id']})\n"
        f"<b>🎯 Custom Ranges:</b> {ranges_count} Configured\n\n"
        f"🔗 <b>sʜᴀʀᴇᴀʙʟᴇ ʟɪɴᴋ:</b>\n<code>{bot_share_link}</code>"
    )
    try:
        await send_log(client, log_msg)
    except Exception:
        pass
    
    await message.reply_text(
        f"✅ <b>sᴛᴏʀʏ ᴀᴅᴅᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
        f"♨️ <b>Story :</b> {data['title']}\n"
        f"🔰 <b>Status :</b> {data.get('status', 'Completed')}\n"
        f"🖥️ <b>Platform :</b> {data.get('category', 'Pocket FM')}\n"
        f"🧩 <b>Genre :</b> {data.get('genre', 'Drama')}\n"
        f"🎬 <b>Episodes :</b> {data.get('episodes', 'N/A')}\n"
        f"🔗 <b>Free Link :</b> {free_link_text}\n\n"
        f"░▒▓█ PRICE - ₹{data['price']} █▓▒░\n\n"
        f"<b>🎬 Demo Status:</b> {demo_status}\n"
        f"<b>🎧 Demo Files IDs:</b> {demo_msg_ids}\n"
        f"<b>📦 Total Files:</b> {total_files}\n"
        f"<b>🎯 Custom Buttons:</b> {ranges_count} Configured\n\n"
        f"🔗 <b>sʜᴀʀᴇᴀʙʟᴇ ʟɪɴᴋ:</b>\n<code>{bot_share_link}</code>",
        disable_web_page_preview=True
    )

# ------------------ ONGOING STORY ADD EPISODES WIZARD ------------------

@Client.on_message(filters.command("addepisodes") & filters.user(ADMIN_ID) & filters.private, group=1)
async def start_add_episodes_wizard(client, message):
    ONGOING_STATE[message.from_user.id] = {'step': 'STORY_NAME'}
    await message.reply_text(
        "➕ <b>ᴀᴅᴅ ᴇᴘɪsᴏᴅᴇs (ᴏɴɢᴏɪɴɢ sᴛᴏʀʏ) WIZARD:</b>\n\n"
        "जिस स्टोरी में नए एपिसोड ऐड करने हैं, उसका <b>Exact Story Title</b> दर्ज करें:\n"
        "<i>(टाइप करें /cancel रद्द करने के लिए)</i>",
        reply_markup=ForceReply(True)
    )

@Client.on_callback_query(filters.regex("^(og_opt_buttons|og_opt_single|og_add_range|og_finish_ranges)") & filters.user(ADMIN_ID))
async def ongoing_range_callbacks(client, callback):
    user_id = callback.from_user.id
    data = callback.data

    if user_id not in ONGOING_STATE:
        return await callback.answer("Session Expired!", show_alert=True)

    if data == "og_opt_buttons":
        ONGOING_STATE[user_id]['mode'] = 'BUTTONS'
        old_first = ONGOING_STATE[user_id]['old_first_id']
        old_last = ONGOING_STATE[user_id]['old_last_id']
        
        ONGOING_STATE[user_id]['step'] = 'OLD_RANGE_NAME'
        await callback.message.reply_text(
            f"📦 <b>पुरानी फाइलों (Msg {old_first} to {old_last}) का Button Name दर्ज करें:</b>\n"
            f"<i>(उदाहरण: Ep 1 to 50 या Part 1)</i>",
            reply_markup=ForceReply(True)
        )
        await callback.answer()

    elif data == "og_opt_single":
        ONGOING_STATE[user_id]['mode'] = 'SINGLE'
        ONGOING_STATE[user_id]['step'] = 'ASK_EPISODE_COUNT'
        await callback.message.reply_text(
            "🎬 <b>आपने एपिसोड कहाँ तक अपडेट कर दिए हैं?</b>\n"
            "<i>(कृपया सिर्फ नंबर भेजें, जैसे: 50, 100, या 120)</i>",
            reply_markup=ForceReply(True)
        )
        await callback.answer()

    elif data == "og_add_range":
        ONGOING_STATE[user_id]['step'] = 'RANGE_NAME'
        await callback.message.reply_text(
            "✏️ <b>नये Button का Name दर्ज करें:</b>\n"
            "<i>(उदाहरण: Ep 51-100, Part 2, या Final Episodes)</i>",
            reply_markup=ForceReply(True)
        )
        await callback.answer()

    elif data == "og_finish_ranges":
        state_data = ONGOING_STATE.pop(user_id, None)
        await finalize_add_episodes_buttons(client, callback.message, state_data)
        await callback.answer()

async def finalize_add_episodes_buttons(client, message, data):
    story_id = data['story_id']
    title = data['title']
    updated_ranges = data['custom_ranges']
    
    all_last_ids = [r['last_id'] for r in updated_ranges]
    all_first_ids = [r['first_id'] for r in updated_ranges]
    
    new_last_id = max(all_last_ids)
    min_first_id = min(all_first_ids)
    total_files_count = (new_last_id - min_first_id) + 1

    ep_count_text = data.get('episode_num_input') or f"{total_files_count} Episodes"

    update_payload = {
        "last_msg_id": new_last_id,
        "total_files": f"{total_files_count} files",
        "episodes": f"{ep_count_text} Episodes" if ep_count_text.isdigit() else ep_count_text,
        "custom_ranges": updated_ranges,
        "status": "Ongoing"
    }

    await stories_col.update_one(
        {"_id": story_id},
        {"$set": update_payload}
    )

    success_msg = (
        f"✅ <b>ᴏɴɢᴏɪɴɢ sᴛᴏʀʏ ᴜᴘᴅᴀᴛᴇᴅ (WITH BUTTONS)!</b>\n\n"
        f"♨️ <b>Story Title:</b> {title}\n"
        f"🔰 <b>Status:</b> Ongoing\n"
        f"🎬 <b>Updated Episodes:</b> {update_payload['episodes']}\n"
        f"📦 <b>Total Files Now:</b> {total_files_count} files\n"
        f"🎯 <b>Total Range Buttons:</b> {len(updated_ranges)} Configured\n\n"
        f"<i>Mini App और Bot दोनों में नए Buttons और Episodes सफलतापूर्वक ऐड हो गए हैं!</i>\n"
        f"📢 <i>Buyers को नोटिफिकेशन भेजा जा रहा है...</i>"
    )
    
    await message.reply_text(success_msg)

    ep_info_str = f"New Episodes / Ranges Added (Total: {update_payload['episodes']})"
    asyncio.create_task(notify_story_buyers(client, title, ep_info_str))

    try:
        log_text = (
            f"<b>➕ ᴏɴɢᴏɪɴɢ ᴇᴘɪsᴏᴅᴇs ᴜᴘᴅᴀᴛᴇᴅ (BUTTONS)</b>\n\n"
            f"📖 <b>Story:</b> <code>{title}</code>\n"
            f"🎬 <b>Episodes:</b> {update_payload['episodes']}\n"
            f"🎯 <b>Total Buttons:</b> {len(updated_ranges)}\n"
            f"📊 <b>Total Files:</b> {total_files_count}"
        )
        await send_log(client, log_text)
    except Exception:
        pass

async def finalize_add_episodes_single(client, message, data):
    story_id = data['story_id']
    title = data['title']
    first_id = data['old_first_id']
    old_last_id = data['old_last_id']
    new_last_id = data['new_last_id']
    ep_num = data.get('episode_num_input')
    
    total_files_count = (new_last_id - first_id) + 1 if (first_id and new_last_id) else "N/A"
    ep_text = f"{ep_num} Episodes" if str(ep_num).isdigit() else f"{ep_num}"

    update_payload = {
        "last_msg_id": new_last_id,
        "total_files": f"{total_files_count} files" if isinstance(total_files_count, int) else total_files_count,
        "episodes": ep_text,
        "status": "Ongoing"
    }

    await stories_col.update_one(
        {"_id": story_id},
        {"$set": update_payload}
    )

    success_msg = (
        f"✅ <b>ᴏɴɢᴏɪɴɢ sᴛᴏʀʏ ᴜᴘᴅᴀᴛᴇᴅ!</b>\n\n"
        f"♨️ <b>Story Title:</b> {title}\n"
        f"🔰 <b>Status:</b> Ongoing\n"
        f"🎬 <b>Episodes Updated To:</b> {ep_text}\n"
        f"📦 <b>New Last Msg ID:</b> {new_last_id}\n\n"
        f"<i>Mini App और Bot में एपिसोड काउंट {ep_text} सफलतापूर्वक सेट कर दिया गया है!</i>\n"
        f"📢 <i>Buyers को नोटिफिकेशन भेजा जा रहा है...</i>"
    )
    
    await message.reply_text(success_msg)

    ep_info_str = f"New Episodes Updated (Now up to {ep_text})"
    asyncio.create_task(notify_story_buyers(client, title, ep_info_str))

    try:
        log_text = (
            f"<b>➕ ᴏɴɢᴏɪɴɢ ᴇᴘɪsᴏᴅᴇs ᴜᴘᴅᴀᴛᴇᴅ</b>\n\n"
            f"📖 <b>Story:</b> <code>{title}</code>\n"
            f"🎬 <b>Episodes:</b> {ep_text}\n"
            f"📦 <b>Last Msg ID:</b> {new_last_id}"
        )
        await send_log(client, log_text)
    except Exception:
        pass

# ------------------ MARK STORY AS COMPLETED ------------------

@Client.on_message(filters.command("markcomplete") & filters.user(ADMIN_ID) & filters.private, group=1)
async def start_mark_complete(client, message):
    COMPLETE_STATE[message.from_user.id] = {'step': 'STORY_NAME'}
    await message.reply_text(
        "🏆 <b>ᴍᴀʀᴋ sᴛᴏʀʏ ᴀs ᴄᴏᴍᴘʟᴇᴛᴇᴅ WIZARD:</b>\n\n"
        "जिस Ongoing स्टोरी को <b>Completed</b> मार्क करना है, उसका <b>Exact Title</b> दर्ज करें:\n"
        "<i>(टाइप करें /cancel रद्द करने के लिए)</i>",
        reply_markup=ForceReply(True)
    )

@Client.on_callback_query(filters.regex("^mc_last_") & filters.user(ADMIN_ID))
async def mark_complete_callbacks(client, callback):
    user_id = callback.from_user.id
    if user_id not in COMPLETE_STATE:
        return await callback.answer("Session Expired!", show_alert=True)

    choice = callback.data.split("mc_last_")[1]

    if choice == "yes":
        COMPLETE_STATE[user_id]['step'] = 'INPUT_NEW_LAST'
        await callback.message.reply_text(
            "🔢 <b>Final/Last Episode का Message ID या Telegram Link भेजें:</b>",
            reply_markup=ForceReply(True)
        )
        await callback.answer()
    else:
        COMPLETE_STATE[user_id]['final_last_id'] = COMPLETE_STATE[user_id]['old_last_id']
        state_data = COMPLETE_STATE.pop(user_id, None)
        await finalize_mark_completed(client, callback.message, state_data)
        await callback.answer()

async def finalize_mark_completed(client, message, data):
    story_id = data['story_id']
    title = data['title']
    first_id = data['old_first_id']
    final_last_id = data['final_last_id']

    total_files_count = (final_last_id - first_id) + 1 if (first_id and final_last_id) else "All"

    update_payload = {
        "status": "Completed",
        "last_msg_id": final_last_id,
        "total_files": f"{total_files_count} files" if isinstance(total_files_count, int) else total_files_count,
        "episodes": f"{total_files_count} Episodes (Full)" if isinstance(total_files_count, int) else "Completed"
    }

    await stories_col.update_one({"_id": story_id}, {"$set": update_payload})

    success_text = (
        f"🏆 <b>sᴛᴏʀʏ ᴍᴀʀᴋᴇᴅ ᴀs ᴄᴏᴍᴘʟᴇᴛᴇᴅ!</b>\n\n"
        f"📖 <b>Title:</b> {title}\n"
        f"🔰 <b>New Status:</b> Completed 🎉\n"
        f"📦 <b>Total Files:</b> {total_files_count}\n\n"
        f"<i>Mini App और Bot दोनों जगह यह स्टोरी अब COMPLETED शो करेगी!</i>\n"
        f"📢 <i>Buyers को Completion नोटिफिकेशन भेजा जा रहा है...</i>"
    )

    await message.reply_text(success_text)

    ep_info_str = f"🎉 Story fully completed! All episodes uploaded ({total_files_count} files)."
    asyncio.create_task(notify_story_buyers(client, title, ep_info_str))

    try:
        log_text = (
            f"<b>🏆 sᴛᴏʀʏ COMPLETED</b>\n\n"
            f"📖 <b>Title:</b> <code>{title}</code>\n"
            f"📊 <b>Total Files:</b> {total_files_count}"
        )
        await send_log(client, log_text)
    except Exception:
        pass

# ------------------ MASTER INPUT HANDLER FOR PRIVATE MESSAGES ------------------

@Client.on_message(filters.private & filters.user(ADMIN_ID) & ~filters.command(["start", "addstory", "deletestory", "allstories", "cancel", "addmoney", "refreshstories", "addepisodes", "markcomplete", "editname", "setepisodes", "changestatus"]), group=1)
async def master_input_handler(client, message):
    user_id = message.from_user.id

    # 1. EDIT STORY NAME INPUT HANDLER
    if user_id in EDIT_NAME_STATE and 'step' in EDIT_NAME_STATE[user_id]:
        step = EDIT_NAME_STATE[user_id]['step']

        if step == 'OLD_NAME':
            old_title = message.text.strip().split("\n")[0]
            story = await stories_col.find_one({"title": {"$regex": f"^{re.escape(old_title)}$", "$options": "i"}})

            if not story:
                return await message.reply_text(f"❌ <b>'{old_title}' नाम से कोई स्टोरी नहीं मिली!</b>\nसही स्टोरी नाम दर्ज करें या /cancel करें:")

            EDIT_NAME_STATE[user_id]['story_id'] = story['_id']
            EDIT_NAME_STATE[user_id]['old_title'] = story['title']
            EDIT_NAME_STATE[user_id]['step'] = 'NEW_NAME'

            await message.reply_text(
                f"✅ <b>स्टोरी मिल गई:</b> {story['title']}\n\n"
                f"✏️ <b>अब इस स्टोरी का नया (New) Title दर्ज करें:</b>",
                reply_markup=ForceReply(True)
            )

        elif step == 'NEW_NAME':
            new_title = message.text.strip().split("\n")[0]
            story_id = EDIT_NAME_STATE[user_id]['story_id']
            old_title = EDIT_NAME_STATE[user_id]['old_title']

            clean_title = new_title.replace(" ", "_")
            new_link = f"https://t.me/{BOT_USERNAME}?start=get_{clean_title}"

            await stories_col.update_one(
                {"_id": story_id},
                {"$set": {"title": new_title, "link": new_link}}
            )

            EDIT_NAME_STATE.pop(user_id, None)

            await message.reply_text(
                f"✅ <b>sᴛᴏʀʏ ɴᴀᴍᴇ ᴜᴘᴅᴀᴛᴇᴅ!</b>\n\n"
                f"🔴 <b>Old Name:</b> {old_title}\n"
                f"🟢 <b>New Name:</b> {new_title}\n"
                f"🔗 <b>New Share Link:</b> <code>https://t.me/{BOT_USERNAME}?start=story_{clean_title}</code>\n\n"
                f"<i>Mini App और Bot दोनों जगह नया नाम सिंक हो गया है!</i>"
            )
        return

    # 2. EDIT EPISODES ONLY INPUT HANDLER
    if user_id in EDIT_EPISODES_STATE and 'step' in EDIT_EPISODES_STATE[user_id]:
        step = EDIT_EPISODES_STATE[user_id]['step']

        if step == 'STORY_NAME':
            story_title = message.text.strip().split("\n")[0]
            story = await stories_col.find_one({"title": {"$regex": f"^{re.escape(story_title)}$", "$options": "i"}})

            if not story:
                return await message.reply_text(f"❌ <b>'{story_title}' नाम से कोई स्टोरी नहीं मिली!</b>\nसही स्टोरी नाम दर्ज करें या /cancel करें:")

            EDIT_EPISODES_STATE[user_id]['story_id'] = story['_id']
            EDIT_EPISODES_STATE[user_id]['title'] = story['title']
            EDIT_EPISODES_STATE[user_id]['step'] = 'NEW_EPISODE_TEXT'

            await message.reply_text(
                f"✅ <b>स्टोरी मिल गई:</b> {story['title']}\n"
                f"🎬 <b>Current Episodes Text:</b> {story.get('episodes', 'N/A')}\n\n"
                f"✏️ <b>नया Episodes Text या Range दर्ज करें:</b>\n"
                f"<i>(उदाहरण: 50 Episodes, 1 to 100 Episodes, या 120+ Episodes)</i>",
                reply_markup=ForceReply(True)
            )

        elif step == 'NEW_EPISODE_TEXT':
            new_ep_text = message.text.strip()
            story_id = EDIT_EPISODES_STATE[user_id]['story_id']
            title = EDIT_EPISODES_STATE[user_id]['title']

            final_ep_str = f"{new_ep_text} Episodes" if new_ep_text.isdigit() else new_ep_text

            await stories_col.update_one(
                {"_id": story_id},
                {"$set": {"episodes": final_ep_str}}
            )

            EDIT_EPISODES_STATE.pop(user_id, None)

            await message.reply_text(
                f"✅ <b>ᴇᴘɪsᴏᴅᴇs ᴜᴘᴅᴀᴛᴇᴅ!</b>\n\n"
                f"📖 <b>Story:</b> {title}\n"
                f"🎬 <b>New Episodes Text:</b> <code>{final_ep_str}</code>\n\n"
                f"<i>Mini App और Bot में एपिसोड टेक्स्ट बदल दिया गया है!</i>"
            )
        return

    # 3. CHANGE STATUS INPUT HANDLER
    if user_id in CHANGE_STATUS_STATE and 'step' in CHANGE_STATUS_STATE[user_id]:
        step = CHANGE_STATUS_STATE[user_id]['step']

        if step == 'STORY_NAME':
            story_title = message.text.strip().split("\n")[0]
            story = await stories_col.find_one({"title": {"$regex": f"^{re.escape(story_title)}$", "$options": "i"}})

            if not story:
                return await message.reply_text(f"❌ <b>'{story_title}' नाम से कोई स्टोरी नहीं मिली!</b>\nसही स्टोरी नाम दर्ज करें या /cancel करें:")

            CHANGE_STATUS_STATE[user_id]['story_id'] = story['_id']
            CHANGE_STATUS_STATE[user_id]['title'] = story['title']

            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🟡 Ongoing सेट करें", callback_data="setstatus_Ongoing"),
                    InlineKeyboardButton("🟢 Completed सेट करें", callback_data="setstatus_Completed")
                ]
            ])

            await message.reply_text(
                f"✅ <b>स्टोरी मिल गई:</b> {story['title']}\n"
                f"🔰 <b>Current Status:</b> {story.get('status', 'Completed')}\n\n"
                f"<b>आप इसका स्टेटस क्या सेट करना चाहते हैं?</b>",
                reply_markup=kb
            )
        return

    # 4. DELETE STORY WIZARD INPUT
    if user_id in DELETE_STATE:
        story_title = message.text.strip().split("\n")[0]
        deleted = await delete_story_db(story_title)
        DELETE_STATE.pop(user_id, None)

        if deleted:
            await message.reply_text(f"✅ <b>sᴛᴏʀʏ '{story_title}' ᴅᴇʟᴇᴛᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ ғᴏʀᴍ ᴅᴀᴛᴀʙᴀsᴇ!</b>")
            try:
                await send_log(client, f"🗑️ <b>sᴛᴏʀʏ ᴅᴇʟᴇᴛᴇᴅ:</b> <code>{story_title}</code>")
            except Exception:
                pass
        else:
            await message.reply_text(f"❌ <b>ғᴀɪʟᴇᴅ ᴛᴏ ᴅᴇʟᴇᴛᴇ!</b> Story name <code>{story_title}</code> not found in database.")
        return

    # 5. MARK COMPLETE WIZARD INPUT
    if user_id in COMPLETE_STATE and 'step' in COMPLETE_STATE[user_id]:
        step = COMPLETE_STATE[user_id]['step']

        if step == 'STORY_NAME':
            story_title = message.text.strip().split("\n")[0]
            story = await stories_col.find_one({"title": {"$regex": f"^{re.escape(story_title)}$", "$options": "i"}})

            if not story:
                return await message.reply_text(f"❌ <b>'{story_title}' नाम से कोई स्टोरी नहीं मिली!</b>\nसही स्टोरी नाम दर्ज करें या /cancel करें:")

            COMPLETE_STATE[user_id]['story_id'] = story['_id']
            COMPLETE_STATE[user_id]['title'] = story['title']
            COMPLETE_STATE[user_id]['old_first_id'] = story.get('first_msg_id')
            COMPLETE_STATE[user_id]['old_last_id'] = story.get('last_msg_id')
            COMPLETE_STATE[user_id]['step'] = 'ASK_NEW_LAST'

            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("YES (अपडेट करें)", callback_data="mc_last_yes"),
                    InlineKeyboardButton("NO (पुराना ही रखें)", callback_data="mc_last_no")
                ]
            ])

            await message.reply_text(
                f"✅ <b>स्टोरी मिल गई:</b> {story['title']}\n"
                f"ℹ️ <b>Current Status:</b> {story.get('status', 'Ongoing')}\n"
                f"📦 <b>Current Last Msg ID:</b> {story.get('last_msg_id')}\n\n"
                f"<b>क्या आप इस स्टोरी का Final Last Message ID / Link भी बदलना चाहते हैं?</b>",
                reply_markup=kb
            )

        elif step == 'INPUT_NEW_LAST':
            new_last = extract_msg_id(message.text)
            if not new_last:
                return await message.reply_text("❌ Invalid ID/Link! Valid Link/ID भेजें:")

            old_f = COMPLETE_STATE[user_id]['old_first_id']
            if new_last and old_f and new_last < old_f:
                return await message.reply_text("❌ Last Message ID, First ID से छोटा नहीं हो सकता। दोबारा सही Link भेजें:")

            COMPLETE_STATE[user_id]['final_last_id'] = new_last
            state_data = COMPLETE_STATE.pop(user_id, None)
            await finalize_mark_completed(client, message, state_data)
        return

    # 6. ONGOING STORY WIZARD INPUT
    if user_id in ONGOING_STATE and 'step' in ONGOING_STATE[user_id]:
        step = ONGOING_STATE[user_id]['step']

        if step == 'STORY_NAME':
            story_title = message.text.strip().split("\n")[0]
            story = await stories_col.find_one({"title": {"$regex": f"^{re.escape(story_title)}$", "$options": "i"}})

            if not story:
                return await message.reply_text(f"❌ <b>'{story_title}' नाम से कोई स्टोरी नहीं मिली!</b>\nसही स्टोरी नाम दर्ज करें या /cancel करें:")

            ONGOING_STATE[user_id]['story_id'] = story['_id']
            ONGOING_STATE[user_id]['title'] = story['title']
            ONGOING_STATE[user_id]['custom_ranges'] = list(story.get('custom_ranges', []))
            ONGOING_STATE[user_id]['old_first_id'] = story.get('first_msg_id')
            ONGOING_STATE[user_id]['old_last_id'] = story.get('last_msg_id')

            ONGOING_STATE[user_id]['step'] = 'ASK_EPISODE_COUNT'
            await message.reply_text(
                f"✅ <b>स्टोरी मिल गई:</b> {story['title']}\n"
                f"🎬 <b>Current Episode Status:</b> {story.get('episodes', 'N/A')}\n\n"
                f"❓ <b>आपने इस ऑनगोइंग स्टोरी के एपिसोड कहाँ तक अपडेट कर दिए हैं?</b>\n"
                f"<i>(कृपया सिर्फ नंबर भेजें, जैसे: 25, 50 या 100)</i>",
                reply_markup=ForceReply(True)
            )

        elif step == 'ASK_EPISODE_COUNT':
            ep_input = message.text.strip()
            ONGOING_STATE[user_id]['episode_num_input'] = ep_input

            existing_ranges = ONGOING_STATE[user_id].get('custom_ranges', [])

            if existing_ranges:
                ONGOING_STATE[user_id]['step'] = 'RANGE_NAME'
                ranges_txt = "\n".join([f"• <b>{r['name']}</b> (Msg {r['first_id']} to {r['last_id']})" for r in existing_ranges])
                await message.reply_text(
                    f"✅ एपिसोड अपडेट होकर <b>{ep_input} Episodes</b> सेट करने के लिए रेडी हैं।\n\n"
                    f"🔘 <b>मौजूदा Buttons:</b>\n{ranges_txt}\n\n"
                    f"✏️ <b>नये Button का Name दर्ज करें:</b>\n"
                    f"<i>(उदाहरण: Ep 51-100, Part 2, या Final Episodes)</i>",
                    reply_markup=ForceReply(True)
                )
            else:
                ONGOING_STATE[user_id]['step'] = 'SELECT_MODE'
                old_f = ONGOING_STATE[user_id].get('old_first_id')
                old_l = ONGOING_STATE[user_id].get('old_last_id')
                old_count = (old_l - old_f) + 1 if (old_f and old_l) else 0

                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔘 Custom Range Buttons बनाना चाहते हैं", callback_data="og_opt_buttons")],
                    [InlineKeyboardButton("📦 Single Delivery (बिना बटन अटैच करना)", callback_data="og_opt_single")]
                ])

                await message.reply_text(
                    f"✅ <b>एपिसोड स्टेटस सेट:</b> {ep_input} Episodes\n"
                    f"ℹ <b>पुरानी फाइलों की रेंज:</b> Msg {old_f} to {old_l} ({old_count} एपिसोड्स)\n\n"
                    f"⚠️ <i>इस स्टोरी में पहले से कोई Button नहीं बना है।</i>\n\n"
                    f"<b>आप नए एपिसोड किस फॉर्मेट में जोड़ना चाहते हैं?</b>",
                    reply_markup=kb
                )

        elif step == 'OLD_RANGE_NAME':
            old_name = message.text.strip()
            old_f = ONGOING_STATE[user_id]['old_first_id']
            old_l = ONGOING_STATE[user_id]['old_last_id']

            ONGOING_STATE[user_id]['custom_ranges'].append({
                "name": old_name,
                "first_id": old_f,
                "last_id": old_l
            })

            ONGOING_STATE[user_id]['step'] = 'RANGE_NAME'
            await message.reply_text(
                f"✅ पुरानी फाइलों का बटन बना दिया: <b>{old_name}</b> (Msg {old_f} to {old_l})\n\n"
                f"✏️ <b>अब नये एपिसोड्स के Button का Name दर्ज करें:</b>\n"
                f"<i>(उदाहरण: Ep 51-100 या Part 2)</i>",
                reply_markup=ForceReply(True)
            )

        elif step == 'SINGLE_NEW_LAST':
            l_id = extract_msg_id(message.text)
            if not l_id:
                return await message.reply_text("❌ Invalid ID/Link! Valid Message ID/Link भेजें:")

            old_l = ONGOING_STATE[user_id]['old_last_id']
            if old_l and l_id <= old_l:
                return await message.reply_text(f"❌ नया Last Link पुरानी Last ID ({old_l}) से बड़ा होना चाहिए। फिर से सही Last Link भेजें:")

            ONGOING_STATE[user_id]['new_last_id'] = l_id
            state_data = ONGOING_STATE.pop(user_id, None)
            await finalize_add_episodes_single(client, message, state_data)

        elif step == 'RANGE_NAME':
            ONGOING_STATE[user_id]['temp_range_name'] = message.text.strip()
            ONGOING_STATE[user_id]['step'] = 'RANGE_FIRST'
            await message.reply_text(
                f"🔢 Button <b>'{message.text.strip()}'</b> के लिए <b>First Message ID / Link</b> भेजें:",
                reply_markup=ForceReply(True)
            )

        elif step == 'RANGE_FIRST':
            f_id = extract_msg_id(message.text)
            if not f_id:
                return await message.reply_text("❌ Invalid ID/Link! Valid Message ID ya Telegram Link bhejein:")

            ONGOING_STATE[user_id]['temp_range_first'] = f_id
            ONGOING_STATE[user_id]['step'] = 'RANGE_LAST'
            await message.reply_text(
                f"🔢 Button <b>'{ONGOING_STATE[user_id]['temp_range_name']}'</b> के लिए <b>Last Message ID / Link</b> भेजें:",
                reply_markup=ForceReply(True)
            )

        elif step == 'RANGE_LAST':
            l_id = extract_msg_id(message.text)
            if not l_id:
                return await message.reply_text("❌ Invalid ID/Link! Valid Message ID ya Telegram Link bhejein:")

            f_id = ONGOING_STATE[user_id]['temp_range_first']
            name = ONGOING_STATE[user_id]['temp_range_name']

            if l_id < f_id:
                return await message.reply_text("❌ Last Message ID, First Message ID से छोटी नहीं हो सकती। फिर से सही Last Link भेजें:")

            ONGOING_STATE[user_id]['custom_ranges'].append({
                "name": name,
                "first_id": f_id,
                "last_id": l_id
            })

            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("➕ Add One More Range/Button", callback_data="og_add_range"),
                    InlineKeyboardButton("✅ Done & Save Ongoing Story", callback_data="og_finish_ranges")
                ]
            ])

            await message.reply_text(
                f"✅ <b>New Button Added:</b> <code>{name}</code> (Msg {f_id} to {l_id})\n\n"
                f"क्या आप एक और Button/Range ऐड करना चाहते हैं या सेव करें?",
                reply_markup=kb
            )
        return

    # 7. ADD STORY WIZARD INPUT
    if user_id in ADD_STATE and 'step' in ADD_STATE[user_id]:
        step = ADD_STATE[user_id]['step']
        
        if step == 'TITLE':
            ADD_STATE[user_id]['title'] = message.text.strip().split("\n")[0]
            ADD_STATE[user_id]['step'] = 'STATUS'
            await message.reply_text("<b>[sᴛᴇᴘ 4/10]</b> 🔰 ᴇɴᴛᴇʀ sᴛᴏʀʏ sᴛᴀᴛᴜs:\n<i>(उदाहरण: Completed या Ongoing)</i>", reply_markup=ForceReply(True))

        elif step == 'STATUS':
            ADD_STATE[user_id]['status'] = message.text.strip()
            ADD_STATE[user_id]['step'] = 'EPISODES'
            await message.reply_text("<b>[sᴛᴇᴘ 5/10]</b> 🎬 ᴇɴᴛᴇʀ ᴛᴏᴛᴀʟ ᴇᴘɪsᴏᴅᴇs:\n<i>(उदाहरण: 80 Episodes, 100+ Episodes या Ongoing)</i>", reply_markup=ForceReply(True))

        elif step == 'EPISODES':
            ADD_STATE[user_id]['episodes'] = message.text.strip()
            ADD_STATE[user_id]['step'] = 'PHOTO'
            await message.reply_text("<b>[sᴛᴇᴘ 6/10]</b> sᴇɴᴅ ᴛʜᴇ sᴛᴏʀʏ ᴘᴏsᴛᴇʀ ᴘʜᴏᴛᴏ (ᴏʀ ᴇɴᴛᴇʀ ᴀɴ ɪᴍᴀɢᴇ ᴜʀʟ):", reply_markup=ForceReply(True))
            
        elif step == 'PHOTO':
            if message.photo:
                ADD_STATE[user_id]['photo'] = message.photo.file_id
            elif message.text and (message.text.startswith("http://") or message.text.startswith("https://")):
                ADD_STATE[user_id]['photo'] = message.text.strip()
            else:
                return await message.reply_text("❌ ᴘʟᴇᴀsᴇ sᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ᴘʜᴏᴛᴏ ᴏʀ ɪᴍᴀɢᴇ ᴜʀʟ:")
                
            ADD_STATE[user_id]['step'] = 'PRICE'
            await message.reply_text("<b>[sᴛᴇᴘ 7/10]</b> ᴇɴᴛᴇʀ ᴛʜᴇ ᴘʀɪᴄᴇ (₹):", reply_markup=ForceReply(True))
            
        elif step == 'PRICE':
            if not message.text or not message.text.isdigit():
                return await message.reply_text("❌ ᴘʟᴇᴀsᴇ ᴇɴᴛᴇʀ ᴛʜᴇ ᴘʀɪᴄᴇ ɪɴ ɴᴜᴍʙᴇʀs ᴏɴʟʏ (ᴇ.ɢ., 99):")
            ADD_STATE[user_id]['price'] = int(message.text)
            ADD_STATE[user_id]['step'] = 'DESC'
            await message.reply_text("<b>[sᴛᴇᴘ 8/10]</b> ᴇɴᴛᴇʀ ᴛʜᴇ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:", reply_markup=ForceReply(True))
            
        elif step == 'DESC':
            ADD_STATE[user_id]['desc'] = message.text.strip()
            ADD_STATE[user_id]['step'] = 'FREE_LINK'
            
            skip_btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("⏩ Skip Link", callback_data="skip_free_link")]
            ])
            await message.reply_text(
                "🔗 <b>[sᴛᴇᴘ 8.5/10] External Free Link दर्ज करें:</b>\n\n"
                "EarnLink / Terabox या कोई भी Free User URL भेजें।\n"
                "<i>(अगर नहीं देना चाहते तो नीचे <b>Skip Link</b> पर क्लिक करें)</i>",
                reply_markup=skip_btn
            )

        elif step == 'FREE_LINK':
            link_text = message.text.strip()
            if not (link_text.startswith("http://") or link_text.startswith("https://")):
                return await message.reply_text("❌ Invalid URL! Valid http/https URL भेजें या 'Skip Link' बटन दबाएं:")

            ADD_STATE[user_id]['free_link'] = link_text
            ADD_STATE[user_id]['step'] = 'ASK_DEMO'
            
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Yes (Enable Demo)", callback_data="setdemo_yes"),
                    InlineKeyboardButton("❌ No (Disable Demo)", callback_data="setdemo_no")
                ]
            ])
            await message.reply_text("<b>[sᴛᴇᴘ 9/10]</b> क्या आप इस स्टोरी के लिए <b>🎬 View Demo</b> चालू रखना चाहते हैं?", reply_markup=kb)

        elif step == 'FIRST_MSG':
            first_id = extract_msg_id(message.text)
            if not first_id:
                return await message.reply_text("❌ Invalid ID/Link! Valid Message ID or Telegram Link enter karein:")
            
            ADD_STATE[user_id]['first_msg_id'] = first_id
            ADD_STATE[user_id]['step'] = 'LAST_MSG'
            await message.reply_text("<b>[sᴛᴇᴘ 10/10]</b> DB Channel से स्टोरी की <b>LAST Message ID / Link</b> भेजें:", reply_markup=ForceReply(True))

        elif step == 'LAST_MSG':
            last_id = extract_msg_id(message.text)
            if not last_id:
                return await message.reply_text("❌ Invalid ID/Link! Valid Message ID or Telegram Link enter karein:")

            data = ADD_STATE[user_id]
            data['last_msg_id'] = last_id
            
            if data['last_msg_id'] < data['first_msg_id']:
                return me.reply_text("❌ Last Message ID, First Message ID से छोटी नहीं हो सकती। फिर से सही Last ID भेजें:")

            total_files = (data['last_msg_id'] - data['first_msg_id']) + 1

            data['custom_ranges'] = []
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Yes (Custom Buttons)", callback_data="setrange_yes"),
                    InlineKeyboardButton("❌ No (Single Delivery)", callback_data="setrange_no")
                ]
            ])
            return await message.reply_text(
                f"📦 <b>ᴛᴏᴛᴀʟ ғɪʟᴇs: {total_files}</b>\n\n"
                f"क्या आप इस स्टोरी के लिए Custom Range Buttons (जैसे Ep 1-50, Ep 51-100) बनाना चाहते हैं?",
                reply_markup=kb
            )

        elif step == 'RANGE_NAME':
            ADD_STATE[user_id]['temp_range_name'] = message.text.strip()
            ADD_STATE[user_id]['step'] = 'RANGE_FIRST'
            await message.reply_text("🔢 इस Button के लिए <b>First Message ID / Link</b> भेजें:", reply_markup=ForceReply(True))

        elif step == 'RANGE_FIRST':
            f_id = extract_msg_id(message.text)
            if not f_id:
                return await message.reply_text("❌ Invalid ID/Link! Valid Link send karein:")
            
            ADD_STATE[user_id]['temp_range_first'] = f_id
            ADD_STATE[user_id]['step'] = 'RANGE_LAST'
            await message.reply_text("🔢 इस Button के लिए <b>Last Message ID / Link</b> भेजें:", reply_markup=ForceReply(True))

        elif step == 'RANGE_LAST':
            l_id = extract_msg_id(message.text)
            if not l_id:
                return await message.reply_text("❌ Invalid ID/Link! Valid Link send karein:")
            
            f_id = ADD_STATE[user_id]['temp_range_first']
            name = ADD_STATE[user_id]['temp_range_name']

            if l_id < f_id:
                return await message.reply_text("❌ Last Message ID, First ID से छोटी नहीं हो सकती। दोबारा सही Last Link भेजें:")

            ADD_STATE[user_id]['custom_ranges'].append({
                "name": name,
                "first_id": f_id,
                "last_id": l_id
            })

            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("➕ Add One More Range", callback_data="add_more_range"),
                    InlineKeyboardButton("✅ Done & Save Story", callback_data="finish_ranges")
                ]
            ])
            await message.reply_text(
                f"✅ <b>Range Added:</b> <code>{name}</code> (Msg {f_id} to {l_id})\n\n"
                f"क्या आप एक और Button/Range ऐड करना चाहते हैं या सेव करें?",
                reply_markup=kb
            )
        return

    message.continue_propagation()
