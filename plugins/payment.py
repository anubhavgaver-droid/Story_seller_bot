import urllib.parse
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import UPI_ID, ADMIN_ID
from database.db import get_story_by_title

@Client.on_callback_query(filters.regex("^view_"))
async def view_story(client, callback):
    title = callback.data.split("view_")[1]
    story = await get_story_by_title(title)
    if not story:
        return await callback.answer("❌ स्टोरी नहीं मिली!", show_alert=True)
        
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("💳 Buy Now", callback_data=f"buy_{story['title']}_{story['price']}")]])
    await callback.message.reply_photo(photo=story['photo'], caption=f"📖 <b>Title:</b> {story['title']}\n💰 <b>Price:</b> ₹{story['price']}\n📝 <b>Desc:</b> {story['desc']}", reply_markup=btn)
    await callback.answer()

@Client.on_callback_query(filters.regex("^buy_"))
async def generate_qr(client, callback):
    _, title, price = callback.data.split("_")
    upi_link = f"upi://pay?pa={UPI_ID}&pn=StorySeller&am={price}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_link)}"
    
    caption = f"<b>💳 Order Checkout:</b> {title}\n<b>Amount:</b> ₹{price}\n\n<b>UPI ID:</b> <code>{UPI_ID}</code>\n\n📸 पेमेंट करके Screenshot यहाँ भेजें।"
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm & Send Screenshot", callback_data=f"sent_{title}")]])
    await callback.message.reply_photo(photo=qr_url, caption=caption, reply_markup=btn)
    await callback.answer()

@Client.on_callback_query(filters.regex("^sent_"))
async def notify_admin(client, callback):
    title = callback.data.split("sent_")[1]
    user = callback.from_user
    
    admin_text = f"🚨 <b>New Payment Request!</b>\nUser: {user.first_name} (@{user.username})\nID: <code>{user.id}</code>\nStory: {title}"
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"app_{user.id}_{title}"), InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user.id}")]
    ])
    await client.send_message(chat_id=ADMIN_ID, text=admin_text, reply_markup=btn)
    await callback.message.reply_text("✅ पेमेंट वेरिफिकेशन रिक्वेस्ट एडमिन को भेज दी गई है!")
    await callback.answer()

@Client.on_callback_query(filters.regex("^app_") & filters.user(ADMIN_ID))
async def approve_order(client, callback):
    _, user_id, title = callback.data.split("_")
    story = await get_story_by_title(title)
    
    await client.send_message(
        chat_id=int(user_id),
        text=f"🎉 <b>आपका पेमेंट स्वीकार कर लिया गया है!</b>\n\n📖 <b>Story:</b> {title}\n🔗 <b>Access Link:</b> {story['link']}"
    )
    await callback.message.edit_text(f"✅ User {user_id} Approved for {title}!")
    await callback.answer()
