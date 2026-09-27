import urllib.parse
import re
import imaplib
import email
import time
import asyncio
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import UPI_ID, ADMIN_ID, BOT_USERNAME, LOG_CHANNEL, GMAIL_USER, GMAIL_PASS
from database.db import get_story_by_title, add_user_purchase, add_wallet_balance

# Global Dictionaries for Tracking
ACTIVE_PAYMENTS = {}        # Stores active session timing and order data
WALLET_TOPUP_WAITING = {}   # Stores wallet state

# 🖼️ Banner Image URL
GUIDE_IMAGE_URL = "https://i.ibb.co/hxSgff6h/photo-2026-09-27-13-06-01-7690200646190697472.jpg" 

# 📋 Compact Terms & Conditions Text in Small Caps
TERMS_TEXT = (
    "📜 <b><u>ᴛᴇʀᴍs & ᴄᴏɴᴅɪᴛɪᴏɴs</u></b>\n\n"
    "• <b>ᴇxᴀᴄᴛ ᴀᴍᴏᴜɴᴛ:</b> ᴘᴀʏᴍᴇɴᴛ ᴍᴜsᴛ ᴍᴀᴛᴄʜ ᴛʜᴇ ᴇxᴀᴄᴛ sᴛᴏʀʏ ᴘʀɪᴄᴇ.\n"
    "• <b>ᴜɴᴅᴇʀᴘᴀʏᴍᴇɴᴛ:</b> ᴜɴᴅᴇʀᴘᴀɪᴅ ᴀᴍᴏᴜɴᴛs ᴡɪʟʟ ʙᴇ ᴄʀᴇᴅɪᴛᴇᴅ ᴛᴏ ʏᴏᴜʀ <b>ᴡᴀʟʟᴇᴛ</b>; ғɪʟᴇ ᴡɪʟʟ ʀᴇᴍᴀɪɴ ʟᴏᴄᴋᴇᴅ.\n"
    "• <b>ᴏᴠᴇʀᴘᴀʏᴍᴇɴᴛ:</b> ᴇxᴛʀᴀ ᴀᴍᴏᴜɴᴛs ᴡɪʟʟ ʙᴇ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ᴄʀᴇᴅɪᴛᴇᴅ ᴛᴏ ʏᴏᴜʀ <b>ᴡᴀʟʟᴇᴛ</b>.\n"
    "• <b>ɴᴏ ʀᴇғᴜɴᴅs:</b> ᴀʟʟ sᴀʟᴇs ᴀʀᴇ ғɪɴᴀʟ. ɴᴏ ᴅɪʀᴇᴄᴛ ʙᴀɴᴋ ʀᴇғᴜɴᴅs.\n"
    "• <b>ᴀɴᴛɪ-ғʀᴀᴜᴅ:</b> ʀᴇᴜsɪɴɢ ᴏʀ ғᴀᴋɪɴɢ ᴘᴀʏᴍᴇɴᴛ ᴛʀᴀɴsᴀᴄᴛɪᴏɴ ɪᴅs ᴡɪʟʟ ʀᴇsᴜʟᴛ ɪɴ ᴀɴ ɪɴsᴛᴀɴᴛ ʙᴀɴ."
)

# ---------------- 📩 BOT VERIFICATION SYSTEM (GMAIL BACKEND) ----------------

