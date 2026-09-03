import re
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from config import ADMIN_ID, BOT_USERNAME, WEB_APP_URL, CHANNEL_ID
from database.db import (
    add_story_db, 
    delete_story_db, 
    get_all_stories, 
    send_log,
    add_wallet_balance,  # Wallet Balance Incrementor
    get_user_wallet
)

ADD_STATE = {}
DELETE_STATE = {}

def extract_msg_id(text: str):
    """Link या Message ID में से Numeric Message ID निकालने का Helper फ़ंक्शन"""
    text = str(text).strip()
    if text.isdigit():
        return int(text)
    match = re.search(r"/(\d+)$", text)
    return int(match.group(1)) if match else None

# ------------------ ADMIN ADD MONEY TO USER WALLET ------------------
@Client.on_message(filters.command("addmoney") & filters.user(ADMIN_ID) & filters.private, group=1)
async def add_money_handler(client, message):
    args = message.text.split()
    
    if len(args) < 3:
        usage_text = (
            "⚠️ <b>ɪɴᴠᴀʟɪᴅ ᴄᴏᴍᴍᴀɴᴅ ғᴏʀᴍᴀᴛ!</b>\n\n"
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
        await message.reply_text(f"⚠️ Balance update ho gaya, lekin User ko message delivery fail ho gayi (User blocked bot): {e}")

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
        clean_title = s['title'].replace(" ", "_")
        bot_link = f"https://t.me/{BOT_USERNAME}?start=story_{clean_title}"
        f_id = s.get('first_msg_id', 'N/A')
        l_id = s.get('last_msg_id', 'N/A')
        demo = s.get('demo_link', 'N/A')
        
        text += (
            f"{idx}. <b>{s['title']}</b> | ₹{s['price']} | <i>{s['category']}</i>\n"
            f"   📦 <b>Batch Range:</b> Message {f_id} to {l_id}\n"
            f"   🎧 <b>Demo Link:</b> {demo}\n"
            f"   🔗 <b>sʜᴀʀᴇ ʟɪɴᴋ:</b> <code>{bot_link}</code>\n\n"
        )
    
    await message.reply_text(text, disable_web_page_preview=True)

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
    await message.reply_text("<b>[sᴛᴇᴘ 1/8]</b> sᴇʟᴇᴄᴛ ᴛʜᴇ sᴛᴏʀʏ ᴄᴀᴛᴇɢᴏʀʏ:\n<i>(ᴛʏᴘᴇ /cancel ᴛᴏ ᴀʙᴏʀᴛ)</i>", reply_markup=kb)

# 5. Category Selection Callback
@Client.on_callback_query(filters.regex("^setcat_") & filters.user(ADMIN_ID))
async def cat_selected(client, callback):
    ADD_STATE[callback.from_user.id]['category'] = callback.data.split("setcat_")[1]
    ADD_STATE[callback.from_user.id]['step'] = 'TITLE'
    await callback.message.reply_text("<b>[sᴛᴇᴘ 2/8]</b> ᴇɴᴛᴇʀ ᴛʜᴇ sᴛᴏʀʏ ᴛɪᴛʟᴇ:", reply_markup=ForceReply(True))
    await callback.answer()

# 6. Admin Input Wizard
@Client.on_message(filters.private & filters.user(ADMIN_ID) & ~filters.command(["start", "addstory", "deletestory", "allstories", "cancel", "addmoney"]), group=1)
async def wizard_inputs(client, message):
    user_id = message.from_user.id
    
    # --- Delete Process ---
    if user_id in DELETE_STATE:
        title_to_delete = message.text.strip()
        deleted = await delete_story_db(title_to_delete)
        del DELETE_STATE[user_id]
        
        if deleted:
            return await message.reply_text(f"✅ <b>'{title_to_delete}'</b> sᴛᴏʀʏ ᴅᴇʟᴇᴛᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!")
        else:
            return await message.reply_text(f"❌ ɴᴏ sᴛᴏʀʏ ғᴏᴜɴᴅ ᴡɪᴛʜ ᴛʜᴇ ᴛɪᴛʟᴇ <b>'{title_to_delete}'</b>.")

    # --- Add Process ---
    if user_id not in ADD_STATE or 'step' not in ADD_STATE[user_id]:
        message.continue_propagation()
        return
        
    step = ADD_STATE[user_id]['step']
    
    if step == 'TITLE':
        ADD_STATE[user_id]['title'] = message.text.strip().split("\n")[0]
        ADD_STATE[user_id]['step'] = 'PHOTO'
        await message.reply_text("<b>[sᴛᴇᴘ 3/8]</b> sᴇɴᴅ ᴛʜᴇ sᴛᴏʀʏ ᴘᴏsᴛᴇʀ ᴘʜᴏᴛᴏ (ᴏʀ ᴇɴᴛᴇʀ ᴀɴ ɪᴍᴀɢᴇ ᴜʀʟ):", reply_markup=ForceReply(True))
        
    elif step == 'PHOTO':
        if message.photo:
            ADD_STATE[user_id]['photo'] = message.photo.file_id
        elif message.text and (message.text.startswith("http://") or message.text.startswith("https://")):
            ADD_STATE[user_id]['photo'] = message.text.strip()
        else:
            return await message.reply_text("❌ ᴘʟᴇᴀsᴇ sᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ᴘʜᴏᴛᴏ ᴏʀ ɪᴍᴀɢᴇ ᴜʀʟ:")
            
        ADD_STATE[user_id]['step'] = 'PRICE'
        await message.reply_text("<b>[sᴛᴇᴘ 4/8]</b> ᴇɴᴛᴇʀ ᴛʜᴇ ᴘʀɪᴄᴇ (₹):", reply_markup=ForceReply(True))
        
    elif step == 'PRICE':
        if not message.text or not message.text.isdigit():
            return await message.reply_text("❌ ᴘʟᴇᴀsᴇ ᴇɴᴛᴇʀ ᴛʜᴇ ᴘʀɪᴄᴇ ɪɴ ɴᴜᴍʙᴇʀs ᴏɴʟʏ (ᴇ.ɢ., 99):")
        ADD_STATE[user_id]['price'] = int(message.text)
        ADD_STATE[user_id]['step'] = 'DESC'
        await message.reply_text("<b>[sᴛᴇᴘ 5/8]</b> ᴇɴᴛᴇʀ ᴛʜᴇ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:", reply_markup=ForceReply(True))
        
    elif step == 'DESC':
        ADD_STATE[user_id]['desc'] = message.text.strip()
        ADD_STATE[user_id]['step'] = 'DEMO_LINK'
        await message.reply_text(
            "<b>[sᴛᴇᴘ 6/8]</b> ᴇɴᴛᴇʀ ᴛʜᴇ <b>ᴅᴇᴍᴏ ʟɪɴᴋ</b> (URL or Message Link):\n"
            "<i>(अगर डेमो लिंक नहीं देना चाहते तो 'none' लिखें)</i>",
            reply_markup=ForceReply(True)
        )

    elif step == 'DEMO_LINK':
        demo_text = message.text.strip()
        ADD_STATE[user_id]['demo_link'] = None if demo_text.lower() == 'none' else demo_text
        ADD_STATE[user_id]['step'] = 'FIRST_MSG'
        await message.reply_text("<b>[sᴛᴇᴘ 7/8]</b> DB Channel से स्टोरी की <b>FIRST Message ID / Link</b> भेजें:", reply_markup=ForceReply(True))
        
    elif step == 'FIRST_MSG':
        first_id = extract_msg_id(message.text)
        if not first_id:
            return await message.reply_text("❌ Invalid ID/Link! Valid Message ID or Telegram Link enter karein:")
        
        ADD_STATE[user_id]['first_msg_id'] = first_id
        ADD_STATE[user_id]['step'] = 'LAST_MSG'
        await message.reply_text("<b>[sᴛᴇᴘ 8/8]</b> DB Channel से स्टोरी की <b>LAST Message ID / Link</b> भेजें:", reply_markup=ForceReply(True))

    elif step == 'LAST_MSG':
        last_id = extract_msg_id(message.text)
        if not last_id:
            return await message.reply_text("❌ Invalid ID/Link! Valid Message ID or Telegram Link enter karein:")

        data = ADD_STATE[user_id]
        data['last_msg_id'] = last_id
        
        if data['last_msg_id'] < data['first_msg_id']:
            return await message.reply_text("❌ Last Message ID, First Message ID से छोटी नहीं हो सकती। फिर से सही Last ID भेजें:")

        # Internal Get Link for delivery
        clean_title = data['title'].replace(" ", "_")
        data['link'] = f"https://t.me/{BOT_USERNAME}?start=get_{clean_title}"

        # Save to DB (Ensure database/db.py supports 'demo_link' key)
        await add_story_db(data)
        
        bot_share_link = f"https://t.me/{BOT_USERNAME}?start=story_{clean_title}"
        total_files = data['last_msg_id'] - data['first_msg_id'] + 1
        demo_val = data.get('demo_link', 'N/A')
        
        # Log notification
        log_msg = (
            f"<b>➕ ɴᴇᴡ sᴛᴏʀʏ ᴀᴅ模!</b>\n\n"
            f"<b>📌 ᴛɪᴛʟᴇ:</b> {data['title']}\n"
            f"<b>📂 ᴄᴀᴛᴇɢᴏʀʏ:</b> {data['category']}\n"
            f"<b>💰 ᴘʀɪᴄᴇ:</b> ₹{data['price']}\n"
            f"<b>🎧 ᴅᴇᴍᴏ:</b> {demo_val}\n"
            f"<b>📦 ғɪʟᴇs:</b> {total_files} (Msg {data['first_msg_id']} to {data['last_msg_id']})\n\n"
            f"🔗 <b>sʜᴀʀᴇᴀʙʟᴇ ʟɪɴᴋ:</b>\n<code>{bot_share_link}</code>"
        )
        try:
            await send_log(client, log_msg)
        except Exception:
            pass
        
        # Confirmation to admin
        await message.reply_text(
            f"✅ <b>sᴛᴏʀʏ ᴀᴅᴅᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
            f"<b>ᴛɪᴛʟᴇ:</b> {data['title']}\n"
            f"<b>ᴘʀɪᴄᴇ:</b> ₹{data['price']}\n"
            f"<b>ᴅᴇᴍᴏ:</b> {demo_val}\n"
            f"<b>ᴛᴏᴛᴀʟ ғɪʟᴇs:</b> {total_files}\n\n"
            f"🔗 <b>sʜᴀʀᴇᴀʙʟᴇ ʟɪɴᴋ:</b>\n<code>{bot_share_link}</code>",
            disable_web_page_preview=True
        )
        del ADD_STATE[user_id]
