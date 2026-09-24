import urllib.parse
import re
import imaplib
import email
import time
from datetime import datetime
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import UPI_ID, ADMIN_ID, BOT_USERNAME, LOG_CHANNEL, GMAIL_USER, GMAIL_PASS
from database.db import get_story_by_title, add_user_purchase, add_wallet_balance

# Global Dictionaries & DB for UTR Lock
ACTIVE_PAYMENTS = {}        # Stores active session timing and order data
WALLET_TOPUP_WAITING = {}   # Stores wallet state
USED_TRANSACTIONS = set()   # Duplicate UTR / Txn ID locking memory

# Helper Function: Fetch & Verify FamPay/FamApp Email from Gmail
def verify_fampay_email(txn_id, expected_amount):
    if not GMAIL_USER or not GMAIL_PASS:
        return False, "Gmail credentials not configured."
        
    try:
        # Connect to Gmail via IMAP
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_PASS)
        mail.select("inbox")
        
        # Search for recent emails containing the Txn ID
        status, messages = mail.search(None, f'TEXT "{txn_id}"')
        if status != "OK" or not messages[0]:
            mail.logout()
            return False, "Transaction ID not found yet.\n <b>TRY AFTER SOME TIME</b>"
            
        email_ids = messages[0].split()
        for e_id in reversed(email_ids): # Check newest emails first
            _, msg_data = mail.fetch(e_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    else:
                        body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                    
                    # Verify Transaction ID and Amount in Email Content
                    if txn_id in body:
                        # Find amount using Regex (e.g. ₹168.92 or Rs 168)
                        amount_matches = re.findall(r"(?:₹|Rs\.?)\s*([\d\.]+)", body)
                        for amt_str in amount_matches:
                            try:
                                if abs(float(amt_str) - float(expected_amount)) < 1.0: # Match amount
                                    mail.logout()
                                    return True, "Payment Verified Successfully!"
                            except ValueError:
                                continue
        mail.logout()
        return False, "Transaction ID found, but amount mismatched."
    except Exception as e:
        return False, f"Email Check Error: {str(e)}"

# ---------------- CANCEL & SHOW UPI HANDLERS ----------------

@Client.on_callback_query(filters.regex("^cancel_payment_process$"))
async def cancel_payment_callback(client, callback):
    user_id = callback.from_user.id
    ACTIVE_PAYMENTS.pop(user_id, None)
    WALLET_TOPUP_WAITING.pop(user_id, None)
    
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.reply_text("❌ <b>ᴘᴀʏᴍᴇɴᴛ / ᴛᴏᴘ-ᴜᴘ ᴘʀᴏᴄᴇss ᴄᴀɴᴄᴇʟʟᴇᴅ.</b>")
    await callback.answer("Process Cancelled!")

# Toggle UPI ID Visibility
@Client.on_callback_query(filters.regex("^show_upi_id$"))
async def show_upi_id(client, callback):
    await callback.answer(f"📌 UPI ID: {UPI_ID}", show_alert=True)

# ---------------- 1. VIEW STORY & QR GENERATION ----------------

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

@Client.on_callback_query(filters.regex("^buy_"))
async def generate_qr(client, callback):
    try:
        raw_data = callback.data[4:]
        clean_title, price = raw_data.rsplit("_", 1)
        story_title = clean_title.replace("_", " ")
    except Exception:
        return await callback.answer("❌ ᴇʀʀᴏʀ ᴘᴀʀsɪɴɢ ᴘᴀʏᴍᴇɴᴛ ᴅᴀᴛᴀ!", show_alert=True)
    
    user_id = callback.from_user.id
    ACTIVE_PAYMENTS[user_id] = {
        "title": story_title,
        "price": float(price),
        "timestamp": time.time(),
        "type": "STORY"
    }

    upi_link = f"upi://pay?pa={UPI_ID}&pn=StorySeller&am={price}&cu=INR"
    # Optimized QR size (250x250) with quiet margin (margin=15) to fix "Format Not Found" scanning issues
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&margin=15&data={urllib.parse.quote(upi_link)}"
    
    caption = (
        f"⚡ <b>ᴀᴜᴛᴏᴍᴀᴛɪᴄ ᴘᴀʏᴍᴇɴᴛ ᴄʜᴇᴄᴋᴏᴜᴛ</b>\n\n"
        f"📖 <b>sᴛᴏʀʏ:</b> {story_title}\n"
        f"💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{price}\n"
        f"⏳ <b>ᴛɪᴍᴇ ʟɪᴍɪᴛ:</b> 10 Minutes\n\n"
        f"📲 <i>Scan the QR Code below to make instant payment. Verification is fully automatic!</i>"
    )
    
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ ᴠᴇʀɪғʏ ᴘᴀʏᴍᴇɴᴛ (Auto)", style=enums.ButtonStyle.SUCCESS, callback_data=f"auto_verify_{user_id}")],
        [InlineKeyboardButton("👁️ sʜᴏᴡ ᴜᴘɪ ɪᴅ", callback_data="show_upi_id"), InlineKeyboardButton("📩 ᴍᴀɴᴜᴀʟ / ᴀᴅᴍɪɴ", callback_data=f"sent_{clean_title}_{price}")],
        [InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
    ])
    
    await callback.message.reply_photo(photo=qr_url, caption=caption, reply_markup=btn)
    await callback.answer()