def check_bot_payment_system(session_timestamp: float, expected_price: float):
    """
    Checks backend mail server for credit notifications received AFTER session_timestamp.
    """
    if not GMAIL_USER or not GMAIL_PASS:
        return False, "Bot verification system not configured.", 0.0
        
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_PASS)
        mail.select("inbox")
        
        session_start_dt = datetime.fromtimestamp(session_timestamp)
        session_expiry_dt = session_start_dt + timedelta(minutes=10)

        status, messages = mail.search(None, 'ALL')
        if status != "OK" or not messages[0]:
            mail.logout()
            return False, "No server logs found.", 0.0
            
        email_ids = messages[0].split()
        recent_ids = email_ids[-20:]  # Scan recent system logs

        for e_id in reversed(recent_ids):
            _, msg_data = mail.fetch(e_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    
                    try:
                        email_date = parsedate_to_datetime(msg['Date']).replace(tzinfo=None)
                    except Exception:
                        continue
                    
                    # Check timestamp window
                    if session_start_dt <= email_date <= session_expiry_dt:
                        subject = str(msg.get('Subject', '')).lower()
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() == "text/plain":
                                    body += part.get_payload(decode=True).decode("utf-8", errors="ignore").lower()
                        else:
                            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore").lower()
                        
                        full_content = subject + " " + body
                        
                        # Keywords for Bank / UPI Credit
                        credit_keywords = ["credited", "received", "payment received", "upi", "successful", "famapp", "fampay"]
                        if any(kw in full_content for kw in credit_keywords):
                            amount_matches = re.findall(r"(?:₹|rs\.?|inr)\s*([\d\.]+)", full_content)
                            for amt_str in amount_matches:
                                try:
                                    actual_paid = float(amt_str)
                                    if actual_paid >= expected_price:
                                        mail.logout()
                                        return True, "Payment verified by bot system", actual_paid
                                except ValueError:
                                    pass

        mail.logout()
        return False, "Payment notification not detected yet.", 0.0
    except Exception as e:
        return False, f"System Error: {str(e)}", 0.0

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
        
    cancel_msg = await callback.message.reply_text("❌ <b>ᴘᴀʏᴍᴇɴᴛ ᴘʀᴏᴄᴇss ᴄᴀɴᴄᴇʟʟᴇᴅ.</b>")
    await callback.answer("Cancelled!")
    
    await asyncio.sleep(8)
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
        f"♨️ <b>sᴛᴏʀʏ :</b> {clean_title}\n"
        f"🔰 <b>sᴛᴀᴛᴜs :</b> {story.get('status', 'Completed')}\n"
        f"🖥️ <b>ᴘʟᴀᴛғᴏʀᴍ :</b> {story.get('category', 'Pocket FM')}\n"
        f"🧩 <b>ɢᴇɴʀᴇ :</b> {story.get('genre', 'Drama')}\n"
        f"🎬 <b>ᴇᴘɪsᴏᴅᴇs :</b> {story.get('episodes', 'N/A')}\n\n"
        f"░▒▓█ ᴘʀɪᴄᴇ - ₹{story['price']} █▓▒░"
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

# ---------------- STEP 1: TERMS & CONDITIONS ----------------

@Client.on_callback_query(filters.regex("^buy_"))
async def show_terms_first(client, callback):
    try:
        raw_data = callback.data[4:]
        clean_title, price = raw_data.rsplit("_", 1)
        story_title = clean_title.replace("_", " ")
    except Exception:
        return await callback.answer("❌ ᴇʀʀᴏʀ ᴘᴀʀsɪɴɢ ᴘᴀʏᴍᴇɴᴛ ᴅᴀᴛᴀ!", show_alert=True)
    
    terms_caption = (
        f"📖 <b>sᴛᴏʀʏ:</b> {story_title}\n"
        f"💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{price}\n\n"
        f"{TERMS_TEXT}\n\n"
        f"👇 <i>ᴘʟᴇᴀsᴇ ᴄʟɪᴄᴋ <b>'✅ ᴀᴄᴄᴇᴘᴛ & ᴄᴏɴᴛɪɴᴜᴇ'</b> ᴛᴏ ɢᴇɴᴇʀᴀᴛᴇ ǫʀ ᴄᴏᴅᴇ:</i>"
    )
    
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ ᴀᴄᴄᴇᴘᴛ & ᴄᴏɴᴛɪɴᴜᴇ", style=enums.ButtonStyle.SUCCESS, callback_data=f"show_qr_{clean_title}_{price}")],
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

# ---------------- STEP 2: GENERATE QR CODE ----------------

@Client.on_callback_query(filters.regex("^show_qr_"))
async def generate_qr_after_terms(client, callback):
    user_id = callback.from_user.id
    
    try:
        raw_data = callback.data[8:]
        clean_title, price_str = raw_data.rsplit("_", 1)
        title = clean_title.replace("_", " ")
        price = float(price_str)
    except Exception:
        return await callback.answer("❌ ᴇʀʀᴏʀ ʀᴇᴀᴅɪɴɢ sᴇssɪᴏɴ ᴅᴀᴛᴀ!", show_alert=True)

    # Save Session Timestamp
    ACTIVE_PAYMENTS[user_id] = {
        "title": title,
        "price": price,
        "timestamp": time.time(),
        "type": "STORY" if title != "WalletTopup" else "WALLET"
    }

    try:
        await callback.message.delete()
    except Exception:
        pass

    upi_link = f"upi://pay?pa={UPI_ID}&pn=StorySeller&am={price}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&margin=15&data={urllib.parse.quote(upi_link)}"
    
    caption = (
        f"⚡ <b>ᴀᴜᴛᴏᴍᴀᴛɪᴄ ᴘᴀʏᴍᴇɴᴛ ᴄʜᴇᴄᴋᴏᴜᴛ</b>\n\n"
        f"📖 <b>sᴛᴏʀʏ:</b> {title}\n"
        f"💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{price}\n"
        f"⏳ <b>sᴇssɪᴏɴ ᴠᴀʟɪᴅɪᴛʏ:</b> 10 ᴍɪɴᴜᴛᴇs\n\n"
        f"📲 <i>sᴄᴀɴ ǫʀ & ᴄᴏᴍᴘʟᴇᴛᴇ ᴘᴀʏᴍᴇɴᴛ ᴠɪᴀ ᴀɴʏ ᴜᴘɪ ᴀᴘᴘ.\nᴛʜᴇɴ ᴄʟɪᴄᴋ <b>'⚡ ᴠᴇʀɪғʏ ᴘᴀʏᴍᴇɴᴛ'</b> ʙᴇʟᴏᴡ!</i>"
    )
    
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ ᴠᴇʀɪғʏ ᴘᴀʏᴍᴇɴᴛ", style=enums.ButtonStyle.SUCCESS, callback_data=f"start_auto_check_{user_id}")],
        [InlineKeyboardButton("👁️ sʜᴏᴡ ᴜᴘɪ ɪᴅ", callback_data="show_upi_id"), InlineKeyboardButton("📩 ᴍᴀɴᴜᴀʟ ᴀᴘᴘʀᴏᴠᴀʟ", callback_data=f"sent_{clean_title}_{price}")],
        [InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
    ])
    
    await callback.message.reply_photo(photo=qr_url, caption=caption, reply_markup=btn)
    await callback.answer()

