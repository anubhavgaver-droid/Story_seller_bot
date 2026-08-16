from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from config import ADMIN_ID, BOT_USERNAME
from database.db import add_story_db, delete_story_db, get_all_stories, send_log

ADD_STATE = {}
DELETE_STATE = {}

# 1. Cancel Command (Cancel both Add & Delete operations)
@Client.on_message(filters.command("cancel") & filters.user(ADMIN_ID) & filters.private, group=1)
async def cancel_action(client, message):
    user_id = message.from_user.id
    if user_id in ADD_STATE or user_id in DELETE_STATE:
        ADD_STATE.pop(user_id, None)
        DELETE_STATE.pop(user_id, None)
        await message.reply_text("❌ <b>प्रोसेस रद्द कर दिया गया!</b>")
    else:
        await message.reply_text("❓ आपका कोई एक्टिव प्रोसेस नहीं था।")

# 2. View All Stories List
@Client.on_message(filters.command("allstories") & filters.user(ADMIN_ID) & filters.private, group=1)
async def list_stories(client, message):
    stories = await get_all_stories()
    if not stories:
        return await message.reply_text("📂 <b>डेटाबेस में कोई स्टोरी मौजूद नहीं है।</b>")
        
    text = "<b>📚 Saved Stories List:</b>\n\n"
    for idx, s in enumerate(stories, start=1):
        text += f"{idx}. <b>{s['title']}</b> | ₹{s['price']} | <i>{s['category']}</i>\n"
    
    await message.reply_text(text)

# 3. Delete Story Command
@Client.on_message(filters.command("deletestory") & filters.user(ADMIN_ID) & filters.private, group=1)
async def start_delete(client, message):
    user_id = message.from_user.id
    DELETE_STATE[user_id] = True
    await message.reply_text(
        "🗑️ <b>Delete Story Wizard:</b>\n\n"
        "जिस स्टोरी को डिलीट करना चाहते हैं, उसका <b>सटीक Title लिखें</b>:\n"
        "<i>(रद्द करने के लिए /cancel लिखें)</i>",
        reply_markup=ForceReply(True)
    )

# 4. Add Story Command
@Client.on_message(filters.command("addstory") & filters.user(ADMIN_ID) & filters.private, group=1)
async def start_add(client, message):
    ADD_STATE[message.from_user.id] = {}
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📻 Pocket FM", callback_data="setcat_pocket_fm")],
        [InlineKeyboardButton("📚 Pratilipi FM", callback_data="setcat_pratilipi_fm")]
    ])
    await message.reply_text("<b>[Step 1/6]</b> स्टोरी की Category चुनें:\n<i>(रद्द करने के लिए /cancel लिखें)</i>", reply_markup=kb)

# 5. Category Selection Callback
@Client.on_callback_query(filters.regex("^setcat_") & filters.user(ADMIN_ID))
async def cat_selected(client, callback):
    ADD_STATE[callback.from_user.id]['category'] = callback.data.split("setcat_")[1]
    ADD_STATE[callback.from_user.id]['step'] = 'TITLE'
    await callback.message.reply_text("<b>[Step 2/6]</b> स्टोरी का Title लिखें:", reply_markup=ForceReply(True))
    await callback.answer()

# 6. Admin Input Wizard (Handles Photos, Text inputs & Deletions)
@Client.on_message(filters.private & filters.user(ADMIN_ID) & ~filters.command(["start", "addstory", "deletestory", "allstories", "cancel"]), group=1)
async def wizard_inputs(client, message):
    user_id = message.from_user.id
    
    # --- Delete Story Process ---
    if user_id in DELETE_STATE:
        title_to_delete = message.text.strip()
        deleted = await delete_story_db(title_to_delete)
        del DELETE_STATE[user_id]
        
        if deleted:
            return await message.reply_text(f"✅ <b>'{title_to_delete}'</b> स्टोरी सफलतापूर्वक डिलीट कर दी गई!")
        else:
            return await message.reply_text(f"❌ <b>'{title_to_delete}'</b> नाम से कोई स्टोरी नहीं मिली।")

    # --- Add Story Process ---
    if user_id not in ADD_STATE or 'step' not in ADD_STATE[user_id]:
        message.continue_propagation()
        return
        
    step = ADD_STATE[user_id]['step']
    
    if step == 'TITLE':
        # केवल पहली लाइन को टाइटल के रूप में सेव करें
        ADD_STATE[user_id]['title'] = message.text.strip().split("\n")[0]
        ADD_STATE[user_id]['step'] = 'PHOTO'
        await message.reply_text("<b>[Step 3/6]</b> स्टोरी की Poster Photo भेजें (या Image URL लिंक दर्ज करें):", reply_markup=ForceReply(True))
        
    elif step == 'PHOTO':
        if message.photo:
            ADD_STATE[user_id]['photo'] = message.photo.file_id
        elif message.text and (message.text.startswith("http://") or message.text.startswith("https://")):
            ADD_STATE[user_id]['photo'] = message.text.strip()
        else:
            return await message.reply_text("❌ कृपया एक फोटो भेजें या वैध Image URL भेजें:")
            
        ADD_STATE[user_id]['step'] = 'PRICE'
        await message.reply_text("<b>[Step 4/6]</b> Price (₹) दर्ज करें:", reply_markup=ForceReply(True))
        
    elif step == 'PRICE':
        if not message.text or not message.text.isdigit():
            return await message.reply_text("❌ Price केवल संख्या में दर्ज करें (जैसे: 99):")
        ADD_STATE[user_id]['price'] = int(message.text)
        ADD_STATE[user_id]['step'] = 'DESC'
        await message.reply_text("<b>[Step 5/6]</b> Description दर्ज करें:", reply_markup=ForceReply(True))
        
    elif step == 'DESC':
        ADD_STATE[user_id]['desc'] = message.text.strip()
        ADD_STATE[user_id]['step'] = 'LINK'
        await message.reply_text("<b>[Step 6/6]</b> अप्रूवल के बाद की Destination Link / Channel Link भेजें:", reply_markup=ForceReply(True))
        
    elif step == 'LINK':
        data = ADD_STATE[user_id]
        data['link'] = message.text.strip()
        
        # MongoDB में डेटाबेस में सेव करें
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
        try:
            await send_log(client, log_msg)
        except Exception:
            pass
        
        # Admin को कन्फर्मेशन मैसेज भेजें
        await message.reply_text(
            f"✅ <b>Story Added Successfully!</b>\n\n"
            f"<b>Title:</b> {data['title']}\n"
            f"<b>Price:</b> ₹{data['price']}\n"
            f"<b>Link:</b> {data['link']}\n\n"
            f"🔗 <b>Shareable Link:</b>\n<code>{share_link}</code>"
        )
        del ADD_STATE[user_id]
