import json
from pyrogram import Client, filters, enums
from pyrogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    WebAppInfo, 
    ForceReply
)
from database.db import (
    get_story_by_title, 
    send_log, 
    is_user_registered, 
    register_user, 
    get_user_purchases, 
    get_stories_by_cat, 
    search_stories_db
)
from config import BOT_USERNAME, WEB_APP_URL

# Search State Dictionary
SEARCH_WAITING = {}

# 1. Main Menu Keyboard Layout
MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ")],
        [KeyboardButton("📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ", style=enums.ButtonStyle.PRIMARY)],
        [KeyboardButton("🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ", style=enums.ButtonStyle.SUCCESS), KeyboardButton("📻 ᴘᴏᴄᴋᴇᴛ ғᴍ", style=enums.ButtonStyle.DANGER)],
        [KeyboardButton("📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ", style=enums.ButtonStyle.DANGER), KeyboardButton("👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ", style=enums.ButtonStyle.PRIMARY)],
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

# ------------------ Start Handler (Dual Deep Linking Support) ------------------
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
    
    # Check if Deep Link Parameter Exists (e.g. story_XYZ)
    if len(args) > 1 and args[1].startswith("story_"):
        raw_param = args[1]
        story_title = raw_param.replace("story_", "").replace("_", " ")
        story = await get_story_by_title(story_title)
        
        if story:
            clean_title = story['title'].replace(" ", "_")
            photo_url = story.get('photo', 'https://picsum.photos/400/200')
            desc = story.get('desc', 'ɴᴏ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴀᴠᴀɪʟᴀʙʟᴇ.')
            
            # Mini App Deep Link URL Param
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
                        f"💳 ʙᴜʏ ɴᴏᴡ (₹{story['price']})", 
                        callback_data=f"buy_{clean_title}_{story['price']}"
                    )
                ]
            ])
            
            caption_text = (
                f"📖 <b>ᴛɪᴛʟᴇ:</b> {story['title']}\n"
                f"💰 <b>ᴘʀɪᴄᴇ:</b> ₹{story['price']}\n"
                f"📝 <b>ᴅᴇsᴄ:</b> {desc}\n\n"
                f"<i>👇 Choose an option below to view or purchase:</i>"
            )
            
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

    # Normal Welcome Message
    welcome_text = (
        f"<b>━━━━━━━ 🌟 sᴛᴏʀʏ sᴇʟʟᴇʀ ʙᴏᴛ 🌟 ━━━━━━━</b>\n\n"
        f"ʜᴇʟʟᴏ {user.first_name}! 👋\n\n"
        "ᴜsᴇ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ sᴇᴀʀᴄʜ ᴏʀ ᴘᴜʀᴄʜᴀsᴇ ʏᴏᴜʀ ғᴀᴠᴏʀɪᴛᴇ sᴛᴏʀɪᴇs."
    )
    await message.reply_text(welcome_text, reply_markup=MAIN_MENU)

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
    
    acc_text = (
        f"<b>👤 ᴀᴄᴄᴏᴜɴᴛ ᴅᴇᴛᴀɪʟs:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"<b>ɴᴀᴍᴇ:</b> {user.first_name}\n"
        f"<b>ᴜsᴇʀ ɪᴅ:</b> <code>{user.id}</code>\n"
        f"<b>ᴜsᴇʀɴᴀᴍᴇ:</b> @{user.username if user.username else 'N/A'}\n"
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
