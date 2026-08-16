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
        return await callback.answer("❌ स्टोरी नहीं मिली!", show_alert=True)
        
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("💳 Buy Now", callback_data=f"buy_{story['title']}_{story['price']}")]])
    await callback.message.reply_photo(
        photo=story.get('photo', 'https://picsum.photos/400/200'),
        caption=f"📖 <b>Title:</b> {story['title']}\n💰 <b>Price:</b> ₹{story['price']}\n📝 <b>Desc:</b> {story['desc']}",
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
        f"<b>💳 Order Checkout:</b> {title}\n"
        f"<b>Amount:</b> ₹{price}\n\n"
        f"<b>UPI ID:</b> <code>{UPI_ID}</code>\n\n"
        f"👇 पेमेंट करने के बाद नीचे <b>Confirm Payment</b> बटन दबाएं।"
    )
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm Payment", callback_data=f"sent_{title}_{price}")]])
    await callback.message.reply_photo(photo=qr_url, caption=caption, reply_markup=btn)
    await callback.answer()

# 1. Ask User for Screenshot (State Active)
@Client.on_callback_query(filters.regex("^sent_"))
async def ask_screenshot(client, callback):
    _, title, price = callback.data.split("_")
    user_id = callback.from_user.id
    
    # User ko waiting state me dalein
    PAYMENT_WAITING[user_id] = {"title": title, "price": price}
    
    await callback.message.reply_text(
        "📸 <b>कृपया पेमेंट का Screenshot भेजें:</b>\n\n"
        "अपना Screenshot इसी चैट में फोटो के रूप में सेंड करें।",
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
        f"🚨 <b>New Payment Verification Request!</b>\n\n"
        f"👤 <b>User:</b> {user.first_name} (@{user.username if user.username else 'N/A'})\n"
        f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
        f"📖 <b>Story:</b> {title}\n"
        f"💰 <b>Amount:</b> ₹{price}"
    )
    
    # Safe callback_data format for Approve / Reject
    # Format: app_USERID_STORYTITLE
    clean_title = title.replace(" ", "_")
    btn = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"app_{user.id}_{clean_title}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user.id}_{clean_title}")
        ]
    ])
    
    # Send Screenshot Photo to Admin
    await client.send_photo(
        chat_id=ADMIN_ID,
        photo=message.photo.file_id,
        caption=admin_text,
        reply_markup=btn
    )
    
    await message.reply_text("✅ आपका Screenshot प्राप्त हो गया है! एडमिन वेरिफिकेशन के बाद आपको एक्सेस लिंक भेज दिया जाएगा।")
    del PAYMENT_WAITING[user_id]

# 3. Approve Payment Handler
@Client.on_callback_query(filters.regex("^app_") & filters.user(ADMIN_ID))
async def approve_order(client, callback):
    data = callback.data.split("_")
    user_id = int(data[1])
    title = "_".join(data[2:]).replace("_", " ")
    
    story = await get_story_by_title(title)
    if not story:
        return await callback.answer("❌ स्टोरी डेटाबेस में नहीं मिली!", show_alert=True)
        
    try:
        await client.send_message(
            chat_id=user_id,
            text=f"🎉 <b>आपका पेमेंट स्वीकार कर लिया गया है!</b>\n\n📖 <b>Story:</b> {title}\n🔗 <b>Access Link:</b> {story['link']}"
        )
        await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n✅ <b>APPROVED BY ADMIN</b>")
        await callback.answer("Approved Successfully!", show_alert=True)
    except Exception as e:
        await callback.answer(f"Error sending message to user: {e}", show_alert=True)

# 4. Reject Payment Handler (FIXED)
@Client.on_callback_query(filters.regex("^rej_") & filters.user(ADMIN_ID))
async def reject_order(client, callback):
    data = callback.data.split("_")
    user_id = int(data[1])
    title = "_".join(data[2:]).replace("_", " ")
    
    try:
        await client.send_message(
            chat_id=user_id,
            text=f"❌ <b>आपका पेमेंट अमान्य (Reject) कर दिया गया है!</b>\n\n📖 <b>Story:</b> {title}\n\nयदि आपको लगता है कि यह गलती से हुआ है, तो हेल्प/सपोर्ट पर संपर्क करें।"
        )
        await callback.message.edit_caption(caption=f"{callback.message.caption.html}\n\n❌ <b>REJECTED BY ADMIN</b>")
        await callback.answer("Payment Rejected!", show_alert=True)
    except Exception as e:
        await callback.answer(f"Error sending rejection to user: {e}", show_alert=True)