# ---------------- STEP 3: STYLISH 30-SECOND COUNTDOWN VERIFICATION ----------------

@Client.on_callback_query(filters.regex("^start_auto_check_"))
async def execute_30s_countdown_check(client, callback):
    user_id = callback.from_user.id
    session = ACTIVE_PAYMENTS.get(user_id)
    
    if not session:
        return await callback.answer("⏰ ᴘᴀʏᴍᴇɴᴛ sᴇssɪᴏɴ ᴇxᴘɪʀᴇᴅ! ᴘʟᴇᴀsᴇ ɢᴇɴᴇʀᴀᴛᴇ ᴀ ɴᴇᴡ ǫʀ.", show_alert=True)
        
    session_start = session['timestamp']
    expected_price = session['price']
    title = session['title']
    
    # 10 Minute Limit
    if time.time() - session_start > 600:
        ACTIVE_PAYMENTS.pop(user_id, None)
        return await callback.answer("⌛ ᴛɪᴍᴇ ʟɪᴍɪᴛ ᴏғ 10 ᴍɪɴᴜᴛᴇs ᴇxᴄᴇᴇᴅᴇᴅ! sᴇssɪᴏɴ ᴇxᴘɪʀᴇᴅ.", show_alert=True)

    await callback.answer("🔎 Payment verification started...")

    status_msg = await callback.message.reply_text(
        f"⚡ <b>ᴏᴜʀ ʙᴏᴛ sʏsᴛᴇᴍ ɪs ᴠᴇʀɪғʏɪɴɢ ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ...</b>\n\n"
        f"🔍 <i>ᴄʜᴇᴄᴋɪɴɢ sʏsᴛᴇᴍ ʟᴏɢs ғᴏʀ ₹{expected_price}...</i>\n"
        f"⏳ <b>ᴛɪᴍᴇ ʀᴇᴍᴀɪɴɪɴɢ:</b> <code>30s</code>"
    )

    is_verified = False
    actual_paid = 0.0

    # ⏱️ STYLISH COUNTDOWN LOOP (30 Seconds)
    for seconds_left in range(30, 0, -1):
        # Background System Check
        is_valid, msg, paid = check_bot_payment_system(session_start, expected_price)
        if is_valid:
            is_verified = True
            actual_paid = paid
            break  # Stop countdown instantly on successful verification

        # Update countdown UI every second
        try:
            dots = "." * ((30 - seconds_left) % 4 + 1)
            await status_msg.edit_text(
                f"⚡ <b>ᴏᴜʀ ʙᴏᴛ sʏsᴛᴇᴍ ɪs ᴠᴇʀɪғʏɪɴɢ ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ{dots}</b>\n\n"
                f"🔍 <b>sᴛᴀᴛᴜs:</b> ᴄʜᴇᴄᴋɪɴɢ sʏsᴛᴇᴍ ᴛʀᴀɴsᴀᴄᴛɪᴏɴs ғᴏʀ ₹{expected_price}\n"
                f"⏱️ <b>ᴛɪᴍᴇ ʀᴇᴍᴀɪɴɪɴɢ:</b> <code>{seconds_left:02d}s</code>"
            )
        except Exception:
            pass

        await asyncio.sleep(1)

    # ---------------- RESULT: SUCCESS ----------------
    if is_verified:
        ACTIVE_PAYMENTS.pop(user_id, None)
        await status_msg.delete()
        
        # WALLET TOP-UP
        if session['type'] == "WALLET":
            new_bal = await add_wallet_balance(user_id, actual_paid)
            await callback.message.reply_text(
                f"🎉 <b>ᴘᴀʏᴍᴇɴᴛ ᴠᴇʀɪғɪᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
                f"💰 <b>ᴀᴅᴅᴇᴅ ᴛᴏ ᴡᴀʟʟᴇᴛ:</b> ₹{actual_paid}\n"
                f"👛 <b>ᴜᴘᴅᴀᴛᴇᴅ ʙᴀʟᴀɴᴄᴇ:</b> ₹{new_bal}"
            )
            if LOG_CHANNEL and LOG_CHANNEL != 0:
                await client.send_message(
                    LOG_CHANNEL, 
                    f"⚡ <b>[AUTO-PAYMENT SUCCESS] WALLET TOPUP</b>\n\n👤 <b>User:</b> {callback.from_user.first_name} (<code>{user_id}</code>)\n💰 <b>Amount:</b> ₹{actual_paid}"
                )
                
        # STORY PURCHASE
        else:
            story = await get_story_by_title(title)
            clean_title = story['title'].strip().split("\n")[0]
            encoded_title = clean_title.replace(" ", "_")
            delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"
            
            extra_amount = actual_paid - expected_price
            await add_user_purchase(user_id, clean_title, story_link=delivery_link)
            access_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (ᴜɴʟᴏᴄᴋᴇᴅ)", style=enums.ButtonStyle.PRIMARY, url=delivery_link)]])
            
            overpaid_text = ""
            if extra_amount > 0:
                new_bal = await add_wallet_balance(user_id, extra_amount)
                overpaid_text = f"\n\n🎁 <b>ᴇxᴛʀᴀ ᴘᴀʏᴍᴇɴᴛ:</b> ₹{extra_amount} ᴀᴅᴅᴇᴅ ᴛᴏ ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ ʙᴀʟᴀɴᴄᴇ! (ɴᴇᴡ ʙᴀʟᴀɴᴄᴇ: ₹{new_bal})"
            
            await callback.message.reply_text(
                f"🎉 <b>ᴘᴀʏᴍᴇɴᴛ ᴠᴇʀɪғɪᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
                f"📖 <b>sᴛᴏʀʏ:</b> {clean_title}\n"
                f"💰 <b>ᴀᴍᴏᴜɴᴛ ᴘᴀɪᴅ:</b> ₹{actual_paid}{overpaid_text}\n\n"
                f"ᴄʟɪᴄᴋ ʙᴇʟᴏᴡ ᴛᴏ ᴀᴄᴄᴇss ʏᴏᴜʀ ғɪʟᴇs:",
                reply_markup=access_btn,
                protect_content=True
            )
            
            if LOG_CHANNEL and LOG_CHANNEL != 0:
                await client.send_message(
                    LOG_CHANNEL, 
                    f"⚡ <b>[AUTO-PAYMENT SUCCESS] STORY BOUGHT</b>\n\n👤 <b>User:</b> {callback.from_user.first_name} (<code>{user_id}</code>)\n📖 <b>Story:</b> {clean_title}\n💰 <b>Amount Paid:</b> ₹{actual_paid}"
                )

    # ---------------- RESULT: NOT FOUND AFTER 30 SECONDS ----------------
    else:
        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 ʀᴇ-ᴄʜᴇᴄᴋ ᴘᴀʏᴍᴇɴᴛ", style=enums.ButtonStyle.SUCCESS, callback_data=f"start_auto_check_{user_id}")],
            [InlineKeyboardButton("📩 ʀᴇǫᴜᴇsᴛ ᴀᴅᴍɪɴ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ", callback_data=f"sent_{title.replace(' ', '_')}_{expected_price}")],
            [InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
        ])
        
        await status_msg.edit_text(
            f"❌ <b>ᴘᴀʏᴍᴇɴᴛ ɴᴏᴛ ᴅᴇᴛᴇᴄᴛᴇᴅ ʏᴇᴛ</b>\n\n"
            f"ᴏᴜʀ ʙᴏᴛ sʏsᴛᴇᴍ ᴄᴏᴜʟᴅ ɴᴏᴛ ғɪɴᴅ ᴀ ᴘᴀʏᴍᴇɴᴛ ᴏғ <b>₹{expected_price}</b> ᴡɪᴛʜɪɴ ᴛʜᴇ ʟᴀsᴛ 30 sᴇᴄᴏɴᴅs.\n\n"
            f"• <i>ʙᴀɴᴋɪɴɢ sᴇʀᴠᴇʀs sᴏᴍᴇᴛɪᴍᴇs ᴛᴀᴋᴇ 1-2 ᴍɪɴᴜᴛᴇs ᴛᴏ ᴘᴜsʜ ᴘᴀʏᴍᴇɴᴛ ɴᴏᴛɪғɪᴄᴀᴛɪᴏɴs.</i>\n"
            f"• <i>ɪғ ʏᴏᴜ ʜᴀᴠᴇ ᴀʟʀᴇᴀᴅʏ ᴘᴀɪᴅ, ᴄʟɪᴄᴋ <b>'🔄 ʀᴇ-ᴄʜᴇᴄᴋ ᴘᴀʏᴍᴇɴᴛ'</b> ʙᴇʟᴏᴡ.</i>\n"
            f"• <i>ᴏʀ ᴄʟɪᴄᴋ <b>'📩 ʀᴇǫᴜᴇsᴛ ᴀᴅᴍɪɴ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ'</b> ᴛᴏ sᴜʙᴍɪᴛ ᴀ sᴄʀᴇᴇɴsʜᴏᴛ ᴍᴀɴᴜᴀʟʟʏ.</i>",
            reply_markup=btn
        )

