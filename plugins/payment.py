import urllib.parse
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from config import UPI_ID, ADMIN_ID, BOT_USERNAME, LOG_CHANNEL
from database.db import get_story_by_title, add_user_purchase, add_wallet_balance

# Waiting States
PAYMENT_WAITING = {}
WALLET_TOPUP_WAITING = {}

# ---------------- CANCEL PROCESS HANDLERS ----------------

# Cancel Callback Handler
@Client.on_callback_query(filters.regex("^cancel_payment_process$"))
async def cancel_payment_callback(client, callback):
    user_id = callback.from_user.id
    
    # Remove from all waiting dictionaries
    PAYMENT_WAITING.pop(user_id, None)
    WALLET_TOPUP_WAITING.pop(user_id, None)
    
    try:
        await callback.message.delete()
    except Exception:
        pass
        
    await callback.message.reply_text("❌ <b>ᴘᴀʏᴍᴇɴᴛ / ᴛᴏᴘ-ᴜᴘ ᴘʀᴏᴄᴇss ᴄᴀɴᴄᴇʟʟᴇᴅ.</b>")
    await callback.answer("Process Cancelled!")

# Text Cancel Command Handler
@Client.on_message(filters.private & filters.command(["cancel"]), group=1)
async def cancel_payment_command(client, message):
    user_id = message.from_user.id
    
    if user_id in PAYMENT_WAITING or user_id in WALLET_TOPUP_WAITING:
        PAYMENT_WAITING.pop(user_id, None)
        WALLET_TOPUP_WAITING.pop(user_id, None)
        await message.reply_text("❌ <b>ᴘᴀʏᴍᴇɴᴛ / ᴛᴏᴘ-ᴜᴘ ᴘʀᴏᴄᴇss ᴄᴀɴᴄᴇʟʟᴇᴅ.</b>")
    else:
        await message.reply_text("⚠️ <b>No active payment process to cancel.</b>")

# 1. View Story
@Client.on_callback_query(filters.regex("^view_"))
async def view_story(client, callback):
    title = callback.data.split("view_")[1].replace("_", " ")
    story = await get_story_by_title(title)
    if not story:
        return await callback.answer("❌ sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ!", show_alert=True)
        
    clean_title = story['title'].strip().split("\n")[0]
    encoded_title = clean_title.replace(" ", "_")
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("💳 ʙᴜʏ ɴᴏᴡ", style=enums.ButtonStyle.PRIMARY, callback_data=f"buy_{encoded_title}_{story['price']}")]])
    
    caption_text = (
        f"♨️ <b>Story :</b> {clean_title}\n"
        f"🔰 <b>Status :</b> {story.get('status', 'Completed')}\n"
        f"🖥️ <b>Platform :</b> {story.get('category', 'Pocket FM')}\n"
        f"🧩 <b>Genre :</b> {story.get('genre', 'Drama')}\n"
        f"🎬 <b>Episodes :</b> {story.get('episodes', 'N/A')}\n\n"
        f"░▒▓█ PRICE - ₹{story['price']} █▓▒░"
    )
    
    try:
        await callback.message.reply_photo(
            photo=story.get('photo', 'https://picsum.photos/400/200'),
            caption=caption_text,
            reply_markup=btn
        )
    except Exception:
        await callback.message.reply_text(caption_text, reply_markup=btn)
        
    await callback.answer()

# 2. Generate QR Code for Story Purchase
@Client.on_callback_query(filters.regex("^buy_"))
async def generate_qr(client, callback):
    try:
        raw_data = callback.data[4:] # Remove 'buy_'
        clean_title, price = raw_data.rsplit("_", 1) # Split from the last underscore
        story_title = clean_title.replace("_", " ")
    except Exception:
        return await callback.answer("❌ ᴇʀʀᴏʀ ᴘᴀʀsɪɴɢ ᴘᴀʏᴍᴇɴᴛ ᴅᴀᴛᴀ!", show_alert=True)
    
    upi_link = f"upi://pay?pa={UPI_ID}&pn=StorySeller&am={price}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_link)}"
    
    caption = (
        f"💳 <b>ᴏʀᴅᴇʀ ᴄʜᴇᴄᴋᴏᴜᴛ:</b> {story_title}\n"
        f"💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{price}\n\n"
        f"📌 <b>ᴜᴘɪ ɪᴅ:</b> <code>{UPI_ID}</code>\n\n"
        f"👇 ᴀғᴛᴇʀ ᴍᴀᴋɪɴɢ ᴛʜᴇ ᴘᴀʏᴍᴇɴᴛ, ᴄʟɪᴄᴋ ᴏɴ <b>ᴄᴏɴғɪʀᴍ ᴘᴀʏᴍᴇɴᴛ</b> ʙᴇʟᴏᴡ."
    )
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ ᴄᴏɴғɪʀᴍ ᴘᴀʏᴍᴇɴᴛ", style=enums.ButtonStyle.PRIMARY, callback_data=f"sent_{clean_title}_{price}")],
        [InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
    ])
    await callback.message.reply_photo(photo=qr_url, caption=caption, reply_markup=btn)
    await callback.answer()

