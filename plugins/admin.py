from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from config import ADMIN_ID, BOT_USERNAME
from database.db import add_story_db, delete_story_db, get_all_stories, send_log

ADD_STATE = {}
DELETE_STATE = {}

# 1. Cancel Command (Cancel both Add & Delete operations)
@Client.on_message(filters.command("cancel") & filters.user(ADMIN_ID) & filters.private, group=1)
async def cancel_action(client, message):
    user_id = message.from_user.id
    if user_id in ADD_STATE or user_id in DELETE_STATE:
        ADD_STATE.pop(user_id, None)
        DELETE_STATE.pop(user_id, None)
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
        text += f"{idx}. <b>{s['title']}</b> | ₹{s['price']} | <i>{s['category']}</i>\n"
    
    await message.reply_text(text)

# 3. Delete Story Command
@Client.on_message(filters.command("deletestory") & filters.user(ADMIN_ID) & filters.private, group=1)
async def start_delete(client, message):
    user_id = message.from_user.id
    DELETE_STATE[user_id] = True
    await message.reply_text(
        "🗑️ <b>ᴅᴇʟᴇᴛᴇ sᴛᴏʀɪᴇs ᴡɪᴢᴀʀᴅ:</b>\n\n"
        "ᴇɴᴛᴇʀ ᴛʜᴇ <b>ᴇxᴀᴄᴛ ᴛɪᴛʟᴇ</b> ᴏғ ᴛʜᴇ sᴛᴏʀʏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴅᴇʟᴇᴛᴇ:\n"
        "<i>(ᴛʏᴘᴇ /cancel ᴛᴏ ᴀʙᴏʀᴛ)</i>",
        reply_markup=ForceReply(True)
    )

# 4. Add Story Command
@Client.on_message(filters.command("addstory") & filters.user(ADMIN_ID) & filters.private, group=1)
async def start_add(client, message):
    ADD_STATE[message.from_user.id] = {}
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📻 Pocket FM", callback_data="setcat_pocket_fm")],
        [InlineKeyboardButton("📚 Pratilipi FM", callback_data="setcat_pratilipi_fm")]
    ])
    await message.reply_text("<b>[sᴛᴇᴘ 1/6]</b> sᴇʟᴇᴄᴛ ᴛʜᴇ sᴛᴏʀʏ ᴄᴀᴛᴇɢᴏʀʏ:\n<i>(ᴛʏᴘᴇ /cancel ᴛᴏ ᴀʙᴏʀᴛ)</i>", reply_markup=kb)

# 5. Category Selection Callback
@Client.on_callback_query(filters.regex("^setcat_") & filters.user(ADMIN_ID))
async def cat_selected(client, callback):
    ADD_STATE[callback.from_user.id]['category'] = callback.data.split("setcat_")[1]
    ADD_STATE[callback.from_user.id]['step'] = 'TITLE'
    await callback.message.reply_text("<b>[sᴛᴇᴘ 2/6]</b> ᴇɴᴛᴇʀ ᴛʜᴇ sᴛᴏʀʏ ᴛɪᴛʟᴇ:", reply_markup=ForceReply(True))
    await callback.answer()

