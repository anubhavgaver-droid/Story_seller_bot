import urllib.parse
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from config import UPI_ID, ADMIN_ID, BOT_USERNAME
from database.db import get_story_by_title, add_user_purchase, add_wallet_balance
from strings import get_text  # Language translation system engine

# Waiting States
PAYMENT_WAITING = {}
WALLET_TOPUP_WAITING = {}

# ------------------ 1. View Story Handler ------------------
@Client.on_callback_query(filters.regex("^view_"))
async def view_story(client, callback):
    user_id = callback.from_user.id
    title = callback.data.split("view_")[1].replace("_", " ")
    story = await get_story_by_title(title)
    if not story:
        return await callback.answer(get_text(user_id, "story_not_found"), show_alert=True)
        
    clean_title = story['title'].strip().split("\n")[0]
    encoded_title = clean_title.replace(" ", "_")
    
    buy_btn_txt = get_text(user_id, "btn_direct_pay").format(price=story['price'])
    btn = InlineKeyboardMarkup([[InlineKeyboardButton(buy_btn_txt, callback_data=f"buy_{encoded_title}_{story['price']}")]])
    
    caption_text = get_text(user_id, "story_details_card").format(
        title=clean_title,
        price=story['price'],
        bal="N/A",
        desc=story.get('desc', get_text(user_id, "no_desc"))
    )
    
    await callback.message.reply_photo(
        photo=story.get('photo', 'https://picsum.photos/400/200'),
        caption=caption_text,
        reply_markup=btn
    )
    await callback.answer()

# ------------------ 2. Generate QR Code for Story Purchase ------------------
@Client.on_callback_query(filters.regex("^buy_"))
async def generate_qr(client, callback):
    user_id = callback.from_user.id
    try:
        raw_data = callback.data[4:]  # Remove 'buy_'
        clean_title, price = raw_data.rsplit("_", 1)  # Split from last underscore
        story_title = clean_title.replace("_", " ")
    except Exception:
        return await callback.answer("❌ Error parsing payment data!", show_alert=True)
    
    upi_link = f"upi://pay?pa={UPI_ID}&pn=StorySeller&am={price}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_link)}"
    
    caption = get_text(user_id, "qr_checkout_caption").format(
        title=story_title,
        price=price,
        upi_id=UPI_ID
    )
    
    btn = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, "btn_confirm_payment"), callback_data=f"sent_{clean_title}_{price}")]])
    await callback.message.reply_photo(photo=qr_url, caption=caption, reply_markup=btn)
    await callback.answer()

# ------------------ WALLET TOPUP FLOW ------------------

# ------------------ 3. Topup Callback Handler ------------------
@Client.on_callback_query(filters.regex("^add_wallet_funds$"))
async def start_wallet_topup(client, callback):
    user_id = callback.from_user.id
    WALLET_TOPUP_WAITING[user_id] = True
    
    await callback.message.reply_text(
        get_text(user_id, "enter_topup_amount_prompt"),
        reply_markup=ForceReply(selective=True, placeholder="e.g. 100")
    )
    await callback.answer()

# ------------------ 4. Receive Amount Input & Send Wallet QR Code ------------------
@Client.on_message(filters.private & filters.text & ~filters.command(["start", "cancel"]), group=3)
async def process_wallet_amount(client, message):
    user_id = message.from_user.id
    
    if user_id not in WALLET_TOPUP_WAITING:
        message.continue_propagation()
        return

    amount_text = message.text.strip()
    if not amount_text.isdigit() or float(amount_text) <= 0:
        return await message.reply_text(get_text(user_id, "invalid_amount_msg"))
    
    price = float(amount_text)
    del WALLET_TOPUP_WAITING[user_id]
    
    upi_link = f"upi://pay?pa={UPI_ID}&pn=WalletTopup&am={price}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_link)}"
    
    caption = get_text(user_id, "wallet_topup_qr_caption").format(
        price=price,
        upi_id=UPI_ID
    )
    
    btn = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, "btn_confirm_payment"), callback_data=f"sent_WalletTopup_{price}")]])
    await message.reply_photo(photo=qr_url, caption=caption, reply_markup=btn)

