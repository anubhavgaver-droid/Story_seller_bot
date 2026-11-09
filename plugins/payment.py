import io
import re
import time
import asyncio
import gc
from PIL import Image
import qrcode

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Config Imports
from config import ADMIN_ID, BOT_USERNAME, LOG_CHANNEL
from gateway import create_order, check_order_status, extract_upi_payload, is_quota_error, is_blocked_error, get_upi_id
from fulfill import fulfill_order
import emailpay
from freeflow import start_free_claim
from bonus import bonus_amount, bonus_hint
from style import sc
from database.db import (
    get_setting,
    get_story_by_key,
    add_user_purchase,
    add_wallet_balance,
    create_payment_order,
    get_payment_order,
    get_latest_open_order,
    delivery_link,
    utr_exists,
    claim_utr,
    set_order_utr,
)

# Global state
_LAST_QUOTA_ALERT = [0.0]   # the admin gets the "gateway problem" alert at most once per hour
ACTIVE_PAYMENTS = {}        # only used by the manual-screenshot flow (the real order record lives in the database)
WALLET_TOPUP_WAITING = {}
UTR_WAITING = {}            # user_id -> order_id: the user tapped Submit UTR and must now send the 12-digit UTR
_UTR_LAST = {}              # user_id -> time of the last UTR check (stops spamming the mailbox)

GUIDE_IMAGE_URL = "https://i.ibb.co/359XV31J/photo-2026-10-01-02-31-01-7691521352814455808.jpg"
UTR_RE = re.compile(r"\b(\d{12})\b")


def _clean(title: str) -> str:
    return (title or "").strip().split("\n")[0]


def _skey(story: dict) -> str:
    """Key used in buttons and links: the random story_id (never the title)."""
    sid = story.get("story_id")
    if sid:
        return str(sid)
    return _clean(story.get("title", "")).replace(" ", "_")[:40]


# ---------------- 0. LOG HELPER ----------------

async def send_log_to_channel(client: Client, text: str):
    """Safe async logger to the log channel."""
    if LOG_CHANNEL and LOG_CHANNEL != 0:
        try:
            await client.send_message(chat_id=LOG_CHANNEL, text=text, disable_web_page_preview=True)
        except Exception as e:
            print(f"LOG_CHANNEL error: {e}")


