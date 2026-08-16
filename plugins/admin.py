from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from config import ADMIN_ID, BOT_USERNAME
from database.db import add_story_db

ADD_STATE = {}

@Client.on_message(filters.command("addstory") & filters.user(ADMIN_ID))
async def start_add(client, message):
    ADD_STATE[message.from_user.id] = {}
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📻 Pocket FM", callback_data="setcat_pocket_fm")],
        [InlineKeyboardButton("📚 Pratilipi FM", callback_data="setcat_pratilipi_fm")]
    ])
    await message.reply_text("<b>[Step 1/5]</b> स्टोरी की Category चुनें:", reply_markup=kb)

@Client.on_callback_query(filters.regex("^setcat_") & filters.user(ADMIN_ID))
async def cat_selected(client, callback):
    ADD_STATE[callback.from_user.id]['category'] = callback.data.split("setcat_")[1]
    ADD_STATE[callback.from_user.id]['step'] = 'TITLE'
    await callback.message.reply_text("<b>[Step 2/5]</b> स्टोरी का Title लिखें:", reply_markup=ForceReply(True))
    await callback.answer()

@Client.on_message(filters.private & filters.user(ADMIN_ID))
async def wizard_inputs(client, message):
    user_id = message.from_user.id
    if user_id not in ADD_STATE or 'step' not in ADD_STATE[user_id]:
        return
        
    step = ADD_STATE[user_id]['step']
    
    if step == 'TITLE':
        ADD_STATE[user_id]['title'] = message.text.strip().split("\n")[0]
        ADD_STATE[user_id]['step'] = 'PRICE'
        await message.reply_text("<b>[Step 3/5]</b> Price (₹) दर्ज करें:", reply_markup=ForceReply(True))
        
    elif step == 'PRICE':
        if not message.text.isdigit():
            return await message.reply_text("❌ Price केवल संख्या में दर्ज करें (जैसे: 99):")
        ADD_STATE[user_id]['price'] = int(message.text)
        ADD_STATE[user_id]['step'] = 'DESC'
        await message.reply_text("<b>[Step 4/5]</b> Description दर्ज करें:", reply_markup=ForceReply(True))
        
    elif step == 'DESC':
        ADD_STATE[user_id]['desc'] = message.text.strip()
        ADD_STATE[user_id]['step'] = 'LINK'
        await message.reply_text("<b>[Step 5/5]</b> अप्रूवल के बाद की Destination Link / Channel Link भेजें:", reply_markup=ForceReply(True))
        
    elif step == 'LINK':
        data = ADD_STATE[user_id]
        data['link'] = message.text.strip()
        data['photo'] = "https://picsum.photos/400/200"
        
        await add_story_db(data)
        
        clean_title = data['title'].replace(" ", "_")
        share_link = f"https://t.me/{BOT_USERNAME}?start=story_{clean_title}"
        
        await message.reply_text(
            f"✅ <b>Story Added Successfully!</b>\n\n"
            f"<b>Title:</b> {data['title']}\n"
            f"<b>Price:</b> ₹{data['price']}\n"
            f"<b>Link:</b> {data['link']}\n\n"
            f"🔗 <b>Shareable Link:</b>\n<code>{share_link}</code>"
        )
        del ADD_STATE[user_id]
