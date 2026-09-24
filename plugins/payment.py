import urllib.parse
import re
import imaplib
import email
import time
import asyncio
from datetime import datetime
from aiohttp import web
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import UPI_ID, ADMIN_ID, BOT_USERNAME, LOG_CHANNEL, GMAIL_USER, GMAIL_PASS
from database.db import get_story_by_title, add_user_purchase, add_wallet_balance

# Global Dictionaries & DB for UTR Lock
ACTIVE_PAYMENTS = {}        # Stores active session timing and order data
WALLET_TOPUP_WAITING = {}   # Stores wallet state
USED_TRANSACTIONS = set()   # Duplicate UTR / Txn ID locking memory

# 📱 MACRODROID INSTANT PAYMENT TRACKER MEMORY
# Format: {"UTR_NUMBER": {"amount": 100.0, "timestamp": 123456789}}
TRACKED_PAYMENTS = {}

WEBHOOK_SECRET = "MY_SUPER_SECRET_KEY_123"

# 🖼️ UTR Step-by-Step Banner Image URL
GUIDE_IMAGE_URL = "https://i.ibb.co/VW778KdR/photo-2026-09-24-08-21-14-7689014092254023680.jpg" 

# 📋 Compact Terms & Conditions Text
TERMS_TEXT = (
    "📜 <b><u>ᴛᴇʀᴍs & ᴄᴏɴᴅɪᴛɪᴏɴs</u></b>\n\n"
    "• <b>ᴇxᴀᴄᴛ ᴀᴍᴏᴜɴᴛ:</b> ᴘᴀʏᴍᴇɴᴛ ᴍᴜsᴛ ᴍᴀᴛᴄʜ ᴛʜᴇ exact sᴛᴏʀʏ ᴘʀɪᴄᴇ.\n"
    "• <b>ᴜɴᴅᴇʀᴘᴀʏᴍᴇɴᴛ:</b> ɪғ ʏᴏᴜ ᴘᴀʏ ʟᴇss, ᴛʜᴇ ᴀᴍᴏᴜɴᴛ ᴡɪʟʟ ʙᴇ ᴀᴅᴅᴇᴅ ᴛᴏ ʏᴏᴜʀ <b>ᴡᴀʟʟᴇᴛ</b>, ᴀɴᴅ ғɪʟᴇ ᴡɪʟʟ ɴᴏᴛ ʙᴇ ᴜɴʟᴏᴄᴋᴇᴅ.\n"
    "• <b>ᴏᴠᴇʀᴘᴀʏᴍᴇɴᴛ:</b> ᴀɴʏ ᴇxᴛʀᴀ ᴀᴍᴏᴜɴᴛ ᴘᴀɪᴅ ᴡɪʟʟ ʙᴇ ᴄʀᴇᴅɪᴛᴇᴅ ᴛᴏ ʏᴏᴜʀ <b>ᴡᴀʟʟᴇᴛ</b>.\n"
    "• <b>ɴᴏ ʀᴇғᴜɴᴅs:</b> ᴀʟʟ sales ᴀʀᴇ ғɪɴᴀʟ. ɴᴏ ᴅɪʀᴇᴄᴛ ʙᴀɴᴋ ʀᴇғᴜɴᴅs.\n"
    "• <b>ᴀɴᴛɪ-ғʀᴀᴜᴅ:</b> ʀᴇᴜsɪɴɢ ᴏʀ ғᴀᴋɪɴɢ ᴛxɴ ɪᴅs ᴡɪʟʟ ʀᴇsᴜʟᴛ ɪɴ ᴀɴ ɪɴsᴛᴀɴᴛ ʙᴀɴ."
)

# ---------------- ⚡ MACRODROID WEBHOOK HANDLER ----------------

async def handle_payment_webhook(request):
    try:
        data = await request.json()
        secret_key = data.get("secret")
        notification_text = data.get("text", "")

        if secret_key != WEBHOOK_SECRET:
            return web.json_response({"status": "unauthorized"}, status=401)

        # Regex for 12-digit UTR / Txn ID and Amount (₹100 or Rs.100 or 100 INR)
        utr_match = re.search(r'\b\d{12}\b', notification_text)
        amount_match = re.search(r'(?:₹|Rs\.?|INR)\s*([0-9]+(?:\.[0-9]+)?)', notification_text, re.IGNORECASE)

        if utr_match and amount_match:
            utr = utr_match.group(0)
            amount = float(amount_match.group(1))

            TRACKED_PAYMENTS[utr] = {
                "amount": amount,
                "timestamp": time.time()
            }
            print(f"⚡ [MACRODROID TRACKED] UTR: {utr} | Amount: ₹{amount}")
            return web.json_response({"status": "success", "utr": utr, "amount": amount})

        return web.json_response({"status": "ignored", "reason": "UTR or Amount not parsed"})

    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