async def _temp_notice(message, text: str, seconds: int = 10):
    """Sends a short message and removes it after a few seconds."""
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
    """Plain QR code (no text, no price), centred on a 500x500 white card."""
    img_w, img_h = 500, 500
    card = Image.new("RGB", (img_w, img_h), (255, 255, 255))

    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=1)
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
    """Non-blocking async wrapper around the image generation."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, sync_generate_exact_website_qr_card, amount_text, qr_payload)


# ---------------- CANCEL HANDLER ----------------

@Client.on_callback_query(filters.regex("^cancel_payment_process$"))
async def cancel_payment_callback(client, callback):
    user_id = callback.from_user.id
    ACTIVE_PAYMENTS.pop(user_id, None)
    WALLET_TOPUP_WAITING.pop(user_id, None)
    UTR_WAITING.pop(user_id, None)

    try:
        await callback.message.delete()
    except Exception:
        pass

    cancel_msg = await callback.message.reply_text(f"❌ <b>{sc('Payment / top-up cancelled')}</b>")
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
        return await callback.answer("Story not found.", show_alert=True)

    clean_title = _clean(story['title'])
    btn = InlineKeyboardMarkup([[InlineKeyboardButton(f"💳 {sc('Buy now')}", style=enums.ButtonStyle.PRIMARY, callback_data=f"buy:{_skey(story)}")]])

    caption_text = (
        f"♨️ <b>Story :</b> {clean_title}\n"
        f"🔰 <b>Status :</b> {story.get('status', 'Completed')}\n"
        f"🖥️ <b>Platform :</b> {story.get('category', 'Pocket FM')}\n"
        f"🧩 <b>Genre :</b> {story.get('genre', 'Drama')}\n"
        f"🎬 <b>Episodes :</b> {story.get('episodes', 'N/A')}\n\n"
        f"░▒▓█ PRICE - {'FREE 🎁' if not story.get('price') else '₹' + str(story['price'])} █▓▒░"
    )

    try:
        await callback.message.reply_photo(photo=story.get('photo', 'https://picsum.photos/400/200'), caption=caption_text, reply_markup=btn)
    except Exception:
        await callback.message.reply_text(caption_text, reply_markup=btn)
    await callback.answer()


# ---------------- STEP 1: CHOOSE A PAYMENT METHOD ----------------

@Client.on_callback_query(filters.regex(r"^buy[_:]"))
async def show_payment_methods(client, callback):
    data = callback.data
    try:
        if data.startswith("buy:"):
            key = data[4:]
        else:
            # old format: buy_<title>_<price>
            raw = data[4:]
            key = raw.rsplit("_", 1)[0] if "_" in raw else raw
    except Exception:
        return await callback.answer("Could not read the payment data.", show_alert=True)

    story = await get_story_by_key(key)
    if not story:
        return await callback.answer("This story was not found or has been removed.", show_alert=True)

    # The price always comes from the database, never from the button.
    price = float(story.get("price", 0) or 0)
    if price <= 0:
        # Free story: no payment, go to the Claim Free flow (ad gate if it is ON)
        await callback.answer("This story is free!")
        await start_free_claim(client, callback.from_user.id, story)
        return

    story_title = _clean(story["title"])
    sid = _skey(story)
    user_id = callback.from_user.id
    ACTIVE_PAYMENTS[user_id] = {"title": story_title, "story_id": sid, "price": price, "timestamp": time.time(), "type": "STORY"}

    mediator_caption = (
        f"💳 <b><u>{sc('Select payment method')}</u></b>\n\n"
        f"📌 <b>{sc('Item')}:</b> {story_title}\n"
        f"💰 <b>{sc('Amount')}:</b> ₹{price:g}\n\n"
        f"<i>Please choose how you would like to complete your payment:</i>"
    )

    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⚡ {sc('Auto UPI (instant)')}", style=enums.ButtonStyle.PRIMARY, callback_data=f"payqr:S:{sid}")],
        [InlineKeyboardButton(f"📲 {sc('Manual (screenshot)')}", callback_data=f"paymanual:S:{sid}")],
        [InlineKeyboardButton(f"💬 {sc('Contact owner')}", url="https://t.me/hdfilm0900_bot")],
        [InlineKeyboardButton(f"❌ {sc('Cancel')}", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
    ])

    try:
        await callback.message.reply_photo(photo=GUIDE_IMAGE_URL, caption=mediator_caption, reply_markup=btn)
    except Exception:
        await callback.message.reply_text(mediator_caption, reply_markup=btn)

    await callback.answer()


# ---------------- STEP 2: CREATE THE INVOICE ----------------

async def _resolve_payment_target(data: str, legacy_prefix: str, new_prefix: str):
    """
    Reads (kind, story, price, title, ref) from the callback data.
    New: <new_prefix>S:<story_id>  or  <new_prefix>W:<amount>
    Old: the title-based legacy_prefix format still works.
    A story's price always comes from the database.
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
        return await callback.answer("Invalid payment data. Please tap Buy again.", show_alert=True)

    if kind == "STORY" and not story:
        return await callback.answer("This story was not found or has been removed.", show_alert=True)
    if price <= 0:
        return await callback.answer("Invalid amount.", show_alert=True)

    # The admin put Auto UPI under maintenance -> popup (turn it back on with /setup or /autopay on)
    if await get_setting("auto_pay_maintenance", True):
        return await callback.answer(
            "Auto UPI is under maintenance right now.\n\nPlease use the 'Manual (Screenshot)' option to pay.",
            show_alert=True
        )

    story_id = ref if kind == "STORY" else None
    ref_part = f"S:{ref}" if kind == "STORY" else f"W:{price:g}"
    retry_cb = f"payqr:{ref_part}"
    manual_cb = f"paymanual:{ref_part}"

    # No popup at the top: stop the loading spinner silently and show a message at the bottom of the chat.
    await callback.answer()
    wait_msg = None
    try:
        wait_msg = await callback.message.reply_text(
            f"⏳ <b>{sc('Please wait')}</b>\nYour invoice is being generated. This takes 1 to 5 seconds..."
        )
    except Exception:
        pass

    customer_name = callback.from_user.first_name or "Customer"
    try:
        pay_url, gen_order_id, err, gw_meta = await create_order(user_id, customer_name, price)
    finally:
        if wait_msg:
            try:
                await wait_msg.delete()
            except Exception:
                pass

    # ---- The gateway did not create an order: never show a fake QR (it can never be verified) ----
    if not pay_url:
        quota_hit = is_quota_error(err) or is_blocked_error(err)  # Try Again is useless in both cases, so offer Manual
        if quota_hit:
            error_text = (
                f"⚠️ <b>{sc('Auto payment is unavailable right now')}</b>\n\n"
                "Please pay with the <b>Manual (Screenshot)</b> option. "
                "The admin will check your screenshot and approve it."
            )
            error_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📲 {sc('Manual (screenshot)')}", style=enums.ButtonStyle.PRIMARY, callback_data=manual_cb)],
                [InlineKeyboardButton(f"❌ {sc('Cancel')}", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
            ])
        else:
            error_text = (
                f"⚠️ <b>{sc('Payment gateway is busy')}</b>\n\n"
                "The payment link could not be created. Please tap <b>Try again</b> in a moment, "
                "or use the <b>Manual</b> option and send a screenshot."
            )
            error_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🔄 {sc('Try again')}", style=enums.ButtonStyle.PRIMARY, callback_data=retry_cb)],
                [InlineKeyboardButton(f"📲 {sc('Manual (screenshot)')}", callback_data=manual_cb)],
                [InlineKeyboardButton(f"❌ {sc('Cancel')}", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
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
                        f"🚨 <b>{sc('The gateway cannot create orders')}</b>\n\n"
                        "Reason: the monthly limit is reached, or the gateway's bot protection (403) is blocking the bot. "
                        "Check your plan or contact the gateway support. Until then users only see the Manual option.\n\n"
                        f"<code>{str(err)[:200]}</code>"
                    )
                except Exception:
                    pass
            return

        await send_log_to_channel(
            client,
            f"⚠️ <b>[GATEWAY] {sc('Order creation failed')}</b>\n\n"
            f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
            f"📌 <b>Item:</b> {title}\n"
            f"💰 <b>Amount:</b> ₹{price:g}\n"
            f"🧾 <b>Reason:</b> <code>{str(err)[:300]}</code>"
        )
        return

    # ---- Order created: save it (verification keeps working after a restart) ----
    await create_payment_order(
        gen_order_id, user_id, price, kind,
        story_id=story_id, title=title, pay_url=pay_url,
        provider=gw_meta.get("provider"), provider_ref=gw_meta.get("provider_ref"),
        payable_amount=gw_meta.get("payable_amount")
    )
    ACTIVE_PAYMENTS[user_id] = {
        "title": title, "story_id": story_id, "price": price,
        "timestamp": time.time(), "type": kind, "order_id": gen_order_id
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
            f"⚡ <b>{sc('Automatic payment checkout')}</b>\n\n"
            f"📖 <b>{sc('Item')}:</b> {title}\n"
            f"💰 <b>{sc('Amount')}:</b> ₹{display_amount}\n"
            f"🆔 <b>{sc('Order ID')}:</b> <code>{gen_order_id}</code>\n"
            f"⏳ <b>{sc('Time limit')}:</b> 10 minutes\n\n"
            f"📲 <i>1. Scan this QR code with PhonePe, GPay, Paytm or any UPI app.\n"
            f"2. After paying, tap <b>Verify payment</b> below.</i>"
        )
    elif provider == "email":
        # Plain price QR. The payment is verified from the UTR (transaction ID) the user submits.
        qr_image_bytes = await generate_exact_website_qr_card(display_amount, pay_url)
        caption = (
            f"⚡ <b>{sc('Automatic payment checkout')}</b>\n\n"
            f"📖 <b>{sc('Item')}:</b> {title}\n"
            f"💰 <b>{sc('Amount')}:</b> ₹{display_amount}\n"
            f"🆔 <b>{sc('Order ID')}:</b> <code>{gen_order_id}</code>\n"
            f"⏳ <b>{sc('Time limit')}:</b> 30 minutes\n\n"
            f"📲 <i>1. Scan the QR code with any UPI app and pay ₹{display_amount}.\n"
            f"2. After paying, tap <b>Submit UTR</b> and send the 12-digit UTR (transaction ID) from your UPI app.\n"
            f"3. Your payment is verified automatically. If it is not found yet, wait a minute and tap <b>Verify payment</b>.</i>"
        )
    else:
        caption = (
            f"⚡ <b>{sc('Automatic payment checkout')}</b>\n\n"
            f"📖 <b>{sc('Item')}:</b> {title}\n"
            f"💰 <b>{sc('Amount')}:</b> ₹{display_amount}\n"
            f"🆔 <b>{sc('Order ID')}:</b> <code>{gen_order_id}</code>\n\n"
            f"📲 <i>1. Tap <b>Open payment page</b> and pay with UPI or card.\n"
            f"2. After paying, come back and tap <b>Verify payment</b>.</i>"
        )

    btn_list = []
    if str(pay_url).startswith(("http://", "https://")):
        btn_list.append([InlineKeyboardButton(f"🌐 {sc('Open payment page')}", style=enums.ButtonStyle.PRIMARY, url=pay_url)])
    if provider == "email":
        btn_list.append([InlineKeyboardButton(f"🔢 {sc('Submit UTR')}", style=enums.ButtonStyle.PRIMARY, callback_data=f"utr:{gen_order_id}")])
    btn_list.append([InlineKeyboardButton(f"⚡ {sc('Verify payment')}", style=enums.ButtonStyle.SUCCESS, callback_data=f"chk:{gen_order_id}")])
    btn_list.append([InlineKeyboardButton(f"🆘 {sc('I paid but got nothing')}", callback_data=f"sos:{gen_order_id}")])
    btn_list.append([InlineKeyboardButton(f"❌ {sc('Cancel')}", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")])

    if qr_image_bytes:
        await callback.message.reply_photo(photo=qr_image_bytes, caption=caption, reply_markup=InlineKeyboardMarkup(btn_list))
    else:
        await callback.message.reply_text(caption, reply_markup=InlineKeyboardMarkup(btn_list))

    # Remove the old method-selection message only AFTER the new invoice has been sent
    try:
        await callback.message.delete()
    except Exception:
        pass


# ---------------- STEP 3: VERIFY THE PAYMENT ----------------

@Client.on_callback_query(filters.regex(r"^(chk:|auto_check_payment_)"))
async def direct_verify_payment(client, callback):
    user_id = callback.from_user.id
    data = callback.data

    if data.startswith("chk:"):
        order = await get_payment_order(data[4:])
    else:
        # button of an old message: the user's newest open order
        order = await get_latest_open_order(user_id)

    if not order or order["user_id"] != user_id:
        return await callback.answer("This session has expired. Please try again.", show_alert=True)

    if order.get("status") == "PAID":
        return await callback.answer(
            "This payment has already been verified. Please check your chat or My Account.",
            show_alert=True
        )

    is_email = order.get("provider") == "email"
    if is_email and not order.get("submitted_utr"):
        return await callback.answer("Please tap Submit UTR first and send your 12-digit UTR.", show_alert=True)

    await callback.answer("Checking your payment...")

    is_valid, actual_paid, msg = await check_order_status(order["order_id"])
    if not is_valid and not is_email:
        await asyncio.sleep(2)
        is_valid, actual_paid, msg = await check_order_status(order["order_id"])

    if is_valid:
        result = await fulfill_order(client, order, actual_paid, "AUTO VERIFY")
        ACTIVE_PAYMENTS.pop(user_id, None)
        if result == "error":
            await _temp_notice(
                callback.message,
                "⚠️ <b>Your payment was found, but the update failed.</b>\nPlease tap <b>Verify payment</b> again in a minute.",
                15
            )
        return

    if is_email:
        return await _temp_notice(
            callback.message,
            f"❌ <b>{msg}</b>\nIf you paid, wait a minute and tap Verify payment again, or tap Submit UTR to send the UTR again.",
            10
        )

    await _temp_notice(
        callback.message,
        "❌ <b>Payment not received yet.</b>\nPlease wait 10 to 20 seconds after paying and tap Verify again.",
        8
    )


# ---------------- SUBMIT UTR (mail-verified payments) ----------------

@Client.on_callback_query(filters.regex(r"^utr:"))
async def ask_utr(client, callback):
    user_id = callback.from_user.id
    order = await get_payment_order(callback.data[4:])
    if not order or order["user_id"] != user_id or order.get("provider") != "email":
        return await callback.answer("This session has expired. Please try again.", show_alert=True)
    if order.get("status") == "PAID":
        return await callback.answer("This payment has already been verified.", show_alert=True)

    UTR_WAITING[user_id] = order["order_id"]
    await callback.answer()
    await callback.message.reply_text(
        f"🔢 <b>{sc('Submit UTR')}</b>\n\n"
        "Please send the <b>12-digit UTR / transaction ID</b> of your payment.\n"
        "<i>You can find it in your UPI app under the payment details.</i>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"❌ {sc('Cancel')}", callback_data="cancel_payment_process")]])
    )


@Client.on_message(filters.private & filters.text & ~filters.command(["start", "cancel"]), group=3)
async def process_utr_input(client, message):
    user_id = message.from_user.id
    order_id = UTR_WAITING.get(user_id)
    if not order_id:
        message.continue_propagation()
        return

    utr = re.sub(r"\s+", "", message.text or "")
    if not re.fullmatch(r"\d{12}", utr):
        return await message.reply_text(
            f"❌ <b>{sc('Invalid UTR')}</b>\nThe UTR is exactly 12 digits. Please send it again."
        )

    if time.time() - _UTR_LAST.get(user_id, 0) < 10:
        return await message.reply_text("⏳ Please wait a few seconds before sending again.")
    _UTR_LAST[user_id] = time.time()

    order = await get_payment_order(order_id)
    if not order or order["user_id"] != user_id or order.get("provider") != "email":
        UTR_WAITING.pop(user_id, None)
        return await message.reply_text("This session has expired. Please start the payment again.")
    if order.get("status") == "PAID":
        UTR_WAITING.pop(user_id, None)
        return await message.reply_text("✅ This payment has already been verified.")

    UTR_WAITING.pop(user_id, None)
    await set_order_utr(order_id, utr)
    order["submitted_utr"] = utr

    checking = await message.reply_text("🔍 Checking your payment...")
    status, paid_amount = await emailpay.verify_order_utr(order)
    try:
        await checking.delete()
    except Exception:
        pass

    if status == "paid":
        result = await fulfill_order(client, order, paid_amount, "UTR VERIFY")
        ACTIVE_PAYMENTS.pop(user_id, None)
        if result == "error":
            await _temp_notice(
                message,
                "⚠️ <b>Your payment was found, but the update failed.</b>\nPlease tap <b>Verify payment</b> again in a minute.",
                15
            )
        return

    if status == "used":
        return await message.reply_text(
            f"⚠️ <b>{sc('This UTR was already used')}</b>\nPlease send the UTR of your new payment."
        )
    if status == "error":
        return await message.reply_text(
            "⚠️ The payment could not be checked right now.\nYour UTR is saved. Please tap <b>Verify payment</b> again in a minute."
        )
    await message.reply_text(
        f"⏳ <b>{sc('Payment not found yet')}</b>\n"
        "Your UTR is saved. Wait a minute, then tap <b>Verify payment</b>. "
        "If you sent a wrong UTR, tap <b>Submit UTR</b> again."
    )


# ---------------- WALLET TOP-UP ----------------

@Client.on_callback_query(filters.regex("^add_wallet_funds$"))
async def start_wallet_topup(client, callback):
    user_id = callback.from_user.id
    WALLET_TOPUP_WAITING[user_id] = True
    hint = await bonus_hint()
    await callback.message.reply_text(
        f"💵 <b>{sc('Enter top-up amount')}</b>\nPlease type the amount in ₹:" + (f"\n\n{hint}" if hint else ""),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"❌ {sc('Cancel')}", callback_data="cancel_payment_process")]])
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
        return await message.reply_text(f"❌ <b>{sc('Invalid amount')}</b>\nPlease send a whole number such as 100.")

    price = float(amount_text)
    del WALLET_TOPUP_WAITING[user_id]

    ACTIVE_PAYMENTS[user_id] = {"title": "WalletTopup", "price": price, "timestamp": time.time(), "type": "WALLET"}

    bonus = await bonus_amount(price)
    bonus_line = f"🎁 <b>{sc('Bonus')}:</b> +₹{bonus:g}  (you get ₹{price + bonus:g} in total)\n" if bonus else ""

    mediator_caption = (
        f"💳 <b><u>{sc('Select payment method')}</u></b>\n\n"
        f"👛 <b>{sc('Wallet top-up')}:</b> ₹{price:g}\n"
        f"{bonus_line}\n"
        f"<i>Please choose how you would like to complete your payment:</i>"
    )

    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⚡ {sc('Auto UPI (instant)')}", style=enums.ButtonStyle.PRIMARY, callback_data=f"payqr:W:{price:g}")],
        [InlineKeyboardButton(f"📲 {sc('Manual (screenshot)')}", callback_data=f"paymanual:W:{price:g}")],
        [InlineKeyboardButton(f"💬 {sc('Contact owner')}", url="https://t.me/hdfilm0900_bot")],
        [InlineKeyboardButton(f"❌ {sc('Cancel')}", style=enums.ButtonStyle.DANGER, callback_data="cancel_payment_process")]
    ])

    await message.reply_photo(photo=GUIDE_IMAGE_URL, caption=mediator_caption, reply_markup=btn)