# ------------------ SCREENSHOT & APPROVAL HANDLERS ------------------

# ------------------ 5. Ask User for Screenshot ------------------
@Client.on_callback_query(filters.regex("^sent_"))
async def ask_screenshot(client, callback):
    user_id = callback.from_user.id
    try:
        raw_data = callback.data[5:]  # Remove 'sent_'
        clean_title, price = raw_data.rsplit("_", 1)
        story_title = clean_title.replace("_", " ")
    except Exception:
        return await callback.answer("❌ Error parsing data!", show_alert=True)
        
    PAYMENT_WAITING[user_id] = {"title": story_title, "price": price}
    
    await callback.message.reply_text(get_text(user_id, "send_screenshot_prompt"))
    await callback.answer()

# ------------------ 6. Capture Screenshot Photo & Send to Admin ------------------
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
    
    await client.send_photo(
        chat_id=ADMIN_ID,
        photo=message.photo.file_id,
        caption=admin_text,
        reply_markup=btn
    )
    
    await message.reply_text(get_text(user_id, "screenshot_received_msg"))
    del PAYMENT_WAITING[user_id]

# ------------------ 7. Approve Payment Handler (Admin) ------------------
@Client.on_callback_query(filters.regex("^app_") & filters.user(ADMIN_ID))
async def approve_order(client, callback):
    data = callback.data.split("_")
    target_user_id = int(data[1])
    price = float(data[-1])
    title = "_".join(data[2:-1]).replace("_", " ")
    
    # CASE 1: WALLET TOPUP APPROVAL
    if title == "WalletTopup":
        new_balance = await add_wallet_balance(target_user_id, price)
        try:
            success_msg = get_text(target_user_id, "wallet_approved_user_msg").format(
                price=price,
                bal=new_balance
            )
            await client.send_message(chat_id=target_user_id, text=success_msg)
            await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n✅ <b>WALLETTOPUP APPROVED</b>")
            return await callback.answer("Wallet Topup Approved & Balance Added!", show_alert=True)
        except Exception as e:
            return await callback.answer(f"Error notifying user: {e}", show_alert=True)

    # CASE 2: DIRECT STORY PURCHASE APPROVAL
    story = await get_story_by_title(title)
    if not story:
        return await callback.answer("❌ Story not found in database!", show_alert=True)
    
    clean_title = story['title'].strip().split("\n")[0]
    encoded_title = clean_title.replace(" ", "_")
    delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"

    # Save to Purchases DB
    await add_user_purchase(target_user_id, clean_title, story_link=delivery_link)

    access_btn = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(target_user_id, "btn_get_files_unlocked"), url=delivery_link)]
    ])
    
    try:
        user_text = get_text(target_user_id, "direct_purchase_approved_user_msg").format(title=clean_title)
        await client.send_message(
            chat_id=target_user_id,
            text=user_text,
            reply_markup=access_btn,
            protect_content=True
        )
        await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n✅ <b>APPROVED BY ADMIN</b>")
        await callback.answer("Approved & Saved to DB Successfully!", show_alert=True)
    except Exception as e:
        await callback.answer(f"Error sending message to user: {e}", show_alert=True)

# ------------------ 8. Reject Payment Handler (Admin) ------------------
@Client.on_callback_query(filters.regex("^rej_") & filters.user(ADMIN_ID))
async def reject_order(client, callback):
    data = callback.data.split("_")
    target_user_id = int(data[1])
    title = "_".join(data[2:]).replace("_", " ")
    
    try:
        rejection_msg = get_text(target_user_id, "payment_rejected_user_msg").format(item=title)
        await client.send_message(chat_id=target_user_id, text=rejection_msg)
        await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n❌ <b>REJECTED BY ADMIN</b>")
        await callback.answer("Payment Rejected!", show_alert=True)
    except Exception as e:
        await callback.answer(f"Error sending rejection to user: {e}", show_alert=True)