# Helper Function: Verify Payment (Checks MacroDroid Memory first, then Gmail IMAP)
def verify_payment_data(txn_id):
    # 1. Check MacroDroid Webhook Memory (Instant Verification)
    if txn_id in TRACKED_PAYMENTS:
        data = TRACKED_PAYMENTS[txn_id]
        return True, "Verified via Instant Webhook", data["amount"]

    # 2. Check Gmail IMAP Backup
    if not GMAIL_USER or not GMAIL_PASS:
        return False, "Gmail credentials not configured.", 0.0
        
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_PASS)
        mail.select("inbox")
        
        status, messages = mail.search(None, f'TEXT "{txn_id}"')
        if status != "OK" or not messages[0]:
            mail.logout()
            return False, "Transaction ID not found in our system yet.", 0.0
            
        email_ids = messages[0].split()
        for e_id in reversed(email_ids):
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
                    
                    if txn_id in body:
                        amount_matches = re.findall(r"(?:₹|Rs\.?)\s*([\d\.]+)", body)
                        if amount_matches:
                            try:
                                actual_paid = float(amount_matches[0])
                                mail.logout()
                                return True, "Transaction Found in Gmail", actual_paid
                            except ValueError:
                                pass
        mail.logout()
        return False, "Transaction ID found, but unable to parse amount.", 0.0
    except Exception as e:
        return False, f"Email Check Error: {str(e)}", 0.0

# ---------------- CANCEL & UPI HANDLERS ----------------

@Client.on_callback_query(filters.regex("^cancel_payment_process$"))
async def cancel_payment_callback(client, callback):
    user_id = callback.from_user.id
    ACTIVE_PAYMENTS.pop(user_id, None)
    WALLET_TOPUP_WAITING.pop(user_id, None)
    
    try:
        await callback.message.delete()
    except Exception:
        pass
        
    cancel_msg = await callback.message.reply_text("❌ <b>ᴘᴀʏᴍᴇɴᴛ / ᴛᴏᴘ-ᴜᴘ ᴘʀᴏᴄᴇss ᴄᴀɴᴄᴇʟʟᴇᴅ.</b>")
    await callback.answer("Process Cancelled!")
    
    await asyncio.sleep(10)
    try:
        await cancel_msg.delete()
    except Exception:
        pass

@Client.on_callback_query(filters.regex("^show_upi_id$"))
async def show_upi_id(client, callback):
    await callback.answer(f"📌 UPI ID: {UPI_ID}", show_alert=True)

# ---------------- 1. VIEW STORY ----------------

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

# ---------------- STEP 1: SHOW TERMS & CONDITIONS FIRST ----------------

@Client.on_callback_query(filters.regex("^buy_"))
async def show_terms_first(client, callback):
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

    terms_caption = (
        f"📖 <b>sᴛᴏʀʏ:</b> {story_title}\n"
        f"💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{price}\n\n"
        f"{TERMS_TEXT}\n\n"
        f"👇 <i>ᴘʟᴇᴀsᴇ ᴄʟɪᴄᴋ <b>'✅ ɪ ᴀᴄᴄᴇᴘᴛ & ᴄᴏɴᴛɪɴᴜᴇ'</b> ᴛᴏ ɢᴇɴᴇʀᴀᴛᴇ QR Code:</i>"
    )
    
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ ɪ ᴀᴄᴄᴇᴘᴛ & ᴄᴏɴᴛɪɴᴜᴇ", style=enums.ButtonStyle.SUCCESS, callback_data=f"show_qr_{user_id}")],
        [InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
    ])
    
    try:
        await callback.message.reply_photo(
            photo=GUIDE_IMAGE_URL,
            caption=terms_caption,
            reply_markup=btn
        )
    except Exception:
        await callback.message.reply_text(terms_caption, reply_markup=btn)

    await callback.answer()

