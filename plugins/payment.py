import urllib.parse
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from config import UPI_ID, ADMIN_ID
from database.db import get_story_by_title, add_user_purchase, add_wallet_balance

# Waiting States
PAYMENT_WAITING = {}
WALLET_TOPUP_WAITING = {}

# 1. View Story
@Client.on_callback_query(filters.regex("^view_"))
async def view_story(client, callback):
    title = callback.data.split("view_")[1].replace("_", " ")
    story = await get_story_by_title(title)
    if not story:
        return await callback.answer("❌ sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ!", show_alert=True)
        
    clean_title = story['title'].replace(" ", "_")
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("💳 ʙᴜʏ ɴᴏᴡ", callback_data=f"buy_{clean_title}_{story['price']}")]])
    await callback.message.reply_photo(
        photo=story.get('photo', 'https://picsum.photos/400/200'),
        caption=f"📖 <b>ᴛɪᴛʟᴇ:</b> {story['title']}\n💰 <b>ᴘʀɪᴄᴇ:</b> ₹{story['price']}\n📝 <b>ᴅᴇsᴄ:</b> {story['desc']}",
        reply_markup=btn
    )
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
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("✅ ᴄᴏɴғɪʀᴍ ᴘᴀʏᴍᴇɴᴛ", callback_data=f"sent_{clean_title}_{price}")]])
    await callback.message.reply_photo(photo=qr_url, caption=caption, reply_markup=btn)
    await callback.answer()

# ---------------- WALLET TOPUP FLOW ----------------

# 3. Topup Callback Handler -> Asks Amount
@Client.on_callback_query(filters.regex("^add_wallet_funds$"))
async def start_wallet_topup(client, callback):
    user_id = callback.from_user.id
    WALLET_TOPUP_WAITING[user_id] = True
    
    await callback.message.reply_text(
        "💵 <b>ᴇɴᴛᴇʀ ᴛᴏᴘ-ᴜᴘ ᴀᴍᴏᴜɴᴛ:</b>\n\n"
        "ᴘʟᴇᴀsᴇ ᴛʏᴘᴇ ᴛʜᴇ ᴀᴍᴏᴜɴᴛ (ɪɴ ₹) ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴀᴅᴅ ᴛᴏ ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ:",
        reply_markup=ForceReply(selective=True, placeholder="ᴇ.ɢ. 100")
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
        return await message.reply_text("❌ <b> Invalid Amount! Please enter numbers only (e.g. 50, 100, 200).</b>")
    
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
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("✅ ᴄᴏɴғɪʀᴍ ᴘᴀʏᴍᴇɴᴛ", callback_data=f"sent_WalletTopup_{price}")]])
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
    
    await callback.message.reply_text(
        "📸 <b>ᴘʟᴇᴀsᴇ sᴇɴᴅ ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ sᴄʀᴇᴇɴsʜᴏᴛ:</b>\n\n"
        "sᴇɴᴅ ʏᴏᴜʀ sᴄʀᴇᴇɴsʜᴏᴛ ᴀs ᴀ ᴘʜᴏᴛᴏ ɪɴ ᴛʜɪs ᴄʜᴀᴛ."
    )
    await callback.answer()

# 6. Capture Screenshot Photo & Send to Admin
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
    
    await message.reply_text("✅ <b>sᴄʀᴇᴇɴsʜᴏᴛ ʀᴇᴄᴇɪᴠᴇᴅ!</b>\nʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ɪs ᴜɴᴅᴇʀ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ʙʏ ᴀᴅᴍɪɴ.")
    del PAYMENT_WAITING[user_id]

# 7. Approve Payment Handler (Auto Detects Wallet vs Story Purchase)
@Client.on_callback_query(filters.regex("^app_") & filters.user(ADMIN_ID))
async def approve_order(client, callback):
    data = callback.data.split("_")
    user_id = int(data[1])
    price = float(data[-1])
    title = "_".join(data[2:-1]).replace("_", " ")
    
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
            return await callback.answer("Wallet Topup Approved & Balance Added!", show_alert=True)
        except Exception as e:
            return await callback.answer(f"Error notifying user: {e}", show_alert=True)

    # CASE 2: DIRECT STORY PURCHASE APPROVAL
    story = await get_story_by_title(title)
    if not story:
        return await callback.answer("❌ sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ ɪɴ ᴅᴀᴛᴀʙᴀsᴇ!", show_alert=True)
        
    await add_user_purchase(user_id, story['title'])

    access_btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 ᴀᴄᴄᴇss sᴛᴏʀʏ", url=story['link'])]
    ])
    
    try:
        await client.send_message(
            chat_id=user_id,
            text=(
                f"🎉 <b>ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ʜᴀs ʙᴇᴇɴ ᴀᴘᴘʀᴏᴠᴇᴅ!</b>\n\n"
                f"📖 <b>sᴛᴏʀʏ:</b> {story['title']}\n\n"
                f"ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴀᴄᴄᴇss ʏᴏᴜʀ ᴄᴏɴᴛᴇɴᴛ:"
            ),
            reply_markup=access_btn,
            protect_content=True
        )
        await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n✅ <b>ᴀᴘᴘʀᴏᴠᴇᴅ ʙʏ ᴀᴅᴍɪɴ</b>")
        await callback.answer("Approved & Saved to DB Successfully!", show_alert=True)
    except Exception as e:
        await callback.answer(f"Error sending message to user: {e}", show_alert=True)

# 8. Reject Payment Handler
@Client.on_callback_query(filters.regex("^rej_") & filters.user(ADMIN_ID))
async def reject_order(client, callback):
    data = callback.data.split("_")
    user_id = int(data[1])
    title = "_".join(data[2:]).replace("_", " ")
    
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
        await callback.answer("Payment Rejected!", show_alert=True)
    except Exception as e:
        await callback.answer(f"Error sending rejection to user: {e}", show_alert=True)
