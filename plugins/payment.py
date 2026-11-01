import io
import time
import asyncio
import gc
from PIL import Image
import qrcode

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Config Imports
from config import ADMIN_ID, BOT_USERNAME, LOG_CHANNEL, UPI_ID
from gateway import create_order, check_order_status, extract_upi_payload, is_quota_error, is_blocked_error, get_upi_id
from fulfill import fulfill_order
from database.db import (
    get_setting,
    get_story_by_key,
    add_user_purchase,
    add_wallet_balance,
    create_payment_order,
    get_payment_order,
    get_latest_open_order,
    delivery_link,
)

# Global Dictionaries
_LAST_QUOTA_ALERT = [0.0]   # admin ko limit-alert har ghante me ek baar
ACTIVE_PAYMENTS = {}        # sirf manual-screenshot flow ke liye (order ka asli record DB me hota hai)
WALLET_TOPUP_WAITING = {}   

GUIDE_IMAGE_URL = "https://i.ibb.co/359XV31J/photo-2026-10-01-02-31-01-7691521352814455808.jpg" 


def _clean(title: str) -> str:
    return (title or "").strip().split("\n")[0]


def _skey(story: dict) -> str:
    """Button / link me jaane wali key: random story_id (title kabhi nahi)."""
    sid = story.get("story_id")
    if sid:
        return str(sid)
    return _clean(story.get("title", "")).replace(" ", "_")[:40]


# ---------------- 0. LOG HELPER FUNCTION ----------------

async def send_log_to_channel(client: Client, text: str):
    """Safe async logger to channel"""
    if LOG_CHANNEL and LOG_CHANNEL != 0:
        try:
            await client.send_message(
                chat_id=LOG_CHANNEL,
                text=text,
                disable_web_page_preview=True
            )
        except Exception as e:
            print(f"❌ LOG_CHANNEL Error: {e}")


async def _temp_notice(message, text: str, seconds: int = 10):
    """Chhota message bhejo aur kuch second baad hata do."""
    try:
        note = await message.reply_text(text)
    except Exception:
        return

    async def _cleanup():
        await asyncio.sleep(seconds)
        try:
            await note.delete()
        except Exception:
            pass

    asyncio.create_task(_cleanup())


# ---------------- 1. QR CARD ----------------

def sync_generate_exact_website_qr_card(amount_text: str, qr_payload: str) -> io.BytesIO:
    """Pure QR Code Generator (No Text / No Price). Centered 400x400 QR Image."""
    img_w, img_h = 500, 500
    
    card = Image.new("RGB", (img_w, img_h), (255, 255, 255))

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=1,
    )
    qr.add_data(qr_payload)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB").resize((400, 400), Image.Resampling.LANCZOS)

    card.paste(qr_img, (50, 50))

    bio = io.BytesIO()
    bio.name = "website_qr_card.png"
    card.save(bio, "PNG", optimize=True)
    bio.seek(0)
    
    del card
    del qr_img
    gc.collect()

    return bio