# ---------------- STEP 2: GENERATE QR & PAYMENT BUTTONS ----------------

@Client.on_callback_query(filters.regex("^show_qr_"))
async def generate_qr_after_terms(client, callback):
    user_id = callback.from_user.id
    session = ACTIVE_PAYMENTS.get(user_id)
    
    if not session:
        return await callback.answer("⏰ Payment Expired! Please try again.", show_alert=True)
        
    if time.time() - session['timestamp'] > 600:
        ACTIVE_PAYMENTS.pop(user_id, None)
        return await callback.answer("⌛ Time limit of 10 minutes exceeded! Payment expired.", show_alert=True)

    try:
        await callback.message.delete()
    except Exception:
        pass

    title = session['title']
    price = session['price']
    clean_title = title.replace(" ", "_")

    upi_link = f"upi://pay?pa={UPI_ID}&pn=StorySeller&am={price}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&margin=15&data={urllib.parse.quote(upi_link)}"
    
    caption = (
        f"⚡ <b>ᴀᴜᴛᴏᴍᴀᴛɪᴄ ᴘᴀʏᴍᴇɴᴛ ᴄʜᴇᴄᴋᴏᴜᴛ</b>\n\n"
        f"📖 <b>sᴛᴏʀʏ:</b> {title}\n"
        f"💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{price}\n"
        f"⏳ <b>ᴛɪᴍᴇ ʟɪᴍɪᴛ:</b> 10 Minutes\n\n"
        f"📲 <i>Scan QR & Complete Payment. Then Click Below to Submit UTR!</i>"
    )
    
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ ᴠᴇʀɪғʏ ᴘᴀʏᴍᴇɴᴛ (Auto)", style=enums.ButtonStyle.SUCCESS, callback_data=f"ask_utr_{user_id}")],
        [InlineKeyboardButton("👁️ sʜᴏᴡ ᴜᴘɪ ɪᴅ", callback_data="show_upi_id"), InlineKeyboardButton("📩 ᴍᴀɴᴜᴀʟ / ᴀᴅᴍɪɴ", callback_data=f"sent_{clean_title}_{price}")],
        [InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
    ])
    
    await callback.message.reply_photo(photo=qr_url, caption=caption, reply_markup=btn)
    await callback.answer()

# ---------------- STEP 3: ASK FOR UTR ----------------

@Client.on_callback_query(filters.regex("^ask_utr_"))
async def ask_utr_input(client, callback):
    user_id = callback.from_user.id
    session = ACTIVE_PAYMENTS.get(user_id)
    
    if not session:
        return await callback.answer("⏰ Payment Expired! Please try again.", show_alert=True)
        
    if time.time() - session['timestamp'] > 600:
        ACTIVE_PAYMENTS.pop(user_id, None)
        return await callback.answer("⌛ Time limit of 10 minutes exceeded! Payment expired.", show_alert=True)

    session['awaiting_txnid'] = True
    
    await callback.message.reply_text(
        "📝 <b>ᴇɴᴛᴇʀ ʏᴏᴜʀ ғᴀᴍᴘᴀʏ / ᴜᴘɪ ᴛʀᴀɴsᴀᴄᴛɪᴏɴ ɪᴅ:</b>\n\n"
        "ᴘʟᴇᴀsᴇ ᴘᴀsᴛᴇ ʏᴏᴜʀ 12-ᴅɪɢɪᴛ ᴜᴛʀ / ᴛxɴ ɪᴅ (ᴇ.ɢ., <code>FMPIB665989150...</code>) ʙᴇʟᴏᴡ:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", callback_data="cancel_payment_process")]])
    )
    await callback.answer()

# ---------------- TEXT LISTENER WITH AUTO-RETRY TIMER FOR UTR ----------------