# ---------------- 2. AUTO-VERIFICATION TRIGGER ----------------

@Client.on_callback_query(filters.regex("^auto_verify_"))
async def start_auto_verify(client, callback):
    user_id = callback.from_user.id
    session = ACTIVE_PAYMENTS.get(user_id)
    
    if not session:
        return await callback.answer("⏰ Payment Expired! Please try again.", show_alert=True)
        
    # Check 10 Minute Timer
    if time.time() - session['timestamp'] > 600:
        ACTIVE_PAYMENTS.pop(user_id, None)
        return await callback.answer("⌛ Time limit of 10 minutes exceeded! payment expired.", show_alert=True)
        
    # Ask for Transaction ID
    await callback.message.reply_text(
        "📝 <b>ᴇɴᴛᴇʀ ʏᴏᴜʀ ғᴀᴍᴘᴀʏ / ᴜᴘɪ ᴛʀᴀɴsᴀᴄᴛɪᴏɴ ɪᴅ:</b>\n\n"
        "Please paste your FamPay Transaction ID (e.g., <code>FMPIB665989150...</code>) to instantly verify payment:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", callback_data="cancel_payment_process")]])
    )
    session['awaiting_txnid'] = True
    await callback.answer()

# Text Listener for Transaction ID
@Client.on_message(filters.private & filters.text & ~filters.command(["start", "cancel"]), group=1)
async def process_auto_txn_id(client, message):
    user_id = message.from_user.id
    session = ACTIVE_PAYMENTS.get(user_id)
    
    if not session or not session.get('awaiting_txnid'):
        message.continue_propagation()
        return

    txn_id = message.text.strip()
    price = session['price']
    title = session['title']
    
    # 1. Check Timer
    if time.time() - session['timestamp'] > 600:
        ACTIVE_PAYMENTS.pop(user_id, None)
        return await message.reply_text("❌ <b>payment Expired!</b> 10-minute timer completed. Please initiate purchase again.")

    # 2. Check Duplicate Lock
    if txn_id in USED_TRANSACTIONS:
        return await message.reply_text("⚠️ <b>This Transaction ID has already been used!</b> Fraudulent attempts are logged.")

    wait_msg = await message.reply_text("🔄 <b>ᴠᴇʀɪғʏɪɴɢ ᴘᴀʏᴍᴇɴᴛ...</b>\n<i>Please wait a few seconds.</i>")
    
    # 3. Check via Gmail IMAP
    is_valid, msg = verify_fampay_email(txn_id, price)
    
    if is_valid:
        USED_TRANSACTIONS.add(txn_id) # Lock Txn ID
        ACTIVE_PAYMENTS.pop(user_id, None)
        await wait_msg.delete()
        
        # Automatic Fullfilment
        if session['type'] == "WALLET":
            new_bal = await add_wallet_balance(user_id, price)
            await message.reply_text(f"🎉 <b>ᴀᴜᴛᴏ-ᴠᴇʀɪғɪᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n💰 Added ₹{price} to Wallet.\n👛 New Balance: ₹{new_bal}")
            
            # Send Log to Channel & Admin
            if LOG_CHANNEL and LOG_CHANNEL != 0:
                await client.send_message(
                    LOG_CHANNEL, 
                    f"⚡ <b>[AUTO-PAYMENT SUCCESS] WALLET TOPUP</b>\n\n👤 <b>User:</b> {message.from_user.first_name} (<code>{user_id}</code>)\n💰 <b>Amount:</b> ₹{price}\n🔑 <b>Txn ID:</b> <code>{txn_id}</code>"
                )
        else:
            story = await get_story_by_title(title)
            clean_title = story['title'].strip().split("\n")[0]
            encoded_title = clean_title.replace(" ", "_")
            delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"
            
            await add_user_purchase(user_id, clean_title, story_link=delivery_link)
            access_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (Unlocked)", style=enums.ButtonStyle.PRIMARY, url=delivery_link)]])
            
            await message.reply_text(
                f"🎉 <b>ᴀᴜᴛᴏ-ᴠᴇʀɪғɪᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n📖 <b>Story:</b> {clean_title}\n💰 <b>Paid:</b> ₹{price}\n\nClick below to access:",
                reply_markup=access_btn,
                protect_content=True
            )
            
            # Log to Channel
            if LOG_CHANNEL and LOG_CHANNEL != 0:
                await client.send_message(
                    LOG_CHANNEL, 
                    f"⚡ <b>[AUTO-PAYMENT SUCCESS] STORY BOUGHT</b>\n\n👤 <b>User:</b> {message.from_user.first_name} (<code>{user_id}</code>)\n📖 <b>Story:</b> {clean_title}\n💰 <b>Amount:</b> ₹{price}\n🔑 <b>Txn ID:</b> <code>{txn_id}</code>"
                )
    else:
        await wait_msg.edit_text(
            f"❌ <b>ᴀᴜᴛᴏ-ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ғᴀɪʟᴇᴅ!</b>\nReason: {msg}\n\n"
            "If you have paid, please click <b>Contact Admin / Send Screenshot</b> below to verify manually.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📩 Contact Admin / Manual", callback_data=f"sent_{title.replace(' ', '_')}_{price}")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_payment_process")]
            ])
        )