# ---------------- MANUAL SCREENSHOT PAYMENT ----------------

@Client.on_callback_query(filters.regex(r"^(sent_|paymanual:)"))
async def ask_screenshot(client, callback):
    try:
        kind, story, price, story_title, ref = await _resolve_payment_target(callback.data, "sent_", "paymanual:")
    except Exception:
        return await callback.answer("Could not read the payment data.", show_alert=True)

    if kind == "STORY" and not story:
        return await callback.answer("This story was not found or has been removed.", show_alert=True)
    if price <= 0:
        return await callback.answer("Invalid amount.", show_alert=True)

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
        f"📲 <b><u>{sc('Manual UPI payment')}</u></b>\n\n"
        f"📌 <b>{sc('Item')}:</b> {story_title}\n"
        f"💰 <b>{sc('Amount')}:</b> ₹{price:g}\n\n"
        f"👇 <b>Pay to this UPI ID:</b>\n"
        f"<code>{upi_id}</code>\n"
        f"<i>(Tap the UPI ID to copy it)</i>\n\n"
        f"📸 <b>After paying, send your payment screenshot in this chat.</b>\n"
        f"💡 For faster approval, write the 12-digit <b>UTR / transaction ID</b> in the photo caption."
    )

    await callback.message.reply_text(
        text=manual_text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"❌ {sc('Cancel')}", callback_data="cancel_payment_process")]])
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

    # Optional UTR from the caption. A UTR that was already approved once can never be used again.
    utr_match = UTR_RE.search(message.caption or "")
    utr = utr_match.group(1) if utr_match else None
    if utr and await utr_exists(utr):
        return await message.reply_text(
            f"⚠️ <b>{sc('This UTR was already used')}</b>\n"
            "That transaction ID has already been approved for an earlier payment. "
            "Please send the screenshot and UTR of your new payment."
        )

    admin_text = (
        f"🚨 <b>{sc('Manual payment request')}</b>\n\n"
        f"👤 <b>User:</b> {user.first_name} (@{user.username if user.username else 'N/A'})\n"
        f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
        f"📌 <b>Item / type:</b> {title} ({pay_type})\n"
        f"💰 <b>Amount:</b> ₹{price:g}\n"
        f"🔢 <b>UTR:</b> {utr if utr else 'not provided'}"
    )

    if pay_type == "WALLET":
        ref_part = f"W:{price:g}"
    else:
        ref_part = f"S:{data.get('story_id') or _clean(title).replace(' ', '_')[:40]}"

    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ {sc('Approve')}", callback_data=f"app:{user.id}:{ref_part}"),
         InlineKeyboardButton(f"❌ {sc('Reject')}", callback_data=f"rej:{user.id}:{ref_part}")]
    ])

    await client.send_photo(chat_id=ADMIN_ID, photo=message.photo.file_id, caption=admin_text, reply_markup=btn)
    await message.reply_text(
        f"✅ <b>{sc('Screenshot received')}</b>\nThe admin will review it and approve it shortly."
    )
    ACTIVE_PAYMENTS.pop(user_id, None)