async def generate_exact_website_qr_card(amount_text: str, qr_payload: str) -> io.BytesIO:
    """Non-blocking async wrapper around Image generation."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, sync_generate_exact_website_qr_card, amount_text, qr_payload)


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
    await callback.answer()
    
    await asyncio.sleep(10)
    try:
        await cancel_msg.delete()
    except Exception:
        pass

# ---------------- VIEW STORY ----------------

@Client.on_callback_query(filters.regex("^view_"))
async def view_story(client, callback):
    key = callback.data[len("view_"):]
    story = await get_story_by_key(key)
    if not story:
        return await callback.answer("❌ sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ!", show_alert=True)
        
    clean_title = _clean(story['title'])
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("💳 ʙᴜʏ ɴᴏᴡ", style=enums.ButtonStyle.PRIMARY, callback_data=f"buy:{_skey(story)}")]])
    
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

# ---------------- STEP 1: DIRECT MEDIATOR (CHOOSE PAYMENT METHOD) ----------------

@Client.on_callback_query(filters.regex(r"^buy[_:]"))
async def show_payment_methods(client, callback):
    data = callback.data
    try:
        if data.startswith("buy:"):
            key = data[4:]
        else:
            # purana format: buy_<title>_<price>
            raw = data[4:]
            key = raw.rsplit("_", 1)[0] if "_" in raw else raw
    except Exception:
        return await callback.answer("❌ ᴇʀʀᴏʀ ᴘᴀʀsɪɴɢ ᴘᴀʏᴍᴇɴᴛ ᴅᴀᴛᴀ!", show_alert=True)

    story = await get_story_by_key(key)
    if not story:
        return await callback.answer("❌ Story not found or removed!", show_alert=True)

    # Price hamesha database se (callback me bheja gaya price par bharosa nahi)
    price = float(story.get("price", 0) or 0)
    if price <= 0:
        return await callback.answer("❌ Is story ka price set nahi hai. Admin se contact karein.", show_alert=True)

    story_title = _clean(story["title"])
    sid = _skey(story)
    user_id = callback.from_user.id
    ACTIVE_PAYMENTS[user_id] = {
        "title": story_title,
        "story_id": sid,
        "price": price,
        "timestamp": time.time(),
        "type": "STORY"
    }

    mediator_caption = (
        f"💳 <b><u>sᴇʟᴇᴄᴛ ᴘᴀʏᴍᴇɴᴛ ᴍᴇᴛʜᴏᴅ</u></b>\n\n"
        f"📌 <b>Item:</b> {story_title}\n"
        f"💰 <b>Amount:</b> ₹{price:g}\n\n"
        f"<i>Please choose how you would like to complete your payment:</i>"
    )

    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ ᴀᴜᴛᴏ ᴜᴘɪ (ɪɴsᴛᴀɴᴛ)", style=enums.ButtonStyle.PRIMARY, callback_data=f"payqr:S:{sid}")],
        [InlineKeyboardButton("📲 ᴍᴀɴᴜᴀʟ (sᴄʀᴇᴇɴsʜᴏᴛ)", callback_data=f"paymanual:S:{sid}")],
        [InlineKeyboardButton("💬 ᴄᴏɴᴛᴀᴄᴛ ᴏᴡɴᴇʀ", url=f"https://t.me/hdfilm0900_bot")],
        [InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
    ])

    try:
        await callback.message.reply_photo(
            photo=GUIDE_IMAGE_URL,
            caption=mediator_caption,
            reply_markup=btn
        )
    except Exception:
        await callback.message.reply_text(mediator_caption, reply_markup=btn)

    await callback.answer()

# ---------------- STEP 2: GENERATE DIRECT UPI QR CARD ----------------

async def _resolve_payment_target(data: str, legacy_prefix: str, new_prefix: str):
    """
    Callback data se (kind, story, price, title, ref) nikalta hai.
    Naya: <new_prefix>S:<story_id>  /  <new_prefix>W:<amount>
    Purana: legacy_prefix wala format (title based) bhi chalta hai.
    Story ka price hamesha DB se aata hai.
    """
    story = None
    if data.startswith(new_prefix):
        k, ref = data[len(new_prefix):].split(":", 1)
        if k == "W":
            amount = float(ref)
            return "WALLET", None, amount, "WalletTopup", ref
        story = await get_story_by_key(ref)
    else:
        raw = data[len(legacy_prefix):]
        if legacy_prefix == "show_qr_":
            price_str, ref = raw.split("_", 1)
        else:  # "sent_"
            ref, price_str = raw.rsplit("_", 1)
        if ref == "WalletTopup":
            return "WALLET", None, float(price_str), "WalletTopup", price_str
        story = await get_story_by_key(ref)

    if not story:
        return "STORY", None, 0.0, "", ""
    return "STORY", story, float(story.get("price", 0) or 0), _clean(story["title"]), _skey(story)


@Client.on_callback_query(filters.regex(r"^(show_qr_|payqr:)"))
async def generate_qr_after_terms(client, callback):
    user_id = callback.from_user.id

    try:
        kind, story, price, title, ref = await _resolve_payment_target(callback.data, "show_qr_", "payqr:")
    except Exception:
        return await callback.answer("❌ Invalid payment data. Please click Buy again.", show_alert=True)

    if kind == "STORY" and not story:
        return await callback.answer("❌ Story not found or removed!", show_alert=True)
    if price <= 0:
        return await callback.answer("❌ Invalid amount!", show_alert=True)

    # Admin ne Auto UPI ko maintenance par rakha hai -> popup (default: ON, /autopay on se chalu karein)
    if await get_setting("auto_pay_maintenance", True):
        return await callback.answer(
            "🛠 Auto UPI abhi Under Maintenance hai.\n\nKripya 'Manual (Screenshot)' option se payment karein.",
            show_alert=True
        )

    story_id = ref if kind == "STORY" else None
    ref_part = f"S:{ref}" if kind == "STORY" else f"W:{price:g}"
    retry_cb = f"payqr:{ref_part}"
    manual_cb = f"paymanual:{ref_part}"

    await callback.answer("⏳ Payment link ban raha hai...")
    customer_name = callback.from_user.first_name or "Customer"

    pay_url, gen_order_id, err, gw_meta = await create_order(user_id, customer_name, price)

    # ---- Gateway ne order nahi banaya: nakli QR NAHI dikhana (wo kabhi verify nahi hota) ----
    if not pay_url:
        quota_hit = is_quota_error(err) or is_blocked_error(err)  # dono me Try Again bekaar, Manual dikhao
        if quota_hit:
            # Gateway plan ki monthly limit khatam: Try Again bekaar hai, seedha Manual dikhao
            error_text = (
                "⚠️ <b>ᴀᴜᴛᴏ ᴘᴀʏᴍᴇɴᴛ ᴀʙʜɪ ᴀᴠᴀɪʟᴀʙʟᴇ ɴᴀʜɪ ʜᴀɪ</b>\n\n"
                "Kripya <b>Manual (Screenshot)</b> option se payment karein. "
                "Admin screenshot check karke approve kar dega."
            )
            error_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📲 ᴍᴀɴᴜᴀʟ (sᴄʀᴇᴇɴsʜᴏᴛ)", style=enums.ButtonStyle.PRIMARY, callback_data=manual_cb)],
                [InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
            ])
        else:
            error_text = (
                "⚠️ <b>ᴘᴀʏᴍᴇɴᴛ ɢᴀᴛᴇᴡᴀʏ ᴀʙʜɪ ʙᴜsʏ ʜᴀɪ</b>\n\n"
                "Payment link nahi ban paya. Kripya thodi der baad <b>Try Again</b> dabayein, "
                "ya <b>Manual</b> option se screenshot bhejein."
            )
            error_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 ᴛʀʏ ᴀɢᴀɪɴ", style=enums.ButtonStyle.PRIMARY, callback_data=retry_cb)],
                [InlineKeyboardButton("📲 ᴍᴀɴᴜᴀʟ (sᴄʀᴇᴇɴsʜᴏᴛ)", callback_data=manual_cb)],
                [InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
            ])
        try:
            await callback.message.edit_caption(caption=error_text, reply_markup=error_kb)
        except Exception:
            try:
                await callback.message.reply_text(error_text, reply_markup=error_kb)
            except Exception:
                pass

        if quota_hit:
            if time.time() - _LAST_QUOTA_ALERT[0] > 3600:
                _LAST_QUOTA_ALERT[0] = time.time()
                try:
                    await client.send_message(
                        ADMIN_ID,
                        "🚨 <b>Gateway se order nahi ban pa raha!</b>\n\n"
                        "Wajah: monthly limit khatam ya gateway ne bot-protection (403) laga di. "
                        "demotry.shop support se baat karein / plan check karein. "
                        "Tab tak users ko sirf Manual (screenshot) option dikh raha hai.\n\n"
                        f"<code>{str(err)[:200]}</code>"
                    )
                except Exception:
                    pass
            return

        await send_log_to_channel(
            client,
            f"⚠️ <b>[GATEWAY] Order create failed</b>\n\n"
            f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
            f"📌 <b>Item:</b> {title}\n"
            f"💰 <b>Amount:</b> ₹{price:g}\n"
            f"🧾 <b>Reason:</b> <code>{str(err)[:300]}</code>"
        )
        return

    # ---- Order ban gaya: DB me record (restart ke baad bhi verify chalega) ----
    await create_payment_order(
        gen_order_id, user_id, price, kind,
        story_id=story_id, title=title, pay_url=pay_url,
        provider=gw_meta.get("provider"), provider_ref=gw_meta.get("provider_ref")
    )
    ACTIVE_PAYMENTS[user_id] = {
        "title": title,
        "story_id": story_id,
        "price": price,
        "timestamp": time.time(),
        "type": kind,
        "order_id": gen_order_id
    }

    display_amount = f"{price:.2f}"
    provider = gw_meta.get("provider")

    qr_image_bytes = None
    if provider == "demotry":
        qr_payload = None
        if str(pay_url).startswith("http"):
            qr_payload = await extract_upi_payload(pay_url)

        if qr_payload:
            if "tn=" not in qr_payload:
                qr_payload += f"&tn={gen_order_id}"
        else:
            upi_id = await get_upi_id()
            qr_payload = f"upi://pay?pa={upi_id}&pn=StorySeller&am={display_amount}&cu=INR&tr={gen_order_id}&tn={gen_order_id}"

        qr_image_bytes = await generate_exact_website_qr_card(display_amount, qr_payload)

        caption = (
            f"⚡ <b>ᴀᴜᴛᴏᴍᴀᴛɪᴄ ᴘᴀʏᴍᴇɴᴛ ᴄʜᴇᴄᴋᴏᴜᴛ</b>\n\n"
            f"📖 <b>ITEM:</b> {title}\n"
            f"💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{display_amount}\n"
            f"🆔 <b>ᴏʀᴅᴇʀ ɪᴅ:</b> <code>{gen_order_id}</code>\n"
            f"⏳ <b>ᴛɪᴍᴇ ʟɪᴍɪᴛ:</b> 10 Minutes\n\n"
            f"📲 <i>1. Scan this QR code using PhonePe, GPay, Paytm, or BHIM App.\n"
            f"2. Click <b>'⚡ ᴠᴇʀɪғʏ ᴘᴀʏᴍᴇɴᴛ'</b> below after paying!</i>"
        )
    else:
        caption = (
            f"⚡ <b>ᴀᴜᴛᴏᴍᴀᴛɪᴄ ᴘᴀʏᴍᴇɴᴛ ᴄʜᴇᴄᴋᴏᴜᴛ</b>\n\n"
            f"📖 <b>ITEM:</b> {title}\n"
            f"💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{display_amount}\n"
            f"🆔 <b>ᴏʀᴅᴇʀ ɪᴅ:</b> <code>{gen_order_id}</code>\n\n"
            f"📲 <i>1. Click <b>'🌐 ᴏᴘᴇɴ ᴘᴀʏᴍᴇɴᴛ ᴘᴀɢᴇ'</b> and pay using UPI / Card.\n"
            f"2. After paying, come back and click <b>'⚡ ᴠᴇʀɪғʏ ᴘᴀʏᴍᴇɴᴛ'</b>!</i>"
        )

    btn_list = []
    if str(pay_url).startswith(("http://", "https://")):
        btn_list.append([InlineKeyboardButton("🌐 ᴏᴘᴇɴ ᴘᴀʏᴍᴇɴᴛ ᴘᴀɢᴇ", style=enums.ButtonStyle.PRIMARY, url=pay_url)])
    btn_list.append([InlineKeyboardButton("⚡ ᴠᴇʀɪғʏ ᴘᴀʏᴍᴇɴᴛ", style=enums.ButtonStyle.SUCCESS, callback_data=f"chk:{gen_order_id}")])
    btn_list.append([InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")])

    if qr_image_bytes:
        await callback.message.reply_photo(
            photo=qr_image_bytes,
            caption=caption,
            reply_markup=InlineKeyboardMarkup(btn_list)
        )
    else:
        await callback.message.reply_text(caption, reply_markup=InlineKeyboardMarkup(btn_list))

    # Naya QR bhej dene ke BAAD purana mediator message hatao
    try:
        await callback.message.delete()
    except Exception:
        pass

# ---------------- STEP 3: VERIFY PAYMENT STATUS ----------------

@Client.on_callback_query(filters.regex(r"^(chk:|auto_check_payment_)"))
async def direct_verify_payment(client, callback):
    user_id = callback.from_user.id
    data = callback.data

    if data.startswith("chk:"):
        order = await get_payment_order(data[4:])
    else:
        # purane message ka button: user ka sabse naya khula order
        order = await get_latest_open_order(user_id)

    if not order or order["user_id"] != user_id:
        return await callback.answer("⏰ Session Expired! Please try again.", show_alert=True)

    if order.get("status") == "PAID":
        return await callback.answer(
            "✅ Ye payment pehle hi verify ho chuka hai. Apna chat ya My Account check karein.",
            show_alert=True
        )

    await callback.answer("🔍 Payment check ho raha hai...")

    is_valid, actual_paid, msg = await check_order_status(order["order_id"])
    if not is_valid:
        await asyncio.sleep(2)
        is_valid, actual_paid, msg = await check_order_status(order["order_id"])

    if is_valid:
        result = await fulfill_order(client, order, actual_paid, "AUTO VERIFY")
        ACTIVE_PAYMENTS.pop(user_id, None)
        if result == "error":
            await _temp_notice(
                callback.message,
                "⚠️ <b>Payment mil gaya hai par update me dikkat aayi.</b>\nKripya 1 minute baad dobara <b>Verify</b> dabayein.",
                15
            )
        return

    await _temp_notice(
        callback.message,
        "❌ <b>Payment abhi tak nahi mila.</b>\nPayment hone ke 10-20 second baad dobara Verify dabayein.",
        8
    )

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

    mediator_caption = (
        f"💳 <b><u>sᴇʟᴇᴄᴛ ᴘᴀʏᴍᴇɴᴛ ᴍᴇᴛʜᴏᴅ</u></b>\n\n"
        f"👛 <b>Wallet Top-Up:</b> ₹{price:g}\n\n"
        f"<i>Please choose how you would like to complete your payment:</i>"
    )

    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ ᴀᴜᴛᴏ ᴜᴘɪ (ɪɴsᴛᴀɴᴛ)", style=enums.ButtonStyle.PRIMARY, callback_data=f"payqr:W:{price:g}")],
        [InlineKeyboardButton("📲 ᴍᴀɴᴜᴀʟ  (sᴄʀᴇᴇɴsʜᴏᴛ)", callback_data=f"paymanual:W:{price:g}")],
        [InlineKeyboardButton("💬 ᴄᴏɴᴛᴀᴄᴛ ᴏᴡɴᴇʀ", url=f"https://t.me/hdfilm0900_bot")],
        [InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
    ])

    await message.reply_photo(photo=GUIDE_IMAGE_URL, caption=mediator_caption, reply_markup=btn)

# ---------------- MANUAL SCREENSHOT (SHOWS UPI ID FIRST) ----------------

@Client.on_callback_query(filters.regex(r"^(sent_|paymanual:)"))
async def ask_screenshot(client, callback):
    try:
        kind, story, price, story_title, ref = await _resolve_payment_target(callback.data, "sent_", "paymanual:")
    except Exception:
        return await callback.answer("❌ Error parsing data!", show_alert=True)

    if kind == "STORY" and not story:
        return await callback.answer("❌ Story not found or removed!", show_alert=True)
    if price <= 0:
        return await callback.answer("❌ Invalid amount!", show_alert=True)

    user_id = callback.from_user.id
    ACTIVE_PAYMENTS[user_id] = {
        "title": story_title,
        "story_id": ref if kind == "STORY" else None,
        "price": price,
        "manual": True,
        "type": kind
    }
    
    try:
        await callback.message.delete()
    except Exception:
        pass

    upi_id = await get_upi_id()
    manual_text = (
        f"📲 <b><u>ᴍᴀɴᴜᴀʟ ᴜᴘɪ ᴘᴀʏᴍᴇɴᴛ</u></b>\n\n"
        f"📌 <b>Item:</b> {story_title}\n"
        f"💰 <b>Amount:</b> ₹{price:g}\n\n"
        f"👇 <b>Pay to this UPI ID:</b>\n"
        f"<code>{upi_id}</code>\n\n"
        f"<i>(Tap the UPI ID above to copy it)</i>\n\n"
        f"📸 <b>After payment, please send your payment screenshot photo directly in this chat.</b>"
    )

    await callback.message.reply_text(
        text=manual_text,
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
    pay_type = data.get('type', 'STORY')
    user = message.from_user
    
    admin_text = (
        f"🚨 <b>ᴍᴀɴᴜᴀʟ ᴘᴀʏᴍᴇɴᴛ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ʀᴇǫᴜᴇsᴛ!</b>\n\n"
        f"👤 <b>User:</b> {user.first_name} (@{user.username if user.username else 'N/A'})\n"
        f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
        f"📌 <b>Item/Type:</b> {title} ({pay_type})\n"
        f"💰 <b>Amount:</b> ₹{price:g}"
    )
    
    if pay_type == "WALLET":
        ref_part = f"W:{price:g}"
    else:
        ref_part = f"S:{data.get('story_id') or _clean(title).replace(' ', '_')[:40]}"

    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ ᴀᴘᴘʀᴏᴠᴇ", callback_data=f"app:{user.id}:{ref_part}"), InlineKeyboardButton("❌ ʀᴇᴊᴇᴄᴛ", callback_data=f"rej:{user.id}:{ref_part}")]
    ])
    
    await client.send_photo(chat_id=ADMIN_ID, photo=message.photo.file_id, caption=admin_text, reply_markup=btn)
    await message.reply_text("✅ <b>Screenshot received!</b> Admin will review and approve shortly.")
    ACTIVE_PAYMENTS.pop(user_id, None)

# ---------------- ADMIN APPROVE & REJECT HANDLERS ----------------

def _already_handled(callback) -> bool:
    caption = callback.message.caption or ""
    return ("APPROVED BY ADMIN" in caption) or ("REJECTED BY ADMIN" in caption)


@Client.on_callback_query(filters.regex(r"^app[_:]") & filters.user(ADMIN_ID))
async def approve_order(client, callback):
    # Admin ne do baar button dabaya to wallet do baar na jude
    if _already_handled(callback):
        return await callback.answer("⚠️ Ye request pehle hi process ho chuki hai.", show_alert=True)

    data = callback.data
    story = None
    try:
        if data.startswith("app:"):
            _, uid_str, k, ref = data.split(":", 3)
            user_id = int(uid_str)
            is_wallet = (k == "W")
            if is_wallet:
                price = float(ref)
            else:
                story = await get_story_by_key(ref)
                price = float(story.get("price", 0) or 0) if story else 0.0
        else:
            # purana format: app_<uid>_<price>_<type>_<title>
            raw_data = data[4:]
            user_id_str, price_str, pay_type, clean_title = raw_data.split("_", 3)
            user_id = int(user_id_str)
            price = float(price_str)
            is_wallet = (clean_title == "WalletTopup" or pay_type == "WALLET")
            if not is_wallet:
                story = await get_story_by_key(clean_title)
    except Exception as e:
        print(f"Approval Parse Error: {e}")
        return await callback.answer("❌ Error parsing approval callback data!", show_alert=True)

    # --- 1. MANUAL WALLET APPROVAL ---
    if is_wallet:
        new_balance = await add_wallet_balance(user_id, price)
        try:
            await client.send_message(
                chat_id=user_id,
                text=f"🎉 <b>ᴡᴀʟʟᴇᴛ ᴛᴏᴘ-ᴜᴘ ᴀᴘᴘʀᴏᴠᴇᴅ!</b>\n💰 Added: ₹{price:g}\n👛 Balance: ₹{new_balance}"
            )
        except Exception as e:
            print(f"Approve: user ko message nahi gaya: {e}")
        await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n✅ <b>APPROVED BY ADMIN</b>")
        await callback.answer("Wallet Approved!", show_alert=True)
        
        log_msg = (
            f"🛠️ <b>[MANUAL APPROVED] WALLET TOP-UP</b>\n\n"
            f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
            f"💰 <b>Amount Added:</b> ₹{price:g}\n"
            f"👛 <b>New Balance:</b> ₹{new_balance}\n"
            f"👮 <b>Approved By:</b> Admin"
        )
        await send_log_to_channel(client, log_msg)
        return

    # --- 2. MANUAL STORY BUY APPROVAL ---
    if not story:
        return await callback.answer("❌ Story database me nahi mili (delete ho gayi?). Approve nahi hua.", show_alert=True)

    clean_title_full = _clean(story['title'])
    story_id = story.get("story_id")
    link = delivery_link(story_id) if story_id else None

    await add_user_purchase(user_id, clean_title_full, story_id=story_id)
    access_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (Unlocked)", style=enums.ButtonStyle.PRIMARY, url=link)]]) if link else None
    
    try:
        await client.send_message(
            chat_id=user_id,
            text=f"🎉 <b>ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ʜᴀs ʙᴇᴇɴ ᴀᴘᴘʀᴏᴠᴇᴅ!</b>\n📖 Story: {clean_title_full}",
            reply_markup=access_btn,
            protect_content=False
        )
    except Exception as e:
        print(f"Approve: user ko message nahi gaya: {e}")
    await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n✅ <b>APPROVED BY ADMIN</b>")
    await callback.answer("Approved!", show_alert=True)
    
    log_msg = (
        f"🛠️ <b>[MANUAL APPROVED] STORY BOUGHT</b>\n\n"
        f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
        f"📖 <b>Story:</b> {clean_title_full}\n"
        f"💰 <b>Amount:</b> ₹{price:g}\n"
        f"👮 <b>Approved By:</b> Admin"
    )
    await send_log_to_channel(client, log_msg)


@Client.on_callback_query(filters.regex(r"^rej[_:]") & filters.user(ADMIN_ID))
async def reject_order(client, callback):
    if _already_handled(callback):
        return await callback.answer("⚠️ Ye request pehle hi process ho chuki hai.", show_alert=True)

    data = callback.data
    try:
        if data.startswith("rej:"):
            _, uid_str, k, ref = data.split(":", 3)
            user_id = int(uid_str)
            if k == "W":
                title = f"Wallet Top-up ₹{ref}"
            else:
                story = await get_story_by_key(ref)
                title = _clean(story["title"]) if story else ref
        else:
            raw_data = data[4:]
            user_id_str, clean_title = raw_data.split("_", 1)
            user_id = int(user_id_str)
            title = clean_title.replace("_", " ")
    except Exception:
        return await callback.answer("❌ Error parsing reject callback data!", show_alert=True)
    
    try:
        await client.send_message(chat_id=user_id, text=f"❌ <b>ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ʜᴀs ʙᴇᴇɴ ʀᴇᴊᴇᴄᴛᴇᴅ!</b>\nItem: {title}")
    except Exception as e:
        print(f"Reject: user ko message nahi gaya: {e}")
    await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n❌ <b>REJECTED BY ADMIN</b>")
    await callback.answer("Rejected!", show_alert=True)
    
    log_msg = (
        f"❌ <b>[MANUAL REJECTED] PAYMENT DECLINED</b>\n\n"
        f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
        f"📌 <b>Item:</b> {title}\n"
        f"👮 <b>Rejected By:</b> Admin"
    )
    await send_log_to_channel(client, log_msg)