# ---------------- WALLET TOPUP FLOW ----------------

# 3. Topup Callback Handler -> Asks Amount
@Client.on_callback_query(filters.regex("^add_wallet_funds$"))
async def start_wallet_topup(client, callback):
    user_id = callback.from_user.id
    WALLET_TOPUP_WAITING[user_id] = True
    
    cancel_btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
    ])
    
    await callback.message.reply_text(
        "💵 <b>ᴇɴᴛᴇʀ ᴛᴏᴘ-ᴜᴘ ᴀᴍᴏᴜɴᴛ:</b>\n\n"
        "ᴘʟᴇᴀsᴇ ᴛʏᴘᴇ ᴛʜᴇ ᴀᴍᴏᴜɴᴛ (ɪɴ ₹) ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴀᴅᴅ ᴛᴏ ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ:",
        reply_markup=cancel_btn
    )
    await callback.answer()

# 4. Receive Amount Input & Send Wallet QR Code
@Client.on_message(filters.private & filters.text & ~filters.command(["start", "cancel"]), group=3)
async def process_wallet_amount(client, message):
    user_id = message.from_user.id
    
    if user_id not in WALLET_TOPUP_WAITING:
        message.continue_propagation()
        return

    amount_text = message.text.strip()
    if not amount_text.isdigit() or float(amount_text) <= 0:
        return await message.reply_text("❌ <b>Invalid Amount! Please enter numbers only (e.g. 50, 100, 200).</b>")
    
    price = float(amount_text)
    del WALLET_TOPUP_WAITING[user_id]
    
    upi_link = f"upi://pay?pa={UPI_ID}&pn=WalletTopup&am={price}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_link)}"
    
    caption = (
        f"👛 <b>ᴡᴀʟʟᴇᴛ ᴛᴏᴘ-ᴜᴘ:</b> ₹{price}\n"
        f"💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{price}\n\n"
        f"📌 <b>ᴜᴘɪ ɪᴅ:</b> <code>{UPI_ID}</code>\n\n"
        f"👇 ᴀғᴛᴇʀ ᴍᴀᴋɪɴɢ ᴛʜᴇ ᴘᴀʏᴍᴇɴᴛ, ᴄʟɪᴄᴋ ᴏɴ <b>ᴄᴏɴғɪʀᴍ ᴘᴀʏᴍᴇɴᴛ</b> ʙᴇʟᴏᴡ."
    )
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ ᴄᴏɴғɪʀᴍ ᴘᴀʏᴍᴇɴᴛ", style=enums.ButtonStyle.PRIMARY, callback_data=f"sent_WalletTopup_{price}")],
        [InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
    ])
    await message.reply_photo(photo=qr_url, caption=caption, reply_markup=btn)

# ---------------- SCREENSHOT & APPROVAL HANDLERS ----------------

# 5. Ask User for Screenshot
@Client.on_callback_query(filters.regex("^sent_"))
async def ask_screenshot(client, callback):
    try:
        raw_data = callback.data[5:] # Remove 'sent_'
        clean_title, price = raw_data.rsplit("_", 1)
        story_title = clean_title.replace("_", " ")
    except Exception:
        return await callback.answer("❌ ᴇʀʀᴏʀ ᴘᴀʀsɪɴɢ ᴅᴀᴛᴀ!", show_alert=True)
        
    user_id = callback.from_user.id
    PAYMENT_WAITING[user_id] = {"title": story_title, "price": price}
    
    cancel_btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", callback_data="cancel_payment_process", style=enums.ButtonStyle.DANGER)]
    ])
    
    await callback.message.reply_text(
        "📸 <b>ᴘʟᴇᴀsᴇ sᴇɴᴅ ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ sᴄʀᴇᴇɴsʜᴏᴛ:</b>\n\n"
        "sᴇɴᴅ ʏᴏᴜʀ sᴄʀᴇᴇɴsʜᴏᴛ ᴀs ᴀ ᴘʜᴏᴛᴏ ɪɴ ᴛʜɪs ᴄʜᴀᴛ.",
        reply_markup=cancel_btn
    )
    await callback.answer()

