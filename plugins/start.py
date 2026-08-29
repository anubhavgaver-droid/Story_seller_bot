import json
from pyrogram import Client, filters, enums
from pyrogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    WebAppInfo
)

# Required Database functions (Aapke database.db file mein wallet queries shamil honi chahiye)
from database.db import (
    get_story_by_title, 
    send_log, 
    is_user_registered, 
    register_user, 
    get_user_purchases, 
    get_user_wallet,
    update_user_wallet,
    add_user_purchase
)
from config import BOT_USERNAME, WEB_APP_URL

# Search State Dictionary
SEARCH_WAITING = {}

# 1. Main Menu Keyboard Layout (Wallet Button Added)
MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ")],
        [KeyboardButton("💼 ᴍʏ ᴡᴀʟʟᴇᴛ", style=enums.ButtonStyle.SUCCESS), KeyboardButton("👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ", style=enums.ButtonStyle.PRIMARY)],
        [KeyboardButton("🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ", style=enums.ButtonStyle.SUCCESS), KeyboardButton("📻 ᴘᴏᴄᴋᴇᴛ ғᴍ", style=enums.ButtonStyle.DANGER)],
        [KeyboardButton("📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ", style=enums.ButtonStyle.DANGER), KeyboardButton("📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ", style=enums.ButtonStyle.PRIMARY)],
        [KeyboardButton("📞 sᴜᴘᴘᴏʀᴛ", style=enums.ButtonStyle.SUCCESS)]
    ],
    resize_keyboard=True
)

# Custom Filter for WebApp Data
async def web_app_filter(_, __, message):
    return bool(message.web_app_data)

filter_webapp = filters.create(web_app_filter)

# ------------------ Mini App Web Data Receiver ------------------
@Client.on_message(filters.service & filter_webapp & filters.private)
async def web_app_data_handler(client, message):
    try:
        data = json.loads(message.web_app_data.data)
        action = data.get("action")
        story_title = data.get("title")
        price = float(data.get("price", 0))
        
        if action == "buy_story":
            story = await get_story_by_title(story_title)
            if not story:
                return await message.reply_text("❌ <b>sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ.</b>")

            clean_title = story_title.replace(" ", "_")
            wallet_bal = await get_user_wallet(message.from_user.id)
            
            # Payment Option Keyboard
            btn = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"💳 ᴅɪʀᴇᴄᴛ ᴘᴀʏ (₹{price})", callback_data=f"directpay_{clean_title}_{price}")],
                [InlineKeyboardButton(f"👛 ᴘᴀʏ ᴠɪᴀ ᴡᴀʟʟᴇᴛ (Bal: ₹{wallet_bal})", callback_data=f"walletpay_{clean_title}_{price}")]
            ])
            
            photo_url = story.get('photo', 'https://picsum.photos/400/200')
            desc = story.get('desc', 'ɴᴏ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴀᴠᴀɪʟᴀʙʟᴇ.')

            caption_text = (
                f"🛒 <b>ᴏʀᴅᴇʀ ɪɴɪᴛɪᴀᴛᴇᴅ ғʀᴏᴍ ᴍɪɴɪ ᴀᴘᴘ</b>\n\n"
                f"📖 <b>ᴛɪᴛʟᴇ:</b> {story_title}\n"
                f"💰 <b>ᴘʀɪᴄᴇ:</b> ₹{price}\n"
                f"👛 <b>ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ:</b> ₹{wallet_bal}\n"
                f"📝 <b>ᴅᴇsᴄ:</b> {desc}\n\n"
                f"👇 <b>Select payment method to complete purchase:</b>"
            )
            
            try:
                await message.reply_photo(photo=photo_url, caption=caption_text, reply_markup=btn)
            except Exception:
                await message.reply_text(caption_text, reply_markup=btn)
    except Exception as e:
        print(f"WebApp Data Error: {e}")

# ------------------ Wallet Payment Callback Handler ------------------
@Client.on_callback_query(filters.regex(r"^walletpay_"))
async def process_wallet_payment(client, callback_query):
    user_id = callback_query.from_user.id
    data_parts = callback_query.data.split("_")
    
    clean_title = data_parts[1]
    price = float(data_parts[2])
    story_title = clean_title.replace("_", " ")

    story = await get_story_by_title(story_title)
    if not story:
        return await callback_query.answer("❌ Story not found!", show_alert=True)

    current_balance = await get_user_wallet(user_id)

    # 1. Balance Check
    if current_balance < price:
        return await callback_query.answer(
            f"❌ Insufficient Balance!\nRequired: ₹{price}\nAvailable: ₹{current_balance}\n\nPlease top-up your wallet.",
            show_alert=True
        )

    # 2. Deduct Balance & Add Purchase
    new_balance = current_balance - price
    await update_user_wallet(user_id, new_balance)
    await add_user_purchase(user_id, story['title'], story.get('link', '#'))

    await callback_query.answer("🎉 Purchase successful! Story unlocked.", show_alert=True)
    
    success_text = (
        f"✅ <b>ᴘᴜʀᴄʜᴀsᴇ sᴜᴄᴄᴇssғᴜʟ!</b>\n\n"
        f"📖 <b>sᴛᴏʀʏ:</b> {story['title']}\n"
        f"💸 <b>ᴅᴇᴅᴜᴄᴛᴇᴅ:</b> ₹{price}\n"
        f"👛 <b>ʀᴇᴍᴀɪɴɪɴɢ ʙᴀʟᴀɴᴄᴇ:</b> ₹{new_balance}\n\n"
        f"👇 Click below to access your story:"
    )
    
    access_btn = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🚀 ᴀᴄᴄᴇss {story['title']}", url=story.get('link', 'https://t.me'))]
    ])
    
    await callback_query.message.edit_text(success_text, reply_markup=access_btn)

