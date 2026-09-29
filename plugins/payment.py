import io
import time
import asyncio
import aiohttp
import re
import urllib.parse
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import qrcode

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Config Imports
from config import (
    ADMIN_ID, BOT_USERNAME, LOG_CHANNEL,
    CREATE_ORDER_URL, CHECK_STATUS_URL, API_KEY_VALUE, API_SECRET_VALUE, UPI_ID
)
from database.db import get_story_by_title, add_user_purchase, add_wallet_balance

# Global Dictionaries
ACTIVE_PAYMENTS = {}        
WALLET_TOPUP_WAITING = {}   

GUIDE_IMAGE_URL = "https://i.ibb.co/VW778KdR/photo-2026-09-24-08-21-14-7689014092254023680.jpg" 

TERMS_TEXT = (
    "📜 <b><u>ᴛᴇʀᴍs & ᴄᴏɴᴅɪᴛɪᴏɴs</u></b>\n\n"
    "• <b>ᴇxᴀᴄᴛ ᴀᴍᴏᴜɴᴛ:</b> ᴘᴀʏᴍᴇɴᴛ ᴍᴜsᴛ ᴍᴀᴛᴄʜ ᴛʜᴇ exact sᴛᴏʀʏ ᴘʀɪᴄᴇ.\n"
    "• <b>ᴜɴᴅᴇʀᴘᴀʏᴍᴇɴᴛ:</b> ɪғ ʏᴏᴜ ᴘᴀʏ ʟᴇss, ᴛʜᴇ ᴀᴍᴏᴜɴᴛ ᴡɪʟʟ ʙᴇ ᴀᴅᴅᴇᴅ ᴛᴏ ʏᴏᴜʀ <b>ᴡᴀʟʟᴇᴛ</b>.\n"
    "• <b>ᴏᴠᴇʀᴘᴀʏᴍᴇɴᴛ:</b> ᴀɴʏ ᴇxᴛʀᴀ ᴀᴍᴏᴜɴᴛ ᴘᴀɪᴅ ᴡɪʟʟ ʙᴇ ᴄʀᴇᴅɪᴛᴇᴅ ᴛᴏ ʏᴏᴜʀ <b>ᴡᴀʟʟᴇᴛ</b>.\n"
    "• <b>ɴᴏ ʀᴇғᴜɴᴅs:</b> ᴀʟʟ sales ᴀʀᴇ ғɪɴᴀʟ."
)

# ---------------- 1. API HELPER & EXTRACTOR FUNCTIONS ----------------