# 6. Capture Screenshot Photo & Send to Admin and Log Channel
@Client.on_message(filters.private & filters.photo, group=2)
async def receive_screenshot(client, message):
    user_id = message.from_user.id
    
    if user_id not in PAYMENT_WAITING:
        return
        
    data = PAYMENT_WAITING[user_id]
    title = data['title']
    price = data['price']
    user = message.from_user
    
    is_wallet = (title == "WalletTopup")
    req_type = "👛 WALLET TOP-UP" if is_wallet else f"📖 STORY: {title}"
    
    admin_text = (
        f"🚨 <b>ɴᴇᴡ ᴘᴀʏᴍᴇɴᴛ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ʀᴇǫᴜᴇsᴛ!</b>\n\n"
        f"👤 <b>ᴜsᴇʀ:</b> {user.first_name} (@{user.username if user.username else 'N/A'})\n"
        f"🆔 <b>ᴜsᴇʀ ɪᴅ:</b> <code>{user.id}</code>\n"
        f"📌 <b>ᴛʏᴘᴇ:</b> {req_type}\n"
        f"💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{price}"
    )
    
    clean_title = title.replace(" ", "_")
    btn = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ ᴀᴘᴘʀᴏᴠᴇ", callback_data=f"app_{user.id}_{clean_title}_{price}"),
            InlineKeyboardButton("❌ ʀᴇᴊᴇᴄᴛ", callback_data=f"rej_{user.id}_{clean_title}")
        ]
    ])
    
    # 1. Send photo to ADMIN
    await client.send_photo(
        chat_id=ADMIN_ID,
        photo=message.photo.file_id,
        caption=admin_text,
        reply_markup=btn
    )

    # 2. Send photo to LOG_CHANNEL for record
    if LOG_CHANNEL and LOG_CHANNEL != 0:
        try:
            log_text = (
                f"📥 <b>ɴᴇᴡ ᴘᴀʏᴍᴇɴᴛ ʀᴇǫᴜᴇsᴛ ʀᴇᴄᴇɪᴠᴇᴅ</b>\n\n"
                f"👤 <b>User:</b> {user.first_name} (<code>{user.id}</code>)\n"
                f"📌 <b>Type:</b> {req_type}\n"
                f"💰 <b>Amount:</b> ₹{price}\n"
                f"⏳ <b>Status:</b> Pending Admin Verification"
            )
            await client.send_photo(
                chat_id=LOG_CHANNEL,
                photo=message.photo.file_id,
                caption=log_text
            )
        except Exception as e:
            print(f"Log Channel Error: {e}")
    
    await message.reply_text("✅ <b>sᴄʀᴇᴇɴsʜᴏᴛ ʀᴇᴄᴇɪᴠᴇᴅ!</b>\nʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ɪs ᴜɴᴅᴇʀ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ʙʏ ᴀᴅᴍɪɴ.")
    del PAYMENT_WAITING[user_id]