# ---------------- WALLET TOPUP FLOW ----------------

@Client.on_callback_query(filters.regex("^add_wallet_funds$"))
async def start_wallet_topup(client, callback):
    user_id = callback.from_user.id
    WALLET_TOPUP_WAITING[user_id] = True
    await callback.message.reply_text(
        "💵 <b>ᴇɴᴛᴇʀ ᴛᴏᴘ-ᴜᴘ ᴀᴍᴏᴜɴᴛ:</b>\nᴘʟᴇᴀsᴇ ᴛʏᴘᴇ ᴀᴍᴏᴜɴᴛ (ɪɴ ₹):",
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
        return await message.reply_text("❌ <b>ɪɴᴠᴀʟɪᴅ ᴀᴍᴏᴜɴᴛ! ᴘʟᴇᴀsᴇ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ.</b>")
    
    price = float(amount_text)
    del WALLET_TOPUP_WAITING[user_id]
    
    terms_caption = (
        f"👛 <b>ᴡᴀʟʟᴇᴛ ᴛᴏᴘ-ᴜᴘ:</b> ₹{price}\n\n"
        f"{TERMS_TEXT}\n\n"
        f"👇 <i>ᴘʟᴇᴀsᴇ ᴄʟɪᴄᴋ <b>'✅ ᴀᴄᴄᴇᴘᴛ & ᴄᴏɴᴛɪɴᴜᴇ'</b> ᴛᴏ ɢᴇɴᴇʀᴀᴛᴇ ǫʀ ᴄᴏᴅᴇ:</i>"
    )
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ ᴀᴄᴄᴇᴘᴛ & ᴄᴏɴᴛɪɴᴜᴇ", style=enums.ButtonStyle.SUCCESS, callback_data=f"show_qr_WalletTopup_{price}")],
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
        return await callback.answer("❌ ᴇʀʀᴏʀ ᴘᴀʀsɪɴɢ ᴅᴀᴛᴀ!", show_alert=True)
        
    user_id = callback.from_user.id
    ACTIVE_PAYMENTS[user_id] = {"title": story_title, "price": price, "manual": True}
    
    await callback.message.reply_text(
        "📸 <b>sᴇɴᴅ ᴘᴀʏᴍᴇɴᴛ sᴄʀᴇᴇɴsʜᴏᴛ:</b>\n\nᴘʟᴇᴀsᴇ sᴇɴᴅ ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ sᴄʀᴇᴇɴsʜᴏᴛ ᴘʜᴏᴛᴏ ɪɴ ᴛʜɪs ᴄʜᴀᴛ.",
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
        f"🚨 <b>ᴍᴀɴᴜᴀʟ ᴘᴀʏᴍᴇɴᴛ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ʀᴇǫᴜᴇsᴛ</b>\n\n"
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
            
    await message.reply_text("✅ <b>sᴄʀᴇᴇɴsʜᴏᴛ ʀᴇᴄᴇɪᴠᴇᴅ!</b> ᴀᴅᴍɪɴ ᴡɪʟʟ ʀᴇᴠɪᴇᴡ ᴀɴᴅ ᴀᴘᴘʀᴏᴠᴇ sʜᴏʀᴛʟʏ.")
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
    access_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (ᴜɴʟᴏᴄᴋᴇᴅ)", style=enums.ButtonStyle.PRIMARY, url=delivery_link)]])
    
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
