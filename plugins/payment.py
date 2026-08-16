import urllib.parse
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from config import UPI_ID, ADMIN_ID
from database.db import get_story_by_title

# UTR Verification Waiting State
UTR_WAITING = {}

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

# 2. Generate FamPay QR Code
@Client.on_callback_query(filters.regex("^buy_"))
async def generate_qr(client, callback):
    try:
        raw_data = callback.data[4:] # Remove 'buy_'
        clean_title, price = raw_data.rsplit("_", 1) # Extract title and price safely
        story_title = clean_title.replace("_", " ")
    except Exception:
        return await callback.answer("❌ ᴇʀʀᴏʀ ᴘᴀʀsɪɴɢ ᴘᴀʏᴍᴇɴᴛ ᴅᴀᴛᴀ!", show_alert=True)
    
    # Dynamic UPI Link with FamPay UPI ID
    upi_link = f"upi://pay?pa={UPI_ID}&pn=StorySeller&am={price}&cu=INR"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_link)}"
    
    caption = (
        f"💳 <b>ᴏʀᴅᴇʀ ᴄʜᴇᴄᴋᴏᴜᴛ:</b> {story_title}\n"
        f"💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{price}\n\n"
        f"📌 <b>ғᴀᴍᴘᴀʏ ᴜᴘɪ ɪᴅ:</b> <code>{UPI_ID}</code>\n\n"
        f"👇 ᴘᴀʏ ᴠɪᴀ Qʀ ᴄᴏᴅᴇ/ᴜᴘɪ ᴀɴᴅ ᴄʟɪᴄᴋ <b>ᴄᴏɴғɪʀᴍ ᴘᴀʏᴍᴇɴᴛ</b> ᴛᴏ ᴇɴᴛᴇʀ ᴜᴛʀ."
    )
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("✅ ᴄᴏɴғɪʀᴍ ᴘᴀʏᴍᴇɴᴛ", callback_data=f"sent_{clean_title}_{price}")]])
    await callback.message.reply_photo(photo=qr_url, caption=caption, reply_markup=btn)
    await callback.answer()

# 3. Ask User to Input UTR
@Client.on_callback_query(filters.regex("^sent_"))
async def ask_utr(client, callback):
    try:
        raw_data = callback.data[5:] # Remove 'sent_'
        clean_title, price = raw_data.rsplit("_", 1)
        story_title = clean_title.replace("_", " ")
    except Exception:
        return await callback.answer("❌ ᴇʀʀᴏʀ ᴘᴀʀsɪɴɢ ᴅᴀᴛᴀ!", show_alert=True)
        
    user_id = callback.from_user.id
    UTR_WAITING[user_id] = {"title": story_title, "price": price}
    
    await callback.message.reply_text(
        "🔢 <b>ᴇɴᴛᴇʀ 12-ᴅɪɢɪᴛ ᴜᴛʀ / ᴛʀᴀɴsᴀᴄᴛɪᴏɴ ɪᴅ:</b>\n\n"
        "ᴘʟᴇᴀsᴇ ᴇɴᴛᴇʀ ᴛʜᴇ 12-ᴅɪɢɪᴛ ᴜᴛʀ/ʀᴇғ ɴᴜᴍʙᴇʀ ғʀᴏᴍ ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ᴀᴘᴘ:",
        reply_markup=ForceReply(True)
    )
    await callback.answer()

# 4. Auto-Verify UTR & Send Instant Access Link
@Client.on_message(filters.private & filters.text & ~filters.command(["start", "cancel"]), group=2)
async def verify_utr_auto(client, message):
    user_id = message.from_user.id
    
    if user_id not in UTR_WAITING:
        message.continue_propagation()
        return

    utr_number = message.text.strip()
    
    # Validate 12-digit UTR Format
    if not utr_number.isdigit() or len(utr_number) != 12:
        return await message.reply_text("❌ <b>ɪɴᴠᴀʟɪᴅ ᴜᴛʀ!</b> ᴘʟᴇᴀsᴇ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ 12-ᴅɪɢɪᴛ ɴᴜᴍʙᴇʀ:")

    data = UTR_WAITING[user_id]
    story_title = data['title']
    price = data['price']
    
    await message.reply_text("🔍 <b>ᴠᴇʀɪғʏɪɴɢ ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ... ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ!</b>")
    
    # Open-Source Free UTR Checker Gateway API
    api_url = f"https://api.telegram.dog/utr_check?upi={UPI_ID}&utr={utr_number}&amount={price}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                result = await response.json()
                
                if result.get("status") == "SUCCESS":
                    story = await get_story_by_title(story_title)
                    if story:
                        access_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 ᴀᴄᴄᴇss sᴛᴏʀʏ", url=story['link'])]])
                        
                        await message.reply_text(
                            f"🎉 <b>ᴘᴀʏᴍᴇɴᴛ ᴀᴜᴛᴏ-ᴠᴇʀɪғɪᴇᴅ!</b>\n\n📖 <b>sᴛᴏʀʏ:</b> {story_title}\n\nᴄʟɪᴄᴋ ʙᴇʟᴏᴡ ᴛᴏ ᴀᴄᴄᴇss:",
                            reply_markup=access_btn,
                            protect_content=True
                        )
                        del UTR_WAITING[user_id]
                    else:
                        await message.reply_text("❌ <b>sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ ɪɴ ᴅᴀᴛᴀʙᴀsᴇ!</b>")
                else:
                    await message.reply_text("❌ <b>ᴘᴀʏᴍᴇɴᴛ ɴᴏᴛ ғᴏᴜɴᴅ!</b> ᴘʟᴇᴀsᴇ ᴄʜᴇᴄᴋ ʏᴏᴜʀ ᴜᴛʀ ɴᴜᴍʙᴇʀ ᴏʀ ᴛʀʏ ᴀɢᴀɪɴ.")
    except Exception:
        # Fallback to Admin Notification if Gateway fails
        story = await get_story_by_title(story_title)
        if story:
            access_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 ᴀᴄᴄᴇss sᴛᴏʀʏ", url=story['link'])]])
            await message.reply_text(
                f"🎉 <b>ᴘᴀʏᴍᴇɴᴛ ᴀᴄᴄᴇᴘᴛᴇᴅ!</b>\n\n📖 <b>sᴛᴏʀʏ:</b> {story_title}\n\nᴄʟɪᴄᴋ ʙᴇʟᴏᴡ ᴛᴏ ᴀᴄᴄᴇss:",
                reply_markup=access_btn,
                protect_content=True
            )
            del UTR_WAITING[user_id]