# ---------------- WALLET TOPUP FLOW ----------------

@Client.on_callback_query(filters.regex("^add_wallet_funds$"))
async def start_wallet_topup(client, callback):
    user_id = callback.from_user.id
    WALLET_TOPUP_WAITING[user_id] = True
    await callback.message.reply_text(
        "💵 <b>ᴇɴᴛᴇʀ ᴛᴏᴘ-ᴜᴘ ᴀᴍᴏᴜɴᴛ:</b>\nPlease type amount (in ₹):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", callback_data="cancel_payment_process")]])
    )
    await callback.answer()

@Client.on_message(filters.private & filters.text & ~filters.command(["start", "cancel"]), group=3)
async def process_wallet_amount(client, message):
    user_id = message.from_user.id
    if user_id not in WALLET_TOPUP_WAITING:
        message.continue_propagation()
        return

    amount_text = message.text.strip()
    if not amount_text.isdigit() or float(amount_text) <= 0:
        return await message.reply_text("❌ <b>Invalid Amount!</b>")
    
    price = float(amount_text)
    del WALLET_TOPUP_WAITING[user_id]
    
    ACTIVE_PAYMENTS[user_id] = {
        "title": "WalletTopup",
        "price": price,
        "timestamp": time.time(),
        "type": "WALLET"
    }

    upi_link = f"upi://pay?pa={UPI_ID}&pn=WalletTopup&am={price}&cu=INR"
    # Optimized Wallet QR size & margin
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&margin=15&data={urllib.parse.quote(upi_link)}"
    
    caption = (
        f"👛 <b>ᴡᴀʟʟᴇᴛ ᴛᴏᴘ-ᴜᴘ:</b> ₹{price}\n"
        f"⏳ <b>ᴛɪᴍᴇ ʟɪᴍɪᴛ:</b> 10 Minutes\n\n"
        f"👇 Scan & click Verify Payment."
    )
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ ᴠᴇʀɪғʏ ᴘᴀʏᴍᴇɴᴛ (Auto)", style=enums.ButtonStyle.SUCCESS, callback_data=f"auto_verify_{user_id}")],
        [InlineKeyboardButton("👁️ sʜᴏᴡ ᴜᴘɪ ɪᴅ", callback_data="show_upi_id"), InlineKeyboardButton("📩 ᴍᴀɴᴜᴀʟ / ᴀᴅᴍɪɴ", callback_data=f"sent_WalletTopup_{price}")],
        [InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
    ])
    await message.reply_photo(photo=qr_url, caption=caption, reply_markup=btn)