# 7. Approve Payment Handler (Auto Detects Wallet vs Story Purchase & Logs with Photo)
@Client.on_callback_query(filters.regex("^app_") & filters.user(ADMIN_ID))
async def approve_order(client, callback):
    data = callback.data.split("_")
    user_id = int(data[1])
    price = float(data[-1])
    title = "_".join(data[2:-1]).replace("_", " ")
    
    photo_file_id = callback.message.photo.file_id if callback.message.photo else None
    
    # CASE 1: WALLET TOPUP APPROVAL
    if title == "WalletTopup":
        new_balance = await add_wallet_balance(user_id, price)
        try:
            await client.send_message(
                chat_id=user_id,
                text=(
                    f"🎉 <b>ᴡᴀʟʟᴇᴛ ᴛᴏᴘ-ᴜᴘ ᴀᴘᴘʀᴏᴠᴇᴅ!</b>\n\n"
                    f"💰 <b>ᴀᴅᴅᴇᴅ:</b> ₹{price}\n"
                    f"👛 <b>ɴᴇᴡ ʙᴀʟᴀɴᴄᴇ:</b> ₹{new_balance}\n\n"
                    f"<i>Now you can purchase stories using your wallet!</i>"
                )
            )
            await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n✅ <b>WALLETTOPUP APPROVED</b>")
            
            # Send Approval Log with Photo to LOG_CHANNEL
            if LOG_CHANNEL and LOG_CHANNEL != 0:
                try:
                    log_text = (
                        f"✅ <b>ᴘᴀʏᴍᴇɴᴛ ᴀᴘᴘʀᴏᴠᴇᴅ (ᴡᴀʟʟᴇᴛ ᴛᴏᴘ-ᴜᴘ)</b>\n\n"
                        f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
                        f"💰 <b>Amount Added:</b> ₹{price}\n"
                        f"👛 <b>Updated Balance:</b> ₹{new_balance}\n"
                        f"👑 <b>Approved By:</b> Admin"
                    )
                    if photo_file_id:
                        await client.send_photo(chat_id=LOG_CHANNEL, photo=photo_file_id, caption=log_text)
                    else:
                        await client.send_message(chat_id=LOG_CHANNEL, text=log_text)
                except Exception as log_err:
                    print(f"Log Error: {log_err}")

            return await callback.answer("Wallet Topup Approved & Balance Added!", show_alert=True)
        except Exception as e:
            return await callback.answer(f"Error notifying user: {e}", show_alert=True)

    # CASE 2: DIRECT STORY PURCHASE APPROVAL
    story = await get_story_by_title(title)
    if not story:
        return await callback.answer("❌ sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ ɪɴ ᴅᴀᴛᴀʙᴀsᴇ!", show_alert=True)
    
    clean_title = story['title'].strip().split("\n")[0]
    encoded_title = clean_title.replace(" ", "_")
    delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"

    # Save to Purchases DB
    await add_user_purchase(user_id, clean_title, story_link=delivery_link)

    access_btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (Unlocked)", style=enums.ButtonStyle.PRIMARY, url=delivery_link)]
    ])
    
    try:
        await client.send_message(
            chat_id=user_id,
            text=(
                f"🎉 <b>ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ʜᴀs ʙᴇᴇɴ ᴀᴘᴘʀᴏᴠᴇᴅ!</b>\n\n"
                f"📖 <b>sᴛᴏʀʏ:</b> {clean_title}\n\n"
                f"ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴀᴄᴄᴇss ʏᴏᴜʀ ᴄᴏɴᴛᴇɴᴛ:"
            ),
            reply_markup=access_btn,
            protect_content=True
        )
        await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n✅ <b>ᴀᴘᴘʀᴏᴠᴇᴅ ʙʏ ᴀᴅᴍɪɴ</b>")
        
        # Send Approval Log with Photo to LOG_CHANNEL
        if LOG_CHANNEL and LOG_CHANNEL != 0:
            try:
                log_text = (
                    f"✅ <b>ᴘᴀʏᴍᴇɴᴛ ᴀᴘᴘʀᴏᴠᴇᴅ (sᴛᴏʀʏ ᴘᴜʀᴄʜᴀsᴇ)</b>\n\n"
                    f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
                    f"📖 <b>Story:</b> {clean_title}\n"
                    f"💰 <b>Amount Paid:</b> ₹{price}\n"
                    f"👑 <b>Approved By:</b> Admin"
                )
                if photo_file_id:
                    await client.send_photo(chat_id=LOG_CHANNEL, photo=photo_file_id, caption=log_text)
                else:
                    await client.send_message(chat_id=LOG_CHANNEL, text=log_text)
            except Exception as log_err:
                print(f"Log Error: {log_err}")

        await callback.answer("Approved & Saved to DB Successfully!", show_alert=True)
    except Exception as e:
        await callback.answer(f"Error sending message to user: {e}", show_alert=True)

# 8. Reject Payment Handler (Logs with Photo)
@Client.on_callback_query(filters.regex("^rej_") & filters.user(ADMIN_ID))
async def reject_order(client, callback):
    data = callback.data.split("_")
    user_id = int(data[1])
    title = "_".join(data[2:]).replace("_", " ")
    
    photo_file_id = callback.message.photo.file_id if callback.message.photo else None
    
    try:
        await client.send_message(
            chat_id=user_id,
            text=(
                f"❌ <b>ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ʜᴀs ʙᴇᴇɴ ʀᴇᴊᴇᴄᴛᴇᴅ!</b>\n\n"
                f"📌 <b>ITEM:</b> {title}\n\n"
                f"ɪғ ʏᴏᴜ ʙᴇʟɪᴇᴠᴇ ᴛʜɪs ɪs ᴀ ᴍɪsᴛᴀᴋᴇ, ᴘʟᴇᴀsᴇ ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ."
            )
        )
        await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n❌ <b>ʀᴇᴊᴇᴄᴛᴇᴅ ʙʏ ᴀᴅᴍɪɴ</b>")
        
        # Send Rejection Log with Photo to LOG_CHANNEL
        if LOG_CHANNEL and LOG_CHANNEL != 0:
            try:
                log_text = (
                    f"❌ <b>ᴘᴀʏᴍᴇɴᴛ ʀᴇᴊᴇᴄᴛᴇᴅ</b>\n\n"
                    f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
                    f"📌 <b>Item/Type:</b> {title}\n"
                    f"👑 <b>Rejected By:</b> Admin"
                )
                if photo_file_id:
                    await client.send_photo(chat_id=LOG_CHANNEL, photo=photo_file_id, caption=log_text)
                else:
                    await client.send_message(chat_id=LOG_CHANNEL, text=log_text)
            except Exception as log_err:
                print(f"Log Error: {log_err}")

        await callback.answer("Payment Rejected!", show_alert=True)
    except Exception as e:
        await callback.answer(f"Error sending rejection to user: {e}", show_alert=True)