# ------------------ Start Handler ------------------
@Client.on_message(filters.command("start") & filters.private, group=-1)
async def start_handler(client, message):
    user = message.from_user
    
    registered = await is_user_registered(user.id)
    if not registered:
        await register_user(user.id, user.first_name, user.username)
        try:
            log_text = (
                f"<b>🆕 ɴᴇᴡ ᴜsᴇʀ ʀᴇɢɪsᴛᴇʀᴇᴅ!</b>\n"
                f"<b>ɴᴀᴍᴇ:</b> {user.first_name}\n"
                f"<b>ᴜsᴇʀ ɪᴅ:</b> <code>{user.id}</code>\n"
                f"<b>ᴜsᴇʀɴᴀᴍᴇ:</b> @{user.username if user.username else 'None'}"
            )
            await send_log(client, log_text)
        except Exception as e:
            print(f"Log Error: {e}")

    args = message.text.split(maxsplit=1)
    
    if len(args) > 1 and args[1].startswith("story_"):
        raw_param = args[1]
        story_title = raw_param.replace("story_", "").replace("_", " ")
        story = await get_story_by_title(story_title)
        
        if story:
            clean_title = story['title'].replace(" ", "_")
            photo_url = story.get('photo', 'https://picsum.photos/400/200')
            desc = story.get('desc', 'ɴᴏ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴀᴠᴀɪʟᴀʙʟᴇ.')
            wallet_bal = await get_user_wallet(user.id)
            
            miniapp_direct_url = f"{WEB_APP_URL}?tgWebAppStartParam={raw_param}"
            
            btn = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🚀 ᴏᴘᴇɴ ᴅɪʀᴇᴄᴛ sᴛᴏʀʏ ᴍɪɴɪ ᴀᴘᴘ", 
                        web_app=WebAppInfo(url=miniapp_direct_url)
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"💳 ᴅɪʀᴇᴄᴛ ʙᴜʏ (₹{story['price']})", 
                        callback_data=f"directpay_{clean_title}_{story['price']}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"👛 ᴘᴀʏ ᴠɪᴀ ᴡᴀʟʟᴇᴛ (Bal: ₹{wallet_bal})", 
                        callback_data=f"walletpay_{clean_title}_{story['price']}"
                    )
                ]
            ])
            
            caption_text = (
                f"📖 <b>ᴛɪᴛʟᴇ:</b> {story['title']}\n"
                f"💰 <b>ᴘʀɪᴄᴇ:</b> ₹{story['price']}\n"
                f"👛 <b>ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ:</b> ₹{wallet_bal}\n"
                f"📝 <b>ᴅᴇsᴄ:</b> {desc}\n\n"
                f"<i>👇 Choose an option below to view or purchase:</i>"
            )
            
            try:
                return await message.reply_photo(photo=photo_url, caption=caption_text, reply_markup=btn)
            except Exception:
                return await message.reply_text(caption_text, reply_markup=btn)
        else:
            return await message.reply_text("❌ <b>ᴛʜɪs sᴛᴏʀʏ ɪs ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ.</b>", reply_markup=MAIN_MENU)

    welcome_text = (
        f"<b>━━━━━━━ 🌟 sᴛᴏʀʏ sᴇʟʟᴇʀ ʙᴏᴛ 🌟 ━━━━━━━</b>\n\n"
        f"ʜᴇʟʟᴏ {user.first_name}! 👋\n\n"
        "ᴜsᴇ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ sᴇᴀʀᴄʜ ᴏʀ ᴘᴜʀᴄʜᴀsᴇ ʏᴏᴜʀ ғᴀᴠᴏʀɪᴛᴇ sᴛᴏʀɪᴇs."
    )
    await message.reply_text(welcome_text, reply_markup=MAIN_MENU)

# ------------------ Wallet System Handlers ------------------

@Client.on_message(filters.regex("^(💼 ᴍʏ ᴡᴀʟʟᴇᴛ|💼 My Wallet)$") & filters.private)
async def wallet_handler(client, message):
    user_id = message.from_user.id
    balance = await get_user_wallet(user_id)
    
    text = (
        f"<b>👛 ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ ᴅᴇᴛᴀɪʟs</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"<b>💳 ᴄᴜʀʀᴇɴᴛ ʙᴀʟᴀɴᴄᴇ:</b> ₹{balance}\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 <i>Use wallet balance for 1-click instant purchases inside Mini App or Bot.</i>"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ᴀᴅᴅ ᴍᴏɴᴇʏ / ᴛᴏᴘ-ᴜᴘ", callback_data="add_wallet_funds")],
        [InlineKeyboardButton("📜 ᴛʀᴀɴsᴀᴄᴛɪᴏɴ ʜɪsᴛᴏʀʏ", callback_data="wallet_history")]
    ])
    
    await message.reply_text(text, reply_markup=kb)