@Client.on_message(filters.private & filters.text & ~filters.command(["start", "cancel"]), group=1)
async def process_auto_txn_id(client, message):
    user_id = message.from_user.id
    session = ACTIVE_PAYMENTS.get(user_id)
    
    if not session or not session.get('awaiting_txnid'):
        message.continue_propagation()
        return

    txn_id = message.text.strip()
    expected_price = session['price']
    title = session['title']
    
    if time.time() - session['timestamp'] > 600:
        ACTIVE_PAYMENTS.pop(user_id, None)
        return await message.reply_text("❌ <b>ᴘᴀʏᴍᴇɴᴛ ᴇxᴘɪʀᴇᴅ!</b> 10-ᴍɪɴᴜᴛᴇ ᴛɪᴍᴇʀ ᴄᴏᴍᴘʟᴇᴛᴇᴅ.")

    if txn_id in USED_TRANSACTIONS:
        return await message.reply_text("⚠️ <b>ᴛʜɪs ᴛʀᴀɴsᴀᴄᴛɪᴏɴ ɪᴅ ʜᴀs ᴀʟʀᴇᴀᴅʏ ʙᴇᴇɴ ᴜsᴇᴅ!</b>")

    wait_msg = await message.reply_text("🔄 <b>ᴠᴇʀɪғʏɪɴɢ ᴘᴀʏᴍᴇɴᴛ...</b>\n<i>Checking transaction details...</i>")
    
    # First attempt to verify
    is_valid, msg, actual_paid = verify_payment_data(txn_id)
    
    # ⏳ IF NOT FOUND IN FIRST ATTEMPT: START 5-SECOND COUNTDOWN & RETRY
    if not is_valid:
        for remaining in range(5, 0, -1):
            try:
                await wait_msg.edit_text(
                    f"⚠️ <b>ᴛʀᴀɴsᴀᴄᴛɪᴏɴ ɴᴏᴛ ғᴏᴜɴᴅ ʏᴇᴛ!</b>\n"
                    f"<i>Waiting for bank confirmation...</i>\n\n"
                    f"🔄 <b>ᴀᴜᴛᴏ-ʀᴇᴛʀʏɪɴɢ ɪɴ:</b> <code>{remaining}s</code>"
                )
            except Exception:
                pass
            await asyncio.sleep(1)

        # Final Retry Attempt
        await wait_msg.edit_text("🔄 <b>ʀᴇ-ᴠᴇʀɪғʏɪɴɢ ᴘᴀʏᴍᴇɴᴛ (Final Check)...</b>")
        is_valid, msg, actual_paid = verify_payment_data(txn_id)

    # ---------------- VERIFICATION SUCCESSFUL ----------------
    if is_valid:
        USED_TRANSACTIONS.add(txn_id)
        TRACKED_PAYMENTS.pop(txn_id, None)
        ACTIVE_PAYMENTS.pop(user_id, None)
        await wait_msg.delete()
        
        # WALLET TOPUP CASE
        if session['type'] == "WALLET":
            new_bal = await add_wallet_balance(user_id, actual_paid)
            await message.reply_text(f"🎉 <b>ᴀᴜᴛᴏ-ᴠᴇʀɪғɪᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n💰 ᴀᴅᴅᴇᴅ ₹{actual_paid} ᴛᴏ ᴡᴀʟʟᴇᴛ.\n👛 ɴᴇᴡ ʙᴀʟᴀɴᴄᴇ: ₹{new_bal}")
            
            if LOG_CHANNEL and LOG_CHANNEL != 0:
                await client.send_message(
                    LOG_CHANNEL, 
                    f"⚡ <b>[AUTO-PAYMENT SUCCESS] WALLET TOPUP</b>\n\n👤 <b>User:</b> {message.from_user.first_name} (<code>{user_id}</code>)\n💰 <b>Amount:</b> ₹{actual_paid}\n🔑 <b>Txn ID:</b> <code>{txn_id}</code>"
                )
                
        # STORY PURCHASE CASE
        else:
            story = await get_story_by_title(title)
            clean_title = story['title'].strip().split("\n")[0]
            encoded_title = clean_title.replace(" ", "_")
            delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"
            
            # CASE A: Underpaid Amount
            if actual_paid < expected_price:
                new_bal = await add_wallet_balance(user_id, actual_paid)
                await message.reply_text(
                    f"⚠️ <b>ɪɴsᴜғғɪᴄɪᴇɴᴛ ᴘᴀʏᴍᴇɴᴛ ʀᴇᴄᴇɪᴠᴇᴅ!</b>\n\n"
                    f"📖 <b>sᴛᴏʀʏ ᴘʀɪᴄᴇ:</b> ₹{expected_price}\n"
                    f"💵 <b>ᴘᴀɪᴅ ᴀᴍᴏᴜɴᴛ:</b> ₹{actual_paid}\n\n"
                    f"💡 <i>As per terms, your ₹{actual_paid} has been credited to your <b>Wallet</b>.</i>\n\n"
                    f"👛 <b>ᴄᴜʀʀᴇɴT ᴡᴀʟʟᴇᴛ ʙᴀʟᴀɴᴄᴇ:</b> ₹{new_bal}\n"
                    f"📌 <i>Top-up remaining amount to unlock files.</i>"
                )
                if LOG_CHANNEL and LOG_CHANNEL != 0:
                    await client.send_message(
                        LOG_CHANNEL, 
                        f"⚠️ <b>[UNDERPAID] WALLET CREDITED</b>\n👤 User: {message.from_user.first_name} (<code>{user_id}</code>)\n📖 Story: {clean_title}\n💰 Expected: ₹{expected_price} | Paid: ₹{actual_paid}"
                    )

            # CASE B: Exact or Overpaid Amount
            else:
                extra_amount = actual_paid - expected_price
                await add_user_purchase(user_id, clean_title, story_link=delivery_link)
                access_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (Unlocked)", style=enums.ButtonStyle.PRIMARY, url=delivery_link)]])
                
                overpaid_text = ""
                if extra_amount > 0:
                    new_bal = await add_wallet_balance(user_id, extra_amount)
                    overpaid_text = f"\n\n🎁 <b>ᴇxᴛʀᴀ ᴘᴀʏᴍᴇɴᴛ:</b> ₹{extra_amount} *added to Wallet!* (Balance: ₹{new_bal})"
                
                await message.reply_text(
                    f"🎉 <b>ᴀᴜᴛᴏ-ᴠᴇʀɪғɪᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n📖 <b>sᴛᴏʀʏ:</b> {clean_title}\n💰 <b>ᴘᴀɪᴅ:</b> ₹{actual_paid}{overpaid_text}\n\nClick below to access your files:",
                    reply_markup=access_btn,
                    protect_content=True
                )
                
                if LOG_CHANNEL and LOG_CHANNEL != 0:
                    await client.send_message(
                        LOG_CHANNEL, 
                        f"⚡ <b>[AUTO-PAYMENT SUCCESS] STORY BOUGHT</b>\n\n👤 <b>User:</b> {message.from_user.first_name} (<code>{user_id}</code>)\n📖 <b>Story:</b> {clean_title}\n💰 <b>Amount Paid:</b> ₹{actual_paid}\n🔑 <b>Txn ID:</b> <code>{txn_id}</code>"
                    )

    # ---------------- VERIFICATION FAILED (STOP PROCESS) ----------------
    else:
        ACTIVE_PAYMENTS.pop(user_id, None)
        await wait_msg.edit_text(
            f"🛑 <b>ᴀᴜᴛᴏ-ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ sᴛᴏᴘᴘᴇᴅ!</b>\n\n"
            f"❌ <b>Reason:</b> Transaction ID not found in system.\n\n"
            f"💡 <i>If you have actually completed the payment, please click below to send a screenshot for manual verification by Admin.</i>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📩 Contact Admin / Manual Verification", callback_data=f"sent_{title.replace(' ', '_')}_{expected_price}")],
                [InlineKeyboardButton("❌ Close", callback_data="cancel_payment_process")]
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

    terms_caption = (
        f"👛 <b>ᴡᴀʟʟᴇᴛ ᴛᴏᴘ-ᴜᴘ:</b> ₹{price}\n\n"
        f"{TERMS_TEXT}\n\n"
        f"👇 <i>ᴘʟᴇᴀsᴇ ᴄʟɪᴄᴋ <b>'✅ ɪ ᴀᴄᴄᴇᴘᴛ & ᴄᴏɴᴛɪɴᴜᴇ'</b> ᴛᴏ ɢᴇɴᴇʀᴀᴛᴇ QR Code:</i>"
    )
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ ɪ ᴀᴄᴄᴇᴘᴛ & ᴄᴏɴᴛɪɴᴜᴇ", style=enums.ButtonStyle.SUCCESS, callback_data=f"show_qr_{user_id}")],
        [InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
    ])
    await message.reply_photo(photo=GUIDE_IMAGE_URL, caption=terms_caption, reply_markup=btn)

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
