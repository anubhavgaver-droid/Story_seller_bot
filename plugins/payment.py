import urllib.parse
import re
import time
import asyncio
import aiohttp
from datetime import datetime
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import UPI_ID, ADMIN_ID, BOT_USERNAME, LOG_CHANNEL
from database.db import get_story_by_title, add_user_purchase, add_wallet_balance

# Global Dictionaries for Active Sessions
ACTIVE_PAYMENTS = {}        # Payment timer and session data
WALLET_TOPUP_WAITING = {}   # Wallet state

# 🖼️ Step-by-Step Banner Image URL
GUIDE_IMAGE_URL = "https://i.ibb.co/VW778KdR/photo-2026-09-24-08-21-14-7689014092254023680.jpg" 

# 🌐 आपकी वेबसाइट API एंडपॉइंट्स (Screenshots के अनुसार)
CREATE_ORDER_URL = "https://demotry.shop/api/create-order"  #[span_3](start_span)[span_3](end_span)
CHECK_STATUS_URL = "https://demotry.shop/api/check-status"  #

# 🔑 API Credentials (Screenshots के अनुसार)
# Note: अपनी पूरी Secret Key 'sk_live_1dc3...' वाली नीचे रिप्लेस कर लें
API_SECRET_HEADER = ":-API-Secret"  #[span_4](start_span)[span_4](end_span)
API_SECRET_VALUE = "sk_live_1dc3..."         #[span_5](start_span)[span_5](end_span) 
API_KEY_VALUE = "" #

# 📋 Compact Terms & Conditions Text
TERMS_TEXT = (
    "📜 <b><u>ᴛᴇʀᴍs & ᴄᴏɴᴅɪᴛɪᴏɴs</u></b>\n\n"
    "• <b>ᴇxᴀᴄᴛ ᴀᴍᴏᴜɴᴛ:</b> ᴘᴀʏᴍᴇɴᴛ ᴍᴜsᴛ ᴍᴀᴛᴄʜ ᴛʜᴇ exact sᴛᴏʀʏ ᴘʀɪᴄᴇ.\n"
    "• <b>ᴜɴᴅᴇʀᴘᴀʏᴍᴇɴᴛ:</b> ɪғ ʏᴏᴜ ᴘᴀʏ ʟᴇss, ᴛʜᴇ ᴀᴍᴏᴜɴᴛ ᴡɪʟʟ ʙᴇ ᴀᴅᴅᴇᴅ ᴛᴏ ʏᴏᴜʀ <b>ᴡᴀʟʟᴇᴛ</b>.\n"
    "• <b>ᴏᴠᴇʀᴘᴀʏᴍᴇɴᴛ:</b> ᴀɴʏ ᴇxᴛʀᴀ ᴀᴍᴏᴜɴᴛ ᴘᴀɪᴅ ᴡɪʟʟ ʙᴇ ᴄʀᴇᴅɪᴛᴇᴅ ᴛᴏ ʏᴏᴜʀ <b>ᴡᴀʟʟᴇᴛ</b>.\n"
    "• <b>ɴᴏ ʀᴇғᴜɴᴅs:</b> ᴀʟʟ sales ᴀʀᴇ ғɪɴᴀʟ."
)

# ---------------- 1. API HELPER FUNCTIONS ----------------