@Client.on_callback_query(filters.regex("^add_wallet_funds$"))
async def add_funds_callback(client, callback_query):
    text = (
        "<b>➕ ᴀᴅᴅ ᴍᴏɴᴇʏ ᴛᴏ ᴡᴀʟʟᴇᴛ</b>\n\n"
        "Contact admin or send payment screenshot to top-up your wallet balance automatically."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ ғᴏʀ ᴛᴏᴘᴜᴘ", url="https://t.me/kaluu_help_bot")]
    ])
    await callback_query.message.edit_text(text, reply_markup=kb)

# ------------------ Dynamic Button Handlers ------------------

@Client.on_message(filters.regex("^(🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ|🚀 Open Mini App)$") & filters.private)
async def open_miniapp_handler(client, message):
    text = (
        "🚀 <b>ᴍɪɴɪ sᴛᴏʀᴇ ᴀᴘᴘ</b>\n\n"
        "ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴏᴘᴇɴ ᴏᴜʀ ᴏғғɪᴄɪᴀʟ ᴍɪɴɪ ᴀᴘᴘ ᴀɴᴅ ᴇxᴘʟᴏʀᴇ ᴀʟʟ sᴛᴏʀɪᴇs!"
    )
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 ʟᴀᴜɴᴄʜ ᴍɪɴɪ ᴀᴘᴘ", web_app=WebAppInfo(url=WEB_APP_URL))]
    ])
    await message.reply_text(text, reply_markup=btn)

@Client.on_message(filters.regex("^(📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ|📢 Updates Channel)$") & filters.private)
async def updates_handler(client, message):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ", url="https://t.me/freestoryhubMR")]
    ])
    await message.reply_text("<b>📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ:</b>\n\nᴊᴏɪɴ ᴏᴜʀ ᴄʜᴀɴɴᴇʟ ғᴏʀ ᴛʜᴇ ʟᴀᴛᴇsᴛ ᴜᴘᴅᴀᴛᴇs ᴀɴᴅ ɴᴇᴡ sᴛᴏʀɪᴇs!", reply_markup=kb)

@Client.on_message(filters.regex("^(👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ|👤 My Account)$") & filters.private)
async def account_handler(client, message):
    user = message.from_user
    purchases = await get_user_purchases(user.id)
    balance = await get_user_wallet(user.id)
    
    acc_text = (
        f"<b>👤 ᴀᴄᴄᴏᴜɴᴛ ᴅᴇᴛᴀɪʟs:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"<b>ɴᴀᴍᴇ:</b> {user.first_name}\n"
        f"<b>ᴜsᴇʀ ɪᴅ:</b> <code>{user.id}</code>\n"
        f"<b>ᴜsᴇʀɴᴀᴍᴇ:</b> @{user.username if user.username else 'N/A'}\n"
        f"<b>👛 ᴡᴀʟʟᴇᴛ ʙᴀʟᴀɴᴄᴇ:</b> ₹{balance}\n"
        f"<b>sᴛᴀᴛᴜs:</b> ᴀᴄᴛɪᴠᴇ ᴜsᴇʀ ⚡\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    if not purchases:
        acc_text += "❌ <b>ʏᴏᴜ ʜᴀᴠᴇɴ'ᴛ ᴘᴜʀᴄʜᴀsᴇᴅ ᴀɴʏ sᴛᴏʀɪᴇs ʏᴇᴛ.</b>"
        return await message.reply_text(acc_text)
    
    acc_text += "📖 <b>ʏᴏᴜʀ ᴘᴜʀᴄʜᴀsᴇᴅ sᴛᴏʀɪᴇs:</b>\n\n"
    buttons = []
    
    for item in purchases:
        story = await get_story_by_title(item['story_title'])
        if story:
            acc_text += f"• <b>{story['title']}</b>\n"
            buttons.append([InlineKeyboardButton(f"🚀 ᴀᴄᴄᴇss {story['title']}", url=story['link'])])
            
    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
    await message.reply_text(acc_text, reply_markup=reply_markup)

@Client.on_message(filters.regex("^(📞 sᴜᴘᴘᴏʀᴛ|📞 Support)$") & filters.private)
async def support_handler(client, message):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ", url="https://t.me/pratilipifm0900")]
    ])
    await message.reply_text("<b>📞 ᴄᴜsᴛᴏᴍᴇʀ sᴜᴘᴘᴏʀᴛ:</b>\n\nɪғ ʏᴏᴜ ғᴀᴄᴇ ᴀɴʏ ɪssᴜᴇs, ғᴇᴇʟ ғʀᴇᴇ ᴛᴏ ᴄᴏɴᴛᴀᴄᴛ support.", reply_markup=kb)
