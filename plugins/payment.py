import re
import urllib.parse
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from config import UPI_ID, ADMIN_ID
from database.db import get_story_by_title

# Stores pending orders: { user_id: {"title": story_title, "price": price} }
PENDING_ORDERS = {}

# 1. View Story Handler
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

# 2. Generate FamPay QR Code (Fixed Title & Price Parsing)
@Client.on_callback_query(filters.regex("^buy_"))
async def generate_qr(client, callback):
    try:
        raw_data = callback.data[4:] # Remove 'buy_'
        clean_title, price = raw_data.rsplit("_", 1) # Split from last underscore safely
        story_title = clean_title.replace("_", " ")
    except Exception:
        return await callback.answer("❌ ᴇʀʀᴏʀ ᴘᴀʀsɪɴɢ ᴘᴀʏᴍᴇɴᴛ ᴅᴀᴛᴀ!", show_alert=True)
    
    upi_link = f"upi://pay?pa={UPI_ID}&pn=StorySeller&am={price}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_link)}"
    
    caption = (
        f"💳 <b>ᴏʀᴅᴇʀ ᴄʜᴇᴄᴋᴏᴜᴛ:</b> {story_title}\n"
        f"💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{price}\n\n"
        f"📌 <b>ғᴀᴍᴘᴀʏ ᴜᴘɪ ɪᴅ:</b> <code>{UPI_ID}</code>\n\n"
        f"👇 ᴀғᴛᴇʀ ᴍᴀᴋɪɴɢ ᴛʜᴇ ᴘᴀʏᴍᴇɴᴛ, ᴄʟɪᴄᴋ ᴏɴ <b>ᴄᴏɴғɪʀᴍ ᴘᴀʏᴍᴇɴᴛ</b> ʙᴇʟᴏᴡ."
    )
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("✅ ᴄᴏɴғɪʀᴍ ᴘᴀʏᴍᴇɴᴛ", callback_data=f"sent_{clean_title}_{price}")]])
    await callback.message.reply_photo(photo=qr_url, caption=caption, reply_markup=btn)
    await callback.answer()

# 3. User Registers Pending Order
@Client.on_callback_query(filters.regex("^sent_"))
async def register_pending_payment(client, callback):
    try:
        raw_data = callback.data[5:] # Remove 'sent_'
        clean_title, price = raw_data.rsplit("_", 1)
        story_title = clean_title.replace("_", " ")
    except Exception:
        return await callback.answer("❌ ᴇʀʀᴏʀ ᴘᴀʀsɪɴɢ ᴅᴀᴛᴀ!", show_alert=True)
        
    user_id = callback.from_user.id
    PENDING_ORDERS[user_id] = {"title": story_title, "price": price}
    
    await callback.message.reply_text(
        "⏳ <b>ᴠᴇʀɪғʏɪɴɢ ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ...</b>\n\n"
        "ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ A ғᴇᴡ sᴇᴄᴏɴᴅs. ᴏɴᴄᴇ ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ɴᴏᴛɪғɪᴄᴀᴛɪᴏɴ ɪs ʀᴇᴄᴇɪᴠᴇᴅ, "
        "ʏᴏᴜʀ ᴏʀᴅᴇʀ ᴡɪʟʟ ʙᴇ ᴀᴜᴛᴏ-ᴀᴘᴘʀᴏᴠᴇᴅ ɪɴsᴛᴀɴᴛʟʏ!"
    )
    await callback.answer()

# 4. MacroDroid Notification Alert Handler (Auto-Approve)
@Client.on_message(filters.command("fampay_alert") & filters.user(ADMIN_ID))
async def handle_fampay_notification(client, message):
    notification_text = message.text
    
    # Extract Amount from FamApp Notification (e.g. ₹1.0 or ₹1)
    amount_match = re.search(r"₹\s*([\d\.]+)", notification_text)
    if not amount_match:
        return
        
    received_amount = float(amount_match.group(1))
    
    matched_user_id = None
    matched_story_title = None
    
    # Match amount with pending orders
    for uid, order in list(PENDING_ORDERS.items()):
        if float(order['price']) == received_amount:
            matched_user_id = uid
            matched_story_title = order['title']
            break

    # Send instant content delivery
    if matched_user_id and matched_story_title:
        story = await get_story_by_title(matched_story_title)
        if story:
            access_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 ᴀᴄᴄᴇss sᴛᴏʀʏ", url=story['link'])]])
            
            try:
                await client.send_message(
                    chat_id=matched_user_id,
                    text=(
                        f"🎉 <b>ᴘᴀʏᴍᴇɴᴛ ᴀᴜᴛᴏ-ᴠᴇʀɪғɪᴇᴅ!</b>\n\n"
                        f"📖 <b>sᴛᴏʀʏ:</b> {matched_story_title}\n\n"
                        f"ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴀᴄᴄᴇss ʏᴏᴜʀ ᴄᴏɴᴛᴇɴᴛ:"
                    ),
                    reply_markup=access_btn,
                    protect_content=True
                )
                del PENDING_ORDERS[matched_user_id]
                await message.reply_text(f"✅ Auto-Approved Order for User ID: {matched_user_id} (₹{received_amount})")
            except Exception as e:
                await message.reply_text(f"❌ Error delivering story link: {e}")
