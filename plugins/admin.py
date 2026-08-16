from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from config import ADMIN_ID, BOT_USERNAME
from database.db import add_story_db, send_log

ADD_STATE = {}

# 1. Cancel Command (Priority Group 1)
@Client.on_message(filters.command("cancel") & filters.user(ADMIN_ID) & filters.private, group=1)
async def cancel_add(client, message):
    user_id = message.from_user.id
    if user_id in ADD_STATE:
        del ADD_STATE[user_id]
        await message.reply_text("❌ <b>Story Adding Process Cancelled!</b>")
    else:
        await message.reply_text("❓ आपका कोई एक्टिव प्रोसेस नहीं था।")

# 2. Add Story Command (Priority Group 1)
@Client.on_message(filters.command("addstory") & filters.user(ADMIN_ID) & filters.private, group=1)
async def start_add(client, message):
    ADD_STATE[message.from_user.id] = {}
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📻 Pocket FM", callback_data="setcat_pocket_fm")],
        [InlineKeyboardButton("📚 Pratilipi FM", callback_data="setcat_pratilipi_fm")]
    ])
    await message.reply_text("<b>[Step 1/5]</b> स्टोरी की Category चुनें:\n<i>(रद्द करने के लिए /cancel लिखें)</i>", reply_markup=kb)

# 3. Category Selected Callback
@Client.on_callback_query(filters.regex("^setcat_") & filters.user(ADMIN_ID))
async def cat_selected(client, callback):
    ADD_STATE[callback.from_user.id]['category'] = callback.data.split("setcat_")[1]
    ADD_STATE[callback.from_user.id]['step'] = 'TITLE'
    await callback.message.reply_text("<b>[Step 2/5]</b> स्टोरी का Title लिखें:", reply_markup=ForceReply(True))
    await callback.answer()

# 4. Input Wizard Steps (PERMANENT FIX FOR ADMIN /start)
@Client.on_message(filters.private & filters.user(ADMIN_ID) & ~filters.command(["start", "addstory", "cancel"]), group=1)
async def wizard_inputs(client, message):
    user_id = message.from_user.id
    
    # अगर एडमिन किसी प्रोसेस (Wizard Step) में नहीं है, तो मैसेज आगे पास कर दें
    if user_id not in ADD_STATE or 'step' not in ADD_STATE[user_id]:
        message.continue_propagation()
        return
        
    step = ADD_STATE[user_id]['step']
    
    if step == 'TITLE':
        # केवल पहली लाइन को टाइटल के रूप में सेव करें
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
        
        # MongoDB में सेव करें
        await add_story_db(data)
        
        clean_title = data['title'].replace(" ", "_")
        share_link = f"https://t.me/{BOT_USERNAME}?start=story_{clean_title}"
        
        # Log Channel में नोटिफिकेशन भेजें
        log_msg = (
            f"<b>➕ New Story Added!</b>\n\n"
            f"<b>📌 Title:</b> {data['title']}\n"
            f"<b>📂 Category:</b> {data['category']}\n"
            f"<b>💰 Price:</b> ₹{data['price']}\n"
            f"<b>🔗 Destination Link:</b> {data['link']}\n"
            f"<b>🔗 Shareable Link:</b> {share_link}"
        )
        await send_log(client, log_msg)
        
        # Admin को कन्फर्मेशन मैसेज भेजें
        await message.reply_text(
            f"✅ <b>Story Added Successfully!</b>\n\n"
            f"<b>Title:</b> {data['title']}\n"
            f"<b>Price:</b> ₹{data['price']}\n"
            f"<b>Link:</b> {data['link']}\n\n"
            f"🔗 <b>Shareable Link:</b>\n<code>{share_link}</code>"
        )
        del ADD_STATE[user_id]