async def extract_qr_data_from_website(payment_url: str):
    """
    Website Payment Link (demotry.shop/pay/...) par background request bhej kar
    wahan se exact UPI payload extract karta hai.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(payment_url, headers=headers, timeout=8) as resp:
                if resp.status == 200:
                    html_content = await resp.text()
                    
                    # 1. HTML ya JS code mein se upi://pay?... intent string extract karna
                    upi_match = re.search(r'upi://pay\?[^\s"\'<>]+', html_content)
                    if upi_match:
                        return upi_match.group(0)
                    
                    # 2. Extract VPA & Order ID if present in HTML
                    amount_match = re.search(r'am=([0-9.]+)', html_content)
                    order_match = re.search(r'tr=([a-zA-Z0-9_\-]+)', html_content)
                    vpa_match = re.search(r'pa=([a-zA-Z0-9.\-_]+@[a-zA-Z0-9]+)', html_content)

                    vpa = vpa_match.group(1) if vpa_match else UPI_ID
                    amt = amount_match.group(1) if amount_match else None
                    oid = order_match.group(1) if order_match else None

                    if amt and oid:
                        return f"upi://pay?pa={vpa}&pn=StorySeller&am={amt}&cu=INR&tr={oid}"
    except Exception as e:
        print(f"❌ Error extracting QR data from website: {e}")
    return None


def generate_exact_website_qr_card(amount_text: str, qr_payload: str) -> io.BytesIO:
    """
    Website Style UI Card Image with Pure UPI Payload in QR Code.
    Ensures PhonePe/GPay opens Direct Payment Screen instead of Link.
    """
    img_w, img_h = 600, 750
    card = Image.new("RGB", (img_w, img_h), (255, 255, 255))
    draw = ImageDraw.Draw(card)

    try:
        font_label = ImageFont.truetype("arial.ttf", 26)
        font_amount = ImageFont.truetype("arialbd.ttf", 75)
    except Exception:
        font_label = ImageFont.load_default()
        font_amount = ImageFont.load_default()

    # 1. Top Heading Label
    label_text = "TOTAL AMOUNT TO PAY"
    label_bbox = draw.textbbox((0, 0), label_text, font=font_label)
    label_w = label_bbox[2] - label_bbox[0]
    draw.text(((img_w - label_w) / 2, 45), label_text, fill="#888888", font=font_label)

    # 2. Large Amount Text (e.g. ₹1.00)
    amt_text = f"₹{amount_text}"
    amt_bbox = draw.textbbox((0, 0), amt_text, font=font_amount)
    amt_w = amt_bbox[2] - amt_bbox[0]
    draw.text(((img_w - amt_w) / 2, 95), amt_text, fill="#0d3c75", font=font_amount)

    # 3. Pure UPI Intent QR Code (Direct Payment)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=1,
    )
    qr.add_data(qr_payload)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB").resize((440, 440))

    # 4. Outer Container Frame
    fx1, fy1, fx2, fy2 = 70, 220, 530, 680
    draw.rounded_rectangle([fx1, fy1, fx2, fy2], radius=25, fill="#ffffff", outline="#e2e8f0", width=2)
    card.paste(qr_img, (80, 230))

    # 5. Blue Focus Corner Styling
    blue_color, c_len, c_w = "#3b82f6", 35, 7
    # Top-Left Corner
    draw.arc([fx1, fy1, fx1+40, fy1+40], start=180, end=270, fill=blue_color, width=c_w)
    draw.line([fx1+20, fy1, fx1+20+c_len, fy1], fill=blue_color, width=c_w)
    draw.line([fx1, fy1+20, fx1, fy1+20+c_len], fill=blue_color, width=c_w)

    # Top-Right Corner
    draw.arc([fx2-40, fy1, fx2, fy1+40], start=270, end=0, fill=blue_color, width=c_w)
    draw.line([fx2-20-c_len, fy1, fx2-20, fy1], fill=blue_color, width=c_w)
    draw.line([fx2, fy1+20, fx2, fy1+20+c_len], fill=blue_color, width=c_w)

    # Bottom-Left Corner
    draw.arc([fx1, fy2-40, fx1+40, fy2], start=90, end=180, fill=blue_color, width=c_w)
    draw.line([fx1+20, fy2, fx1+20+c_len, fy2], fill=blue_color, width=c_w)
    draw.line([fx1, fy2-20-c_len, fx1, fy2-20], fill=blue_color, width=c_w)

    # Bottom-Right Corner
    draw.arc([fx2-40, fy2-40, fx2, fy2], start=0, end=90, fill=blue_color, width=c_w)
    draw.line([fx2-20-c_len, fy2, fx2-20, fy2], fill=blue_color, width=c_w)
    draw.line([fx2, fy2-20-c_len, fx2, fy2-20], fill=blue_color, width=c_w)

    bio = io.BytesIO()
    bio.name = "website_qr_card.png"
    card.save(bio, "PNG")
    bio.seek(0)
    return bio


async def create_website_order(user_id: int, user_name: str, amount: float):
    order_id = f"ORD_{user_id}_{int(time.time())}"
    
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY_VALUE.strip(),
        "X-API-Secret": API_SECRET_VALUE.strip()
    }
    
    payload = {
        "amount": float(amount),
        "order_id": order_id,
        "customer_name": user_name or "Telegram User",
        "customer_mobile": "9999999999",
        "redirect_url": f"https://t.me/{BOT_USERNAME}",
        "callback_url": f"https://t.me/{BOT_USERNAME}"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(CREATE_ORDER_URL, json=payload, headers=headers, timeout=12) as resp:
                resp_text = await resp.text()
                print(f"[CREATE ORDER LOG] Code: {resp.status}, Response: {resp_text}")
                
                if resp.status in [200, 201]:
                    data = await resp.json()
                    pay_url = None
                    if isinstance(data.get("data"), dict):
                        pay_url = data["data"].get("payment_url") or data["data"].get("url")
                    if not pay_url:
                        pay_url = data.get("payment_url") or data.get("url")
                        
                    return pay_url, order_id
    except Exception as e:
        print(f"❌ Error in create_website_order: {e}")
        
    return None, order_id


async def check_website_order_status(order_id: str):
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY_VALUE.strip(),
        "X-API-Secret": API_SECRET_VALUE.strip()
    }
    payload = {
        "order_id": order_id
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(CHECK_STATUS_URL, json=payload, headers=headers, timeout=12) as resp:
                resp_text = await resp.text()
                print(f"[STATUS CHECK LOG] Code: {resp.status}, Response: {resp_text}")
                
                if resp.status == 200:
                    data = await resp.json()
                    res_data = data.get("data", {}) if isinstance(data.get("data"), dict) else data
                    
                    status = str(res_data.get("payment_status") or res_data.get("status") or data.get("status") or "").upper()
                    paid_amt = float(res_data.get("amount", 0) or data.get("amount", 0))
                    
                    if status in ["SUCCESS", "PAID", "COMPLETED"]:
                        return True, paid_amt, "Payment Verified Successfully"
                    return False, 0.0, f"Status: {status if status else 'PENDING'}"
                return False, 0.0, f"Server Error (HTTP {resp.status})"
    except Exception as e:
        return False, 0.0, f"Connection Error: {str(e)}"

# ---------------- CANCEL HANDLER ----------------

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
        f"👇 <i>ᴘʟᴇᴀsᴇ ᴄʟɪᴄᴋ <b>'✅ ɪ ᴀᴄᴄᴇᴘᴛ & ᴄᴏɴᴛɪɴᴜᴇ'</b> ᴛᴏ ɢᴇɴᴇʀᴀᴛᴇ QR & ᴘᴀʏᴍᴇɴᴛ ʟɪɴᴋ:</i>"
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

# ---------------- STEP 2: GENERATE DIRECT UPI QR CARD ----------------

@Client.on_callback_query(filters.regex("^show_qr_"))
async def generate_qr_after_terms(client, callback):
    user_id = callback.from_user.id
    session = ACTIVE_PAYMENTS.get(user_id)
    
    if not session:
        return await callback.answer("⏰ Session Expired! Please click Buy again.", show_alert=True)

    await callback.answer("🔄 Generating Direct UPI QR Code...", show_alert=False)

    title = session['title']
    price = session['price']
    clean_title = title.replace(" ", "_")
    customer_name = callback.from_user.first_name or "Customer"

    # 1. Website Gateway API se Order Generate karna
    payment_url, gen_order_id = await create_website_order(user_id, customer_name, price)

    try:
        await callback.message.delete()
    except Exception:
        pass

    btn_list = []
    qr_payload = None
    display_amount = f"{price:.2f}"

    # 2. Extract UPI String or Fallback to Direct UPI URI String
    if payment_url:
        qr_payload = await extract_qr_data_from_website(payment_url)
        btn_list.append([InlineKeyboardButton("🌐 ᴘᴀʏ ᴠɪᴀ ᴡᴇʙsɪᴛᴇ", url=payment_url)])

    # FIX: Agar Extract nahi ho pata, to Direct Pure UPI Payload Banayein (Kabhi Web URL QR me nahi jayega)
    if not qr_payload:
        qr_payload = f"upi://pay?pa={UPI_ID}&pn=StorySeller&am={display_amount}&cu=INR&tr={gen_order_id}"

    session['order_id'] = gen_order_id  

    # 3. Direct UPI Intent se QR Image Generate Karein
    qr_image_bytes = generate_exact_website_qr_card(display_amount, qr_payload)

    caption = (
        f"⚡ <b>ᴀᴜᴛᴏᴍᴀᴛɪᴄ ᴘᴀʏᴍᴇɴᴛ ᴄʜᴇᴄᴋᴏᴜᴛ</b>\n\n"
        f"📖 <b>sᴛᴏʀʏ:</b> {title}\n"
        f"💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{display_amount}\n"
        f"🆔 <b>ᴏʀᴅᴇʀ ɪᴅ:</b> <code>{gen_order_id}</code>\n"
        f"⏳ <b>ᴛɪᴍᴇ ʟɪᴍɪᴛ:</b> 10 Minutes\n\n"
        f"📲 <i>1. Scan this QR code using PhonePe, GPay, Paytm, or BHIM App.\n"
        f"2. Or click <b>'🌐 ᴘᴀʏ ᴠɪᴀ ᴡᴇʙsɪᴛᴇ'</b> to open payment page.\n"
        f"3. Click <b>'⚡ ᴠᴇʀɪғʏ ᴘᴀʏᴍᴇɴᴛ'</b> below after paying!</i>"
    )
    
    btn_list.append([InlineKeyboardButton("⚡ ᴠᴇʀɪғʏ ᴘᴀʏᴍᴇɴᴛ", style=enums.ButtonStyle.SUCCESS, callback_data=f"auto_check_payment_{user_id}")])
    btn_list.append([InlineKeyboardButton("📩 ᴍᴀɴᴜᴀʟ / ᴀᴅᴍɪɴ", callback_data=f"sent_{clean_title}_{price}")])
    btn_list.append([InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")])

    await callback.message.reply_photo(
        photo=qr_image_bytes,
        caption=caption,
        reply_markup=InlineKeyboardMarkup(btn_list)
    )

# ---------------- STEP 3: VERIFY PAYMENT STATUS ----------------

@Client.on_callback_query(filters.regex("^auto_check_payment_"))
async def direct_verify_payment(client, callback):
    user_id = callback.from_user.id
    session = ACTIVE_PAYMENTS.get(user_id)
    
    if not session:
        return await callback.answer("⏰ Session Expired! Please try again.", show_alert=True)
        
    expected_price = session['price']
    title = session['title']
    order_id = session.get('order_id')
    
    await callback.answer("🔄 Checking payment status...", show_alert=False)
    
    is_valid, actual_paid, msg = await check_website_order_status(order_id)
    
    if not is_valid:
        await asyncio.sleep(3)
        is_valid, actual_paid, msg = await check_website_order_status(order_id)

    if is_valid:
        ACTIVE_PAYMENTS.pop(user_id, None)
        actual_paid = actual_paid if actual_paid > 0 else expected_price
        
        if session['type'] == "WALLET":
            new_bal = await add_wallet_balance(user_id, actual_paid)
            await callback.message.reply_text(f"🎉 <b>ᴀᴜᴛᴏ-ᴠᴇʀɪғɪᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n💰 Added ₹{actual_paid} to Wallet.\n👛 New Balance: ₹{new_bal}")
            
        else:
            story = await get_story_by_title(title)
            clean_title = story['title'].strip().split("\n")[0] if story else title
            encoded_title = clean_title.replace(" ", "_")
            delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"
            
            await add_user_purchase(user_id, clean_title, story_link=delivery_link)
            access_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (Unlocked)", style=enums.ButtonStyle.PRIMARY, url=delivery_link)]])
            
            await callback.message.reply_text(
                f"🎉 <b>ᴀᴜᴛᴏ-ᴠᴇʀɪғɪᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n📖 <b>Story:</b> {clean_title}\n💰 <b>Paid:</b> ₹{actual_paid}\n\nClick below to access your files:",
                reply_markup=access_btn,
                protect_content=True
            )
            
            if LOG_CHANNEL and LOG_CHANNEL != 0:
                await client.send_message(
                    LOG_CHANNEL, 
                    f"⚡ <b>[DIRECT VERIFY SUCCESS] STORY BOUGHT</b>\n👤 <b>User:</b> {callback.from_user.first_name} (<code>{user_id}</code>)\n📖 <b>Story:</b> {clean_title}\n💰 <b>Amount:</b> ₹{actual_paid}"
                )
    else:
        await callback.answer(f"❌ Payment Not Detected!\n{msg}\n\nAgar payment complete ho gaya hai toh 10 sec baad firse check karein.", show_alert=True)

# ---------------- WALLET TOPUP ----------------

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
        f"👇 <i>ᴘʟᴇᴀsᴇ ᴄʟɪᴄᴋ <b>'✅ ɪ ᴀᴄᴄᴇᴘᴛ & ᴄᴏɴᴛɪɴᴜᴇ'</b> ᴛᴏ ɢᴇɴᴇʀᴀᴛᴇ QR & ᴘᴀʏᴍᴇɴᴛ ʟɪɴᴋ:</i>"
    )
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ ɪ ᴀᴄᴄᴇᴘᴛ & ᴄᴏɴᴛɪɴᴜᴇ", style=enums.ButtonStyle.SUCCESS, callback_data=f"show_qr_{user_id}")],
        [InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
    ])
    await message.reply_photo(photo=GUIDE_IMAGE_URL, caption=terms_caption, reply_markup=btn)

# ---------------- MANUAL SCREENSHOT ----------------

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
    
    admin_text = (
        f"🚨 <b>ᴍᴀɴᴜᴀʟ ᴘᴀʏᴍᴇɴᴛ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ʀᴇǫᴜᴇsᴛ!</b>\n\n"
        f"👤 <b>User:</b> {user.first_name} (@{user.username if user.username else 'N/A'})\n"
        f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
        f"📌 <b>Item:</b> {title}\n"
        f"💰 <b>Amount:</b> ₹{price}"
    )
    
    clean_title = title.replace(" ", "_")
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ ᴀᴘᴘʀᴏᴠᴇ", callback_data=f"app_{user.id}_{clean_title}_{price}"), InlineKeyboardButton("❌ ʀᴇᴊᴇᴄᴛ", callback_data=f"rej_{user.id}_{clean_title}")]
    ])
    
    await client.send_photo(chat_id=ADMIN_ID, photo=message.photo.file_id, caption=admin_text, reply_markup=btn)
    await message.reply_text("✅ <b>Screenshot received!</b> Admin will review and approve shortly.")
    ACTIVE_PAYMENTS.pop(user_id, None)

# Admin Handlers
@Client.on_callback_query(filters.regex("^app_") & filters.user(ADMIN_ID))
async def approve_order(client, callback):
    data = callback.data.split("_")
    user_id = int(data[1])
    price = float(data[-1])
    title = "_".join(data[2:-1]).replace("_", " ")
    
    if title == "WalletTopup":
        new_balance = await add_wallet_balance(user_id, price)
        await client.send_message(chat_id=user_id, text=f"🎉 <b>ᴡᴀʟʟᴇᴛ ᴛᴏᴘ-ᴜᴘ ᴀᴘᴘʀᴏᴠᴇᴅ!</b>\n💰 Added: ₹{price}\n👛 Balance: ₹{new_balance}")
        await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n✅ <b>APPROVED BY ADMIN</b>")
        return await callback.answer("Wallet Approved!", show_alert=True)

    story = await get_story_by_title(title)
    clean_title = story['title'].strip().split("\n")[0] if story else title
    encoded_title = clean_title.replace(" ", "_")
    delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"

    await add_user_purchase(user_id, clean_title, story_link=delivery_link)
    access_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (Unlocked)", style=enums.ButtonStyle.PRIMARY, url=delivery_link)]])
    
    await client.send_message(
        chat_id=user_id,
        text=f"🎉 <b>ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ʜᴀs ʙᴇᴇɴ ᴀᴘᴘʀᴏᴠᴇᴅ!</b>\n📖 Story: {clean_title}",
        reply_markup=access_btn,
        protect_content=True
    )
    await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n✅ <b>APPROVED BY ADMIN</b>")
    await callback.answer("Approved!", show_alert=True)

@Client.on_callback_query(filters.regex("^rej_") & filters.user(ADMIN_ID))
async def reject_order(client, callback):
    data = callback.data.split("_")
    user_id = int(data[1])
    title = "_".join(data[2:]).replace("_", " ")
    
    await client.send_message(chat_id=user_id, text=f"❌ <b>ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ʜᴀs ʙᴇᴇɴ ʀᴇᴊᴇᴄᴛᴇᴅ!</b>\nItem: {title}")
    await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n❌ <b>REJECTED BY ADMIN</b>")
    await callback.answer("Rejected!", show_alert=True)