# ---------------- ADMIN APPROVE / REJECT ----------------

def _already_handled(callback) -> bool:
    caption = callback.message.caption or ""
    return ("APPROVED BY ADMIN" in caption) or ("REJECTED BY ADMIN" in caption)


@Client.on_callback_query(filters.regex(r"^app[_:]") & filters.user(ADMIN_ID))
async def approve_order(client, callback):
    # If the admin taps twice, the wallet must not be credited twice
    if _already_handled(callback):
        return await callback.answer("This request has already been processed.", show_alert=True)

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
            # old format: app_<uid>_<price>_<type>_<title>
            raw_data = data[4:]
            user_id_str, price_str, pay_type, clean_title = raw_data.split("_", 3)
            user_id = int(user_id_str)
            price = float(price_str)
            is_wallet = (clean_title == "WalletTopup" or pay_type == "WALLET")
            if not is_wallet:
                story = await get_story_by_key(clean_title)
    except Exception as e:
        print(f"Approval parse error: {e}")
        return await callback.answer("Could not read the approval data.", show_alert=True)

    # UTR duplicate guard: the same transaction ID can be approved only once
    utr_match = re.search(r"UTR:\s*(\d{12})", callback.message.caption or "")
    if utr_match:
        if not await claim_utr(utr_match.group(1), user_id):
            return await callback.answer(
                "This UTR was already approved before. Please reject this request.", show_alert=True
            )

    # --- 1. MANUAL WALLET APPROVAL ---
    if is_wallet:
        bonus = await bonus_amount(price)
        new_balance = await add_wallet_balance(user_id, price + bonus)
        bonus_line = f"\n🎁 Bonus: +₹{bonus:g}" if bonus else ""
        try:
            await client.send_message(
                chat_id=user_id,
                text=f"🎉 <b>{sc('Wallet top-up approved')}</b>\n💰 Added: ₹{price:g}{bonus_line}\n👛 Balance: ₹{new_balance}"
            )
        except Exception as e:
            print(f"Approve: could not message the user: {e}")
        await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n✅ <b>APPROVED BY ADMIN</b>")
        await callback.answer("Wallet top-up approved.", show_alert=True)

        await send_log_to_channel(
            client,
            f"🛠️ <b>[MANUAL APPROVED] {sc('Wallet top-up')}</b>\n\n"
            f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
            f"💰 <b>Amount added:</b> ₹{price:g}" + (f" (+₹{bonus:g} bonus)" if bonus else "") + "\n"
            f"👛 <b>New balance:</b> ₹{new_balance}\n"
            f"👮 <b>Approved by:</b> Admin"
        )
        return

    # --- 2. MANUAL STORY APPROVAL ---
    if not story:
        return await callback.answer("The story was not found in the database (deleted?). Not approved.", show_alert=True)

    clean_title_full = _clean(story['title'])
    story_id = story.get("story_id")
    link = delivery_link(story_id) if story_id else None

    await add_user_purchase(user_id, clean_title_full, story_id=story_id)
    access_btn = InlineKeyboardMarkup([[InlineKeyboardButton(f"📂 {sc('Get files')}", style=enums.ButtonStyle.PRIMARY, url=link)]]) if link else None

    try:
        await client.send_message(
            chat_id=user_id,
            text=f"🎉 <b>{sc('Your payment has been approved')}</b>\n📖 Story: {clean_title_full}",
            reply_markup=access_btn,
            protect_content=False
        )
    except Exception as e:
        print(f"Approve: could not message the user: {e}")
    await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n✅ <b>APPROVED BY ADMIN</b>")
    await callback.answer("Approved.", show_alert=True)

    await send_log_to_channel(
        client,
        f"🛠️ <b>[MANUAL APPROVED] {sc('Story bought')}</b>\n\n"
        f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
        f"📖 <b>Story:</b> {clean_title_full}\n"
        f"💰 <b>Amount:</b> ₹{price:g}\n"
        f"👮 <b>Approved by:</b> Admin"
    )