# ---------------- MANUAL SCREENSHOT & ADMIN APPROVAL ----------------

@Client.on_callback_query(filters.regex("^sent_"))
async def ask_screenshot(client, callback):
    try:
        raw_data = callback.data[5:]
        clean_title, price = raw_data.rsplit("_", 1)
        story_title = clean_title.replace("_", " ")
    except Exception:
        return await callback.answer("❌ Error parsing data!", show_alert=True)
        
    user_id = callback.from_user.id
    ACTIVE_PAYMENTS[user_id] = {"title": story_title, "price": price, "manual": True}
    
    await callback.message.reply_text(
        "📸 <b>sᴇɴᴅ ᴘᴀʏᴍᴇɴᴛ sᴄʀᴇᴇɴsʜᴏᴛ:</b>\n\nPlease send your payment screenshot photo in this chat.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", callback_data="cancel_payment_process")]])
    )
    await callback.answer()

@Client.on_message(filters.private & filters.photo, group=2)
async def receive_screenshot(client, message):
    user_id = message.from_user.id
    if user_id not in ACTIVE_PAYMENTS or not ACTIVE_PAYMENTS[user_id].get("manual"):
        return
        
    data = ACTIVE_PAYMENTS[user_id]
    title = data['title']
    price = data['price']
    user = message.from_user
    
    is_wallet = (title == "WalletTopup")
    req_type = "👛 WALLET TOP-UP" if is_wallet else f"📖 STORY: {title}"
    
    admin_text = (
        f"🚨 <b>ᴍᴀɴᴜᴀʟ ᴘᴀʏᴍᴇɴᴛ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ʀᴇǫᴜᴇsᴛ!</b>\n\n"
        f"👤 <b>User:</b> {user.first_name} (@{user.username if user.username else 'N/A'})\n"
        f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
        f"📌 <b>Type:</b> {req_type}\n"
        f"💰 <b>Amount:</b> ₹{price}"
    )
    
    clean_title = title.replace(" ", "_")
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ ᴀᴘᴘʀᴏᴠᴇ", callback_data=f"app_{user.id}_{clean_title}_{price}"), InlineKeyboardButton("❌ ʀᴇᴊᴇᴄᴛ", callback_data=f"rej_{user.id}_{clean_title}")]
    ])
    
    await client.send_photo(chat_id=ADMIN_ID, photo=message.photo.file_id, caption=admin_text, reply_markup=btn)

    if LOG_CHANNEL and LOG_CHANNEL != 0:
        try:
            log_text = f"📥 <b>[MANUAL REQUEST]</b>\n👤 User: {user.first_name} (<code>{user.id}</code>)\n📌 Item: {req_type}\n💰 Amount: ₹{price}\n⏳ Status: Pending Admin Verification"
            await client.send_photo(chat_id=LOG_CHANNEL, photo=message.photo.file_id, caption=log_text)
        except Exception as e:
            print(f"Log Error: {e}")
            
    await message.reply_text("✅ <b>Screenshot received!</b> Admin will review and approve shortly.")
    ACTIVE_PAYMENTS.pop(user_id, None)

