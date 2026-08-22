import json
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, CallbackQuery
from database.db import get_story_by_title, send_log, is_user_registered, register_user, get_user_purchases
from config import BOT_USERNAME, WEB_APP_URL

# 1. Main Menu Keyboard Layout (Changed to Inline Keyboard)
MAIN_MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ", callback_data="open_miniapp_info")],
    [InlineKeyboardButton("📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ", url="https://t.me/freestoryhubMR")],
    [
        InlineKeyboardButton("🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ", callback_data="search_story"),
        InlineKeyboardButton("📻 ᴘᴏᴄᴋᴇᴛ ғᴍ", callback_data="pocket_fm")
    ],
    [
        InlineKeyboardButton("📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ", callback_data="pratilipi_fm"),
        InlineKeyboardButton("👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ", callback_data="my_account")
    ],
    [InlineKeyboardButton("📞 sᴜᴘᴘᴏʀᴛ", callback_data="support_info")]
])

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
        price = data.get("price")
        
        if action == "buy_story":
            story = await get_story_by_title(story_title)
            clean_title = story_title.replace(" ", "_")
            
            btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 ᴘᴀʏ ɴᴏᴡ", callback_data=f"buy_{clean_title}_{price}")]
            ])
            
            photo_url = story.get('photo', 'https://picsum.photos/400/200') if story else 'https://picsum.photos/400/200'
            desc = story.get('desc', 'ɴᴏ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴀᴠᴀɪʟᴀʙʟᴇ.') if story else ''

            caption_text = (
                f"🛒 <b>ᴏʀᴅᴇʀ ɪɴɪᴛɪᴀᴛᴇᴅ ғʀᴏᴍ ᴍɪɴɪ ᴀᴘᴘ</b>\n\n"
                f"📖 <b>ᴛɪᴛʟᴇ:</b> {story_title}\n"
                f"💰 <b>ᴘʀɪᴄᴇ:</b> ₹{price}\n"
                f"📝 <b>ᴅᴇsᴄ:</b> {desc}\n\n"
                f"👇 <b>Click below to complete purchase:</b>"
            )
            
            try:
                await message.reply_photo(
                    photo=photo_url,
                    caption=caption_text,
                    reply_markup=btn
                )
            except Exception:
                await message.reply_text(
                    caption_text,
                    reply_markup=btn
                )
    except Exception as e:
        print(f"WebApp Data Error: {e}")

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
        story_title = args[1].replace("story_", "").replace("_", " ")
        story = await get_story_by_title(story_title)
        
        if story:
            clean_title = story['title'].replace(" ", "_")
            btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 ʙᴜʏ ɴᴏᴡ", callback_data=f"buy_{clean_title}_{story['price']}")]
            ])
            photo_url = story.get('photo', 'https://picsum.photos/400/200')
            desc = story.get('desc', 'ɴᴏ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴀᴠᴀɪʟᴀʙʟᴇ.')
            
            caption_text = f"📖 <b>ᴛɪᴛʟᴇ:</b> {story['title']}\n💰 <b>ᴘʀɪᴄᴇ:</b> ₹{story['price']}\n📝 <b>ᴅᴇsᴄ:</b> {desc}"
            
            try:
                return await message.reply_photo(
                    photo=photo_url,
                    caption=caption_text,
                    reply_markup=btn
                )
            except Exception:
                return await message.reply_text(
                    caption_text,
                    reply_markup=btn
                )
        else:
            return await message.reply_text("❌ <b>ᴛʜɪs sᴛᴏʀʏ ɪs ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ.</b>", reply_markup=MAIN_MENU)

    welcome_text = (
        f"<b>━━━━━━━ 🌟 sᴛᴏʀʏ sᴇʟʟᴇʀ ʙᴏᴛ 🌟 ━━━━━━━</b>\n\n"
        f"ʜᴇʟʟᴏ {user.first_name}! 👋\n\n"
        "ᴜsᴇ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ sᴇᴀʀᴄʜ ᴏʀ ᴘᴜʀᴄʜᴀsᴇ ʏᴏᴜʀ ғᴀᴠᴏʀɪᴛᴇ sᴛᴏʀɪᴇs."
    )
    await message.reply_text(welcome_text, reply_markup=MAIN_MENU)