@Client.on_callback_query(filters.regex(r"^rej[_:]") & filters.user(ADMIN_ID))
async def reject_order(client, callback):
    if _already_handled(callback):
        return await callback.answer("This request has already been processed.", show_alert=True)

    data = callback.data
    try:
        if data.startswith("rej:"):
            _, uid_str, k, ref = data.split(":", 3)
            user_id = int(uid_str)
            if k == "W":
                title = f"Wallet top-up ₹{ref}"
            else:
                story = await get_story_by_key(ref)
                title = _clean(story["title"]) if story else ref
        else:
            raw_data = data[4:]
            user_id_str, clean_title = raw_data.split("_", 1)
            user_id = int(user_id_str)
            title = clean_title.replace("_", " ")
    except Exception:
        return await callback.answer("Could not read the reject data.", show_alert=True)

    try:
        await client.send_message(chat_id=user_id, text=f"❌ <b>{sc('Your payment was rejected')}</b>\nItem: {title}")
    except Exception as e:
        print(f"Reject: could not message the user: {e}")
    await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n❌ <b>REJECTED BY ADMIN</b>")
    await callback.answer("Rejected.", show_alert=True)

    await send_log_to_channel(
        client,
        f"❌ <b>[MANUAL REJECTED] {sc('Payment declined')}</b>\n\n"
        f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
        f"📌 <b>Item:</b> {title}\n"
        f"👮 <b>Rejected by:</b> Admin"
    )