async def create_website_order(user_id: int, user_name: str, amount: float):
    """वेबसाइट /api/create-order API से पेमेंट URL और Order ID लेता है"""
    order_id = f"ORD{user_id}_{int(time.time())}"
    headers = {
        API_SECRET_HEADER: API_SECRET_VALUE, #[span_6](start_span)[span_6](end_span)
        "Content-Type": "application/json"
    }
    payload = {
        "amount": f"{amount:.2f}",
        "order_id": order_id,
        "customer_name": user_name,
        "callback_url": f"https://t.me/{BOT_USERNAME}" #[span_7](start_span)[span_7](end_span)
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(CREATE_ORDER_URL, json=payload, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("payment_url"), order_id #[span_8](start_span)[span_8](end_span)
    except Exception as e:
        print(f"Error creating order: {e}")
    return None, order_id

async def check_website_order_status(order_id: str):
    """वेबसाइट /api/check-status API से ऑर्डर का लाइव स्टेटस चेक करता है"""
    headers = {
        "X-API-Key": API_KEY_VALUE, #
        "Content-Type": "application/json"
    }
    payload = {
        "order_id": order_id #
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(CHECK_STATUS_URL, json=payload, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # {"status": "success", "amount": "100.00"}
                    if data.get("status") in ["success", "SUCCESS", "PAID"]: #
                        paid_amt = float(data.get("amount", 0)) #
                        return True, paid_amt, "Payment Verified"
                    return False, 0.0, "Payment not completed yet"
                return False, 0.0, f"Server Error ({resp.status})"
    except Exception as e:
        return False, 0.0, f"Connection Error: {str(e)}"

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

# ---------------- VIEW STORY ----------------

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

# ---------------- STEP 1: SHOW TERMS ----------------

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

# ---------------- STEP 2: GENERATE QR FROM WEBSITE API ----------------

@Client.on_callback_query(filters.regex("^show_qr_"))
async def generate_qr_after_terms(client, callback):
    user_id = callback.from_user.id
    session = ACTIVE_PAYMENTS.get(user_id)
    
    if not session:
        return await callback.answer("⏰ Payment Expired! Please try again.", show_alert=True)
        
    if time.time() - session['timestamp'] > 600:
        ACTIVE_PAYMENTS.pop(user_id, None)
        return await callback.answer("⌛ Time limit of 10 minutes exceeded! Payment expired.", show_alert=True)

    await callback.answer("🔄 Generating Payment Link...", show_alert=False)

    title = session['title']
    price = session['price']
    clean_title = title.replace(" ", "_")
    customer_name = callback.from_user.first_name or "Customer"

    # Website API Call to Create Order
    payment_url, order_id = await create_website_order(user_id, customer_name, price)
    session['order_id'] = order_id  # Save Order ID for status checking

    try:
        await callback.message.delete()
    except Exception:
        pass

    # Use Website Payment URL for QR Code
    target_link = payment_url if payment_url else f"upi://pay?pa={UPI_ID}&pn=StorySeller&am={price}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&margin=15&data={urllib.parse.quote(target_link)}"
    
    caption = (
        f"⚡ <b>ᴀᴜᴛᴏᴍᴀᴛɪᴄ ᴘᴀʏᴍᴇɴᴛ ᴄʜᴇᴄᴋᴏᴜᴛ</b>\n\n"
        f"📖 <b>sᴛᴏʀʏ:</b> {title}\n"
        f"💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{price}\n"
        f"🆔 <b>ᴏʀᴅᴇʀ ɪᴅ:</b> <code>{order_id}</code>\n"
        f"⏳ <b>ᴛɪᴍᴇ ʟɪᴍɪᴛ:</b> 10 Minutes\n\n"
        f"📲 <i>1. Scan QR Code to pay via Paytm/UPI.\n2. After payment, click <b>'⚡ ᴠᴇʀɪғʏ ᴘᴀʏᴍᴇɴᴛ'</b> below!</i>"
    )
    
    btn_list = [
        [InlineKeyboardButton("⚡ ᴠᴇʀɪғʏ ᴘᴀʏᴍᴇɴᴛ", style=enums.ButtonStyle.SUCCESS, callback_data=f"auto_check_payment_{user_id}")]
    ]
    
    if payment_url:
        btn_list.append([InlineKeyboardButton("🔗 Pay Via Web Page / Paytm", url=payment_url)])
        
    btn_list.append([InlineKeyboardButton("👁️ sʜᴏᴡ ᴜᴘɪ ɪᴅ", callback_data="show_upi_id"), InlineKeyboardButton("📩 ᴍᴀɴᴜᴀʟ / ᴀᴅᴍɪɴ", callback_data=f"sent_{clean_title}_{price}")])
    btn_list.append([InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")])

    await callback.message.reply_photo(photo=qr_url, caption=caption, reply_markup=InlineKeyboardMarkup(btn_list))

# ---------------- STEP 3: DIRECT CLICK VERIFY ----------------

@Client.on_callback_query(filters.regex("^auto_check_payment_"))
async def direct_verify_payment(client, callback):
    user_id = callback.from_user.id
    session = ACTIVE_PAYMENTS.get(user_id)
    
    if not session:
        return await callback.answer("⏰ Session Expired! Please click Buy Now again.", show_alert=True)
        
    qr_created_time = session['timestamp']
    expected_price = session['price']
    title = session['title']
    order_id = session.get('order_id')
    
    if time.time() - qr_created_time > 600:
        ACTIVE_PAYMENTS.pop(user_id, None)
        return await callback.answer("⌛ 10 Minutes Time Limit Exceeded! Payment Expired.", show_alert=True)

    await callback.answer("🔄 Checking status from Website...", show_alert=False)
    
    # 1. Check status from Website API
    is_valid, actual_paid, msg = await check_website_order_status(order_id)
    
    # ⏳ Auto-retry once after 5 seconds if not detected immediately
    if not is_valid:
        wait_msg = await callback.message.reply_text("🔄 <b>Checking payment status with Website Server...</b>")
        for remaining in range(5, 0, -1):
            try:
                await wait_msg.edit_text(f"⏳ <b>Payment not detected yet! Re-checking in {remaining}s...</b>")
            except Exception:
                pass
            await asyncio.sleep(1)
            
        is_valid, actual_paid, msg = await check_website_order_status(order_id)
        try:
            await wait_msg.delete()
        except Exception:
            pass

    # ---------------- SUCCESSFUL PAYMENT ----------------
    if is_valid:
        ACTIVE_PAYMENTS.pop(user_id, None)
        actual_paid = actual_paid if actual_paid > 0 else expected_price
        
        # WALLET TOPUP
        if session['type'] == "WALLET":
            new_bal = await add_wallet_balance(user_id, actual_paid)
            await callback.message.reply_text(f"🎉 <b>ᴀᴜᴛᴏ-ᴠᴇʀɪғɪᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n💰 Added ₹{actual_paid} to Wallet.\n👛 New Balance: ₹{new_bal}")
            
            if LOG_CHANNEL and LOG_CHANNEL != 0:
                await client.send_message(
                    LOG_CHANNEL, 
                    f"⚡ <b>[DIRECT VERIFY SUCCESS] WALLET TOPUP</b>\n👤 <b>User:</b> {callback.from_user.first_name} (<code>{user_id}</code>)\n💰 <b>Amount:</b> ₹{actual_paid}"
                )
                
        # STORY PURCHASE
        else:
            story = await get_story_by_title(title)
            clean_title = story['title'].strip().split("\n")[0]
            encoded_title = clean_title.replace(" ", "_")
            delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"
            
            if actual_paid < expected_price:
                new_bal = await add_wallet_balance(user_id, actual_paid)
                await callback.message.reply_text(
                    f"⚠️ <b>ɪɴsᴜғғɪᴄɪᴇɴᴛ ᴘᴀʏᴍᴇɴᴛ ʀᴇᴄᴇɪᴠᴇᴅ!</b>\n\n"
                    f"📖 <b>Story Price:</b> ₹{expected_price}\n"
                    f"💵 <b>Paid Amount:</b> ₹{actual_paid}\n\n"
                    f"💡 <i>₹{actual_paid} added to your <b>Wallet</b>. Top-up remaining to unlock.</i>"
                )
            else:
                extra_amount = actual_paid - expected_price
                await add_user_purchase(user_id, clean_title, story_link=delivery_link)
                access_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (Unlocked)", style=enums.ButtonStyle.PRIMARY, url=delivery_link)]])
                
                overpaid_text = ""
                if extra_amount > 0:
                    new_bal = await add_wallet_balance(user_id, extra_amount)
                    overpaid_text = f"\n\n🎁 <b>Extra Payment:</b> ₹{extra_amount} added to Wallet!"
                
                await callback.message.reply_text(
                    f"🎉 <b>ᴀᴜᴛᴏ-ᴠᴇʀɪғɪᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n📖 <b>Story:</b> {clean_title}\n💰 <b>Paid:</b> ₹{actual_paid}{overpaid_text}\n\nClick below to access your files:",
                    reply_markup=access_btn,
                    protect_content=True
                )
                
                if LOG_CHANNEL and LOG_CHANNEL != 0:
                    await client.send_message(
                        LOG_CHANNEL, 
                        f"⚡ <b>[DIRECT VERIFY SUCCESS] STORY BOUGHT</b>\n👤 <b>User:</b> {callback.from_user.first_name} (<code>{user_id}</code>)\n📖 <b>Story:</b> {clean_title}\n💰 <b>Amount:</b> ₹{actual_paid}"
                    )

    # ---------------- PAYMENT NOT FOUND ----------------
    else:
        await callback.answer(f"❌ Payment not detected yet!\nReason: {msg}", show_alert=True)

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

# ---------------- MANUAL SCREENSHOT FLOW ----------------

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
    await message.reply_text("✅ <b>Screenshot received!</b> Admin will review and approve shortly.")
    ACTIVE_PAYMENTS.pop(user_id, None)

# Admin Approval / Rejection
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
        await callback.answer("Rejected!", show_alert=True)
    except Exception as e:
        await callback.answer(f"Error: {e}", show_alert=True)