# ------------------ Callback Queries (Buttons Click Handlers) ------------------
@Client.on_callback_query()
async def callback_handler(client, query: CallbackQuery):
    data = query.data
    user = query.from_user

    # A. 🚀 MINI APP BUTTON CLICK
    if data == "open_miniapp_info":
        await query.answer()
        
        miniapp_text = (
            "🚀 <b>ᴍɪɴɪ sᴛᴏʀᴇ ᴀᴘᴘ</b>\n\n"
            "ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴏᴘᴇɴ ᴏᴜʀ ᴏғғɪᴄɪᴀʟ ᴍɪɴɪ ᴀᴘᴘ ᴀɴᴅ ᴇxᴘʟᴏʀᴇ ᴀʟʟ ᴀᴜᴅɪᴏ sᴇʀɪᴇs!"
        )
        
        miniapp_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 ʟᴀᴜɴᴄʜ ᴍɪɴɪ ᴀᴘᴘ", web_app=WebAppInfo(url=WEB_APP_URL))],
            [InlineKeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴇɴᴜ", callback_data="back_to_main")]
        ])
        
        await query.message.edit_text(miniapp_text, reply_markup=miniapp_kb)

    # B. 📞 SUPPORT BUTTON CLICK
    elif data == "support_info":
        await query.answer()
        
        support_text = (
            "<b>📞 ᴄᴜsᴛᴏᴍᴇʀ sᴜᴘᴘᴏʀᴛ:</b>\n\n"
            "ɪғ ʏᴏᴜ ғᴀᴄᴇ ᴀɴʏ ɪssᴜᴇs, ғᴇᴇʟ ғʀᴇᴇ ᴛᴏ ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ."
        )
        
        support_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ", url="https://t.me/pratilipifm0900")],
            [InlineKeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴇɴᴜ", callback_data="back_to_main")]
        ])
        
        await query.message.edit_text(support_text, reply_markup=support_kb)

    # C. 👤 MY ACCOUNT CLICK
    elif data == "my_account":
        await query.answer()
        purchases = await get_user_purchases(user.id)
        
        acc_text = (
            f"<b>👤 ᴀᴄᴄᴏᴜɴᴛ ᴅᴇᴛᴀɪʟs:</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<b>ɴᴀᴍᴇ:</b> {user.first_name}\n"
            f"<b>ᴜsᴇʀ ɪᴅ:</b> <code>{user.id}</code>\n"
            f"<b>ᴜsᴇʀɴᴀᴍᴇ:</b> @{user.username if user.username else 'N/A'}\n"
            f"<b>sᴛᴀᴛᴜs:</b> ᴀᴄᴛɪᴠᴇ ᴜsᴇʀ ⚡\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
        )
        
        buttons = []
        if not purchases:
            acc_text += "❌ <b>ʏᴏᴜ ʜᴀᴠᴇɴ'ᴛ ᴘᴜʀᴄʜᴀsᴇᴅ ᴀɴʏ sᴛᴏʀɪᴇs ʏᴇᴛ.</b>"
        else:
            acc_text += "📖 <b>ʏᴏᴜʀ ᴘᴜʀᴄʜᴀsᴇᴅ sᴛᴏʀɪᴇs:</b>\n\n"
            for item in purchases:
                story = await get_story_by_title(item['story_title'])
                if story:
                    acc_text += f"• <b>{story['title']}</b>\n"
                    buttons.append([InlineKeyboardButton(f"🚀 ᴀᴄᴄᴇss {story['title']}", url=story['link'])])
        
        buttons.append([InlineKeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴇɴᴜ", callback_data="back_to_main")])
        await query.message.edit_text(acc_text, reply_markup=InlineKeyboardMarkup(buttons))

    # D. 🔙 BACK TO MAIN MENU CLICK
    elif data == "back_to_main":
        await query.answer()
        
        welcome_text = (
            f"<b>━━━━━━━ 🌟 sᴛᴏʀʏ sᴇʟʟᴇʀ ʙᴏᴛ 🌟 ━━━━━━━</b>\n\n"
            f"ʜᴇʟʟᴏ {user.first_name}! 👋\n\n"
            "ᴜsᴇ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ sᴇᴀʀᴄʜ ᴏʀ ᴘᴜʀᴄʜᴀsᴇ ʏᴏᴜʀ ғᴀᴠᴏʀɪᴛᴇ sᴛᴏʀɪᴇs."
        )
        
        await query.message.edit_text(welcome_text, reply_markup=MAIN_MENU)