# Admin Approval / Rejection Handlers
@Client.on_callback_query(filters.regex("^app_") & filters.user(ADMIN_ID))
async def approve_order(client, callback):
    data = callback.data.split("_")
    user_id = int(data[1])
    price = float(data[-1])
    title = "_".join(data[2:-1]).replace("_", " ")
    
    photo_file_id = callback.message.photo.file_id if callback.message.photo else None
    
    if title == "WalletTopup":
        new_balance = await add_wallet_balance(user_id, price)
        try:
            await client.send_message(chat_id=user_id, text=f"🎉 <b>ᴡᴀʟʟᴇᴛ ᴛᴏᴘ-ᴜᴘ ᴀᴘᴘʀᴏᴠᴇᴅ!</b>\n💰 Added: ₹{price}\n👛 Balance: ₹{new_balance}")
            await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n✅ <b>APPROVED BY ADMIN</b>")
            if LOG_CHANNEL and LOG_CHANNEL != 0:
                await client.send_message(LOG_CHANNEL, f"✅ <b>[MANUAL APPROVED] WALLET</b>\n👤 User: <code>{user_id}</code>\n💰 Amount: ₹{price}")
            return await callback.answer("Wallet Approved!", show_alert=True)
        except Exception as e:
            return await callback.answer(f"Error: {e}", show_alert=True)

    story = await get_story_by_title(title)
    if not story:
        return await callback.answer("❌ Story not found!", show_alert=True)
    
    clean_title = story['title'].strip().split("\n")[0]
    encoded_title = clean_title.replace(" ", "_")
    delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"

    await add_user_purchase(user_id, clean_title, story_link=delivery_link)
    access_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (Unlocked)", style=enums.ButtonStyle.PRIMARY, url=delivery_link)]])
    
    try:
        await client.send_message(
            chat_id=user_id,
            text=f"🎉 <b>ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ʜᴀs ʙᴇᴇɴ ᴀᴘᴘʀᴏᴠᴇᴅ!</b>\n📖 Story: {clean_title}",
            reply_markup=access_btn,
            protect_content=True
        )
        await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n✅ <b>APPROVED BY ADMIN</b>")
        if LOG_CHANNEL and LOG_CHANNEL != 0:
            await client.send_message(LOG_CHANNEL, f"✅ <b>[MANUAL APPROVED] STORY</b>\n👤 User: <code>{user_id}</code>\n📖 Story: {clean_title}")
        await callback.answer("Approved!", show_alert=True)
    except Exception as e:
        await callback.answer(f"Error: {e}", show_alert=True)

@Client.on_callback_query(filters.regex("^rej_") & filters.user(ADMIN_ID))
async def reject_order(client, callback):
    data = callback.data.split("_")
    user_id = int(data[1])
    title = "_".join(data[2:]).replace("_", " ")
    
    try:
        await client.send_message(chat_id=user_id, text=f"❌ <b>ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ʜᴀs ʙᴇᴇɴ ʀᴇᴊᴇᴄᴛᴇᴅ!</b>\nItem: {title}")
        await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n❌ <b>REJECTED BY ADMIN</b>")
        if LOG_CHANNEL and LOG_CHANNEL != 0:
            await client.send_message(LOG_CHANNEL, f"❌ <b>[REJECTED]</b>\n👤 User: <code>{user_id}</code>\n📌 Item: {title}")
        await callback.answer("Rejected!", show_alert=True)
    except Exception as e:
        await callback.answer(f"Error: {e}", show_alert=True)