# 6. Admin Input Wizard (Handles Photos, Text inputs & Deletions)
@Client.on_message(filters.private & filters.user(ADMIN_ID) & ~filters.command(["start", "addstory", "deletestory", "allstories", "cancel"]), group=1)
async def wizard_inputs(client, message):
    user_id = message.from_user.id
    
    # --- Delete Story Process ---
    if user_id in DELETE_STATE:
        title_to_delete = message.text.strip()
        deleted = await delete_story_db(title_to_delete)
        del DELETE_STATE[user_id]
        
        if deleted:
            return await message.reply_text(f"✅ <b>'{title_to_delete}'</b> sᴛᴏʀʏ ᴅᴇʟᴇᴛᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!")
        else:
            return await message.reply_text(f"❌ ɴᴏ sᴛᴏʀʏ ғᴏᴜɴᴅ ᴡɪᴛʜ ᴛʜᴇ ᴛɪᴛʟᴇ <b>'{title_to_delete}'</b>.")

    # --- Add Story Process ---
    if user_id not in ADD_STATE or 'step' not in ADD_STATE[user_id]:
        message.continue_propagation()
        return
        
    step = ADD_STATE[user_id]['step']
    
    if step == 'TITLE':
        # Save only the first line as the title
        ADD_STATE[user_id]['title'] = message.text.strip().split("\n")[0]
        ADD_STATE[user_id]['step'] = 'PHOTO'
        await message.reply_text("<b>[sᴛᴇᴘ 3/6]</b> sᴇɴᴅ ᴛʜᴇ sᴛᴏʀʏ ᴘᴏsᴛᴇʀ ᴘʜᴏᴛᴏ (ᴏʀ ᴇɴᴛᴇʀ ᴀɴ ɪᴍᴀɢᴇ ᴜʀʟ):", reply_markup=ForceReply(True))
        
    elif step == 'PHOTO':
        if message.photo:
            ADD_STATE[user_id]['photo'] = message.photo.file_id
        elif message.text and (message.text.startswith("http://") or message.text.startswith("https://")):
            ADD_STATE[user_id]['photo'] = message.text.strip()
        else:
            return await message.reply_text("❌ ᴘʟᴇᴀsᴇ sᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ᴘʜᴏᴛᴏ ᴏʀ ɪᴍᴀɢᴇ ᴜʀʟ:")
            
        ADD_STATE[user_id]['step'] = 'PRICE'
        await message.reply_text("<b>[sᴛᴇᴘ 4/6]</b> ᴇɴᴛᴇʀ ᴛʜᴇ ᴘʀɪᴄᴇ (₹):", reply_markup=ForceReply(True))
        
    elif step == 'PRICE':
        if not message.text or not message.text.isdigit():
            return await message.reply_text("❌ ᴘʟᴇᴀsᴇ ᴇɴᴛᴇʀ ᴛʜᴇ ᴘʀɪᴄᴇ ɪɴ ɴᴜᴍʙᴇʀs ᴏɴʟʏ (ᴇ.ɢ., 99):")
        ADD_STATE[user_id]['price'] = int(message.text)
        ADD_STATE[user_id]['step'] = 'DESC'
        await message.reply_text("<b>[sᴛᴇᴘ 5/6]</b> ᴇɴᴛᴇʀ ᴛʜᴇ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:", reply_markup=ForceReply(True))
        
    elif step == 'DESC':
        ADD_STATE[user_id]['desc'] = message.text.strip()
        ADD_STATE[user_id]['step'] = 'LINK'
        await message.reply_text("<b>[sᴛᴇᴘ 6/6]</b> sᴇɴᴅ ᴛʜᴇ ᴅᴇsᴛɪɴᴀᴛɪᴏɴ / ᴄʜᴀɴɴᴇʟ ʟɪɴᴋ ғᴏʀ ᴀғᴛᴇʀ-ᴘᴜʀᴄʜᴀsᴇ:", reply_markup=ForceReply(True))
        
    elif step == 'LINK':
        data = ADD_STATE[user_id]
        data['link'] = message.text.strip()
        
        # Save to database
        await add_story_db(data)
        
        clean_title = data['title'].replace(" ", "_")
        share_link = f"https://t.me/{BOT_USERNAME}?start=story_{clean_title}"
        
        # Send log notification
        log_msg = (
            f"<b>➕ ɴᴇᴡ sᴛᴏʀʏ ᴀᴅᴅᴇᴅ!</b>\n\n"
            f"<b>📌 ᴛɪᴛʟᴇ:</b> {data['title']}\n"
            f"<b>📂 ᴄᴀᴛᴇɢᴏʀʏ:</b> {data['category']}\n"
            f"<b>💰 ᴘʀɪᴄᴇ:</b> ₹{data['price']}\n"
            f"<b>🔗 ᴅᴇsᴛɪɴᴀᴛɪᴏɴ ʟɪɴᴋ:</b> {data['link']}\n"
            f"<b>🔗 sʜᴀʀᴇᴀʙʟᴇ ʟɪɴᴋ:</b> {share_link}"
        )
        try:
            await send_log(client, log_msg)
        except Exception:
            pass
        
        # Send confirmation to admin
        await message.reply_text(
            f"✅ <b>sᴛᴏʀʏ ᴀᴅᴅᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
            f"<b>ᴛɪᴛʟᴇ:</b> {data['title']}\n"
            f"<b>ᴘʀɪᴄᴇ:</b> ₹{data['price']}\n"
            f"<b>ʟɪɴᴋ:</b> {data['link']}\n\n"
            f"🔗 <b>sʜᴀʀᴇᴀʙʟᴇ ʟɪɴᴋ:</b>\n<code>{share_link}</code>"
        )
        del ADD_STATE[user_id]
