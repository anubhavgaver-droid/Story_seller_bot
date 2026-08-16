import urllib.parse
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from config import UPI_ID, ADMIN_ID
from database.db import get_story_by_title

# Payment Screenshot Waiting State
PAYMENT_WAITING = {}

@Client.on_callback_query(filters.regex("^view_"))
async def view_story(client, callback):
    title = callback.data.split("view_")[1]
    story = await get_story_by_title(title)
    if not story:
        return await callback.answer("❌ sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ!", show_alert=True)
        
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("💳 ʙᴜʏ ɴᴏᴡ", callback_data=f"buy_{story['title']}_{story['price']}")]])
    await callback.message.reply_photo(
        photo=story.get('photo', 'https://picsum.photos/400/200'),
        caption=f"📖 <b>ᴛɪᴛʟᴇ:</b> {story['title']}\n💰 <b>ᴘʀɪᴄᴇ:</b> ₹{story['price']}\n📝 <b>ᴅᴇsᴄ:</b> {story['desc']}",
        reply_markup=btn
    )
    await callback.answer()

@Client.on_callback_query(filters.regex("^buy_"))
async def generate_qr(client, callback):
    data_parts = callback.data.split("_")
    title = data_parts[1]
    price = data_parts[2]
    
    upi_link = f"upi://pay?pa={UPI_ID}&pn=StorySeller&am={price}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_link)}"
    
    caption = (
        f"💳 <b>ᴏʀᴅᴇʀ ᴄʜᴇᴄᴋᴏᴜᴛ:</b> {title}\n"
        f"💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{price}\n\n"
        f"📌 <b>ᴜᴘɪ ɪᴅ:</b> <code>{UPI_ID}</code>\n\n"
        f"👇 ᴀғᴛᴇʀ ᴍᴀᴋɪɴɢ ᴛʜᴇ ᴘᴀʏᴍᴇɴᴛ, ᴄʟɪᴄᴋ ᴏɴ <b>ᴄᴏɴғɪʀᴍ ᴘᴀʏᴍᴇɴᴛ</b> ʙᴇʟᴏᴡ."
    )
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("✅ ᴄᴏɴғɪʀᴍ ᴘᴀʏᴍᴇɴᴛ", callback_data=f"sent_{title}_{price}")]])
    await callback.message.reply_photo(photo=qr_url, caption=caption, reply_markup=btn)
    await callback.answer()

# 1. Ask User for Screenshot
@Client.on_callback_query(filters.regex("^sent_"))
async def ask_screenshot(client, callback):
    _, title, price = callback.data.split("_")
    user_id = callback.from_user.id
    
    PAYMENT_WAITING[user_id] = {"title": title, "price": price}
    
    await callback.message.reply_text(
        "📸 <b>ᴘʟᴇᴀsᴇ sᴇɴᴅ Yᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ sᴄʀᴇᴇɴsʜᴏᴛ:</b>\n\n"
        "sᴇɴᴅ Yᴏᴜʀ sᴄʀᴇᴇɴsʜᴏᴛ ᴀs ᴀ ᴘʜᴏᴛᴏ ɪɴ ᴛʜɪs ᴄʜᴀᴛ.",
        reply_markup=ForceReply(True)
    )
    await callback.answer()

# 2. Capture Screenshot Photo & Send to Admin
@Client.on_message(filters.private & filters.photo, group=2)
async def receive_screenshot(client, message):
    user_id = message.from_user.id
    
    if user_id not in PAYMENT_WAITING:
        return
        
    data = PAYMENT_WAITING[user_id]
    title = data['title']
    price = data['price']
    user = message.from_user
    
    admin_text = (
        f"🚨 <b>ɴᴇᴡ ᴘᴀʏᴍᴇɴᴛ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ʀᴇǫᴜᴇsᴛ!</b>\n\n"
        f"👤 <b>ᴜsᴇʀ:</b> {user.first_name} (@{user.username if user.username else 'N/A'})\n"
        f"🆔 <b>ᴜsᴇʀ ɪᴅ:</b> <code>{user.id}</code>\n"
        f"📖 <b>sᴛᴏʀʏ:</b> {title}\n"
        f"💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{price}"
    )
    
    clean_title = title.replace(" ", "_")
    btn = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ ᴀᴘᴘʀᴏᴠᴇ", callback_data=f"app_{user.id}_{clean_title}"),
            InlineKeyboardButton("❌ ʀᴇᴊᴇᴄᴛ", callback_data=f"rej_{user.id}_{clean_title}")
        ]
    ])
    
    await client.send_photo(
        chat_id=ADMIN_ID,
        photo=message.photo.file_id,
        caption=admin_text,
        reply_markup=btn
    )
    
    await message.reply_text("✅ <b>sᴄʀᴇᴇɴsʜᴏᴛ ʀᴇᴄᴇɪᴠᴇᴅ!</b>\nʏᴏᴜʀ ᴀᴄᴄᴇss ʟɪɴᴋ ᴡɪʟʟ ʙᴇ sᴇɴᴛ ᴀғᴛᴇʀ ᴀᴅᴍɪɴ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ.")
    del PAYMENT_WAITING[user_id]

# 3. Approve Payment Handler (Inline Button Link + Copy/Forward Restricted)
@Client.on_callback_query(filters.regex("^app_") & filters.user(ADMIN_ID))
async def approve_order(client, callback):
    data = callback.data.split("_")
    user_id = int(data[1])
    title = "_".join(data[2:]).replace("_", " ")
    
    story = await get_story_by_title(title)
    if not story:
        return await callback.answer("❌ sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ ɪɴ ᴅᴀᴛᴀʙᴀsᴇ!", show_alert=True)
        
    access_btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 ᴀᴄᴄᴇss sᴛᴏʀʏ", url=story['link'])]
    ])
    
    try:
        # protect_content=True makes the message non-forwardable & non-copyable
        await client.send_message(
            chat_id=user_id,
            text=(
                f"🎉 <b>ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ʜᴀs ʙᴇᴇɴ ᴀᴘᴘʀᴏᴠᴇᴅ!</b>\n\n"
                f"📖 <b>sᴛᴏʀʏ:</b> {title}\n\n"
                f"ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴀᴄᴄᴇss ʏᴏᴜʀ ᴄᴏɴᴛᴇɴᴛ:"
            ),
            reply_markup=access_btn,
            protect_content=True
        )
        await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n✅ <b>ᴀᴘᴘʀᴏᴠᴇᴅ ʙʏ ᴀᴅᴍɪɴ</b>")
        await callback.answer("Approved Successfully!", show_alert=True)
    except Exception as e:
        await callback.answer(f"Error sending message to user: {e}", show_alert=True)

# 4. Reject Payment Handler
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
                f"📖 <b>sᴛᴏʀʏ:</b> {title}\n\n"
                f"ɪғ ʏᴏᴜ ʙᴇʟɪᴇᴠᴇ ᴛʜɪs ɪs ᴀ ᴍɪsᴛᴀᴋᴇ, ᴘʟᴇᴀsᴇ ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ."
            )
        )
        await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n❌ <b>ʀᴇᴊᴇᴄᴛᴇᴅ ʙʏ ᴀᴅᴍɪɴ</b>")
        await callback.answer("Payment Rejected!", show_alert=True)
    except Exception as e:
        await callback.answer(f"Error sending rejection to user: {e}", show_alert=True)
