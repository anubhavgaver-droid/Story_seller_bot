import json
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    WebAppInfo,
    CallbackQuery
)

# Required Database functions
from database.db import (
    get_story_by_title, 
    send_log, 
    is_user_registered, 
    register_user, 
    get_user_purchases, 
    get_user_wallet,
    update_user_wallet,
    add_user_purchase,
    is_story_unlocked
)
from config import BOT_USERNAME, WEB_APP_URL, CHANNEL_ID

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

            clean_title = story_title.strip().split("\n")[0]
            encoded_title = clean_title.replace(" ", "_")
            wallet_bal = await get_user_wallet(message.from_user.id)
            
            # Payment Option Keyboard
            inline_buttons = []
            
            # Demo button check (Using demo_enabled)
            if story.get('demo_enabled', False):
                inline_buttons.append([InlineKeyboardButton("🎬 ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ", callback_data=f"viewdemo_{encoded_title}")])

            inline_buttons.extend([
                [InlineKeyboardButton(f"💳 ᴅɪʀᴇᴄᴛ ᴘᴀʏ (₹{price})", callback_data=f"buy_{encoded_title}_{price}")],
                [InlineKeyboardButton(f"👛 ᴘᴀʏ ᴠɪᴀ ᴡᴀʟʟᴇᴛ (Bal: ₹{wallet_bal})", callback_data=f"walletpay_{encoded_title}_{price}")]
            ])
            
            btn = InlineKeyboardMarkup(inline_buttons)
            
            photo_url = story.get('photo', 'https://picsum.photos/400/200')
            desc = story.get('desc', 'ɴᴏ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴀᴠᴀɪʟᴀʙʟᴇ.')

            caption_text = (
                f"🛒 <b>ᴏʀᴅᴇʀ ɪɴɪᴛɪᴀᴛᴇᴅ ғʀᴏᴍ ᴍɪɴɪ ᴀᴘᴘ</b>\n\n"
                f"📖 <b>ᴛɪᴛʟᴇ:</b> {clean_title}\n"
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

# ------------------ View Demo Callback Handler (10 Min Auto Delete) ------------------
@Client.on_callback_query(filters.regex(r"^viewdemo_"))
async def view_demo_callback(client: Client, callback_query: CallbackQuery):
    try:
        encoded_title = callback_query.data.split("viewdemo_")[1]
        story_title = encoded_title.replace("_", " ")
        
        story = await get_story_by_title(story_title)
        if not story or not story.get("demo_enabled"):
            return await callback_query.answer("⚠️ Demo is not available for this story!", show_alert=True)
            
        demo_ids = story.get("demo_msg_ids", [])
        if not demo_ids:
            return await callback_query.answer("❌ No Demo files available!", show_alert=True)
            
        await callback_query.answer("🎬 Sending Demo files... Please check your chat!")
        
        user_id = callback_query.from_user.id
        sent_messages = []
        
        # Header Message
        header_msg = await client.send_message(
            chat_id=user_id,
            text=f"🎬 <b>ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ ғᴏʀ:</b> <code>{story['title']}</code>\n\n"
                 f"⏰ <i>This demo preview will automatically delete in 10 minutes!</i>"
        )
        sent_messages.append(header_msg)
        
        # Copy Auto-Picked Demo Messages from DB Channel
        for msg_id in demo_ids:
            try:
                copied_msg = await client.copy_message(
                    chat_id=user_id,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg_id,
                    caption=f"🎧 <b>Demo Sample</b> - {story['title']}"
                )
                sent_messages.append(copied_msg)
            except Exception as e:
                print(f"Error copying demo msg {msg_id}: {e}")

        # Async background task to auto delete after 10 minutes (600s)
        async def auto_delete_task(messages_list):
            await asyncio.sleep(600)  # 10 Minutes Timer
            for msg in messages_list:
                try:
                    await msg.delete()
                except Exception:
                    pass
                    
        asyncio.create_task(auto_delete_task(sent_messages))

    except Exception as e:
        print(f"Error in view_demo_callback: {e}")
        await callback_query.answer("❌ Failed to send Demo files!", show_alert=True)

# ------------------ Wallet Payment Callback Handler ------------------
@Client.on_callback_query(filters.regex(r"^walletpay_"))
async def process_wallet_payment(client, callback_query):
    try:
        data_parts = callback_query.data.split("_")
        
        # Split safely from the last item to support spaces in story titles
        price = float(data_parts[-1])
        story_title = " ".join(data_parts[1:-1])

        story = await get_story_by_title(story_title)
        if not story:
            return await callback_query.answer("❌ Story not found!", show_alert=True)

        user_id = callback_query.from_user.id
        current_balance = await get_user_wallet(user_id)

        # 1. Balance Check
        if current_balance < price:
            return await callback_query.answer(
                f"❌ Insufficient Balance!\nRequired: ₹{price}\nAvailable: ₹{current_balance}\n\nPlease top-up your wallet.",
                show_alert=True
            )

        clean_title = story['title'].strip().split("\n")[0]
        encoded_title = clean_title.replace(" ", "_")
        delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"

        # 2. Deduct Balance & Add Purchase
        new_balance = current_balance - price
        await update_user_wallet(user_id, new_balance)
        await add_user_purchase(user_id, clean_title, story_link=delivery_link)

        await callback_query.answer("🎉 Purchase successful! Story unlocked.", show_alert=True)
        
        success_text = (
            f"✅ <b>ᴘᴜʀᴄʜᴀsᴇ sᴜᴄᴄᴇssғᴜʟ!</b>\n\n"
            f"📖 <b>sᴛᴏʀʏ:</b> {clean_title}\n"
            f"💸 <b>ᴅᴇᴅᴜᴄᴛᴇᴅ:</b> ₹{price}\n"
            f"👛 <b>ʀᴇᴍᴀɪɴɪɴɢ ʙᴀʟᴀɴᴄᴇ:</b> ₹{new_balance}\n\n"
            f"👇 Click below to access your story files:"
        )
        
        access_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (Unlocked)", url=delivery_link)]
        ])
        
        await callback_query.message.edit_text(success_text, reply_markup=access_btn)

    except Exception as e:
        print(f"Error processing wallet payment: {e}")
        await callback_query.answer("❌ Error processing wallet payment!", show_alert=True)

# ------------------ Start & Deep-Link Batch Delivery Handler ------------------
@Client.on_message(filters.command("start") & filters.private, group=-1)
async def start_handler(client, message):
    user = message.from_user
    
    # 1. User Registration Logic
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
    
    # 2. BATCH DELIVERY MECHANISM (get_ENCODED_TITLE)
    if len(args) > 1 and args[1].startswith("get_"):
        raw_param = args[1]
        try:
            encoded_title = raw_param.replace("get_", "")
            story_title = encoded_title.replace("_", " ")
        except Exception:
            return await message.reply_text("❌ <b>ɪɴᴠᴀʟɪᴅ ᴏʀ ᴄᴏʀʀᴜᴘᴛᴇᴅ ʟɪɴᴋ!</b>")

        story = await get_story_by_title(story_title)
        if not story:
            return await message.reply_text("❌ <b>sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ ɪɴ ᴅᴀᴛᴀʙᴀsᴇ!</b>")

        clean_title = story['title'].strip().split("\n")[0]

        # Purchase Status Verification
        unlocked = await is_story_unlocked(user.id, clean_title)
        if not unlocked:
            buy_btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 ʙᴜʏ ɴᴏᴡ", callback_data=f"buy_{encoded_title}_{story['price']}")]
            ])
            return await message.reply_text(
                f"🔒 <b>ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ!</b>\n\n"
                f"You haven't purchased <b>{clean_title}</b> yet.\n"
                f"Please buy it first to unlock access.",
                reply_markup=buy_btn
            )

        first_id = story.get('first_msg_id')
        last_id = story.get('last_msg_id')

        if not first_id or not last_id:
            return await message.reply_text("⚠️ <b>ɴᴏ ғɪʟᴇs ᴀssᴏᴄɪᴀᴛᴇᴅ ᴡɪᴛʜ ᴛʜɪs sᴛᴏʀʏ!</b>\nPlease contact support.")

        status_msg = await message.reply_text(f"⏳ <b>ғᴇᴛᴄʜɪɴɢ ғɪʟᴇs ғᴏʀ:</b> <i>{clean_title}</i>\nᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...")

        # File Delivery Loop
        success_count = 0
        total_files = (last_id - first_id) + 1

        for msg_id in range(first_id, last_id + 1):
            try:
                await client.copy_message(
                    chat_id=user.id,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg_id,
                    protect_content=True
                )
                success_count += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Error copying message {msg_id}: {e}")

        try:
            await status_msg.delete()
        except Exception:
            pass

        if success_count > 0:
            return await message.reply_text(
                f"🎉 <b>All files delivered successfully!</b>\n\n"
                f"📖 <b>Story:</b> {clean_title}\n"
                f"📦 <b>Delivered Episodes/Files:</b> {success_count} / {total_files}"
            )
        else:
            return await message.reply_text("❌ <b>Failed to deliver files. Make sure bot is Admin in DB Channel.</b>")

    # 3. DIRECT STORY VIEW FROM DEEP LINK (story_ENCODED_TITLE)
    if len(args) > 1 and args[1].startswith("story_"):
        raw_param = args[1]
        story_title = raw_param.replace("story_", "").replace("_", " ")
        story = await get_story_by_title(story_title)
        
        if story:
            clean_title = story['title'].strip().split("\n")[0]
            encoded_title = clean_title.replace(" ", "_")
            photo_url = story.get('photo', 'https://picsum.photos/400/200')
            desc = story.get('desc', 'ɴᴏ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴀᴠᴀɪʟᴀʙʟᴇ.')
            wallet_bal = await get_user_wallet(user.id)
            
            miniapp_direct_url = f"{WEB_APP_URL}?tgWebAppStartParam={raw_param}"
            
            # Keyboards Creation
            buttons = [
                [
                    InlineKeyboardButton(
                        "🚀 ᴏᴘᴇɴ ᴅɪʀᴇᴄᴛ sᴛᴏʀʏ ᴍɪɴɪ ᴀᴘᴘ", 
                        web_app=WebAppInfo(url=miniapp_direct_url)
                    )
                ]
            ]
            
            # Add Demo Button if demo_enabled is True
            if story.get('demo_enabled', False):
                buttons.append([InlineKeyboardButton("🎬 ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ", callback_data=f"viewdemo_{encoded_title}")])

            # Add Buy & Wallet Buttons
            buttons.append([
                InlineKeyboardButton(
                    f"💳 ᴅɪʀᴇᴄᴛ ʙᴜʏ (₹{story['price']})", 
                    callback_data=f"buy_{encoded_title}_{story['price']}"
                )
            ])
            buttons.append([
                InlineKeyboardButton(
                    f"👛 ᴘᴀʏ ᴠɪᴀ ᴡᴀʟʟᴇᴛ (Bal: ₹{wallet_bal})", 
                    callback_data=f"walletpay_{encoded_title}_{story['price']}"
                )
            ])
            
            btn = InlineKeyboardMarkup(buttons)
            
            caption_text = (
                f"📖 <b>ᴛɪᴛʟᴇ:</b> {clean_title}\n"
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

    # 4. NORMAL /START WELCOME MESSAGE
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
        [InlineKeyboardButton("➕ ᴀᴅᴅ ᴍᴏɴᴇʏ / ᴛᴏᴘ-ᴜᴘ", callback_data="add_wallet_funds")]
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
            clean_title = story['title'].strip().split("\n")[0]
            encoded_title = clean_title.replace(" ", "_")
            delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"
            
            acc_text += f"• <b>{clean_title}</b>\n"
            buttons.append([InlineKeyboardButton(f"🚀 ᴀᴄᴄᴇss {clean_title}", url=delivery_link)])
            
    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
    await message.reply_text(acc_text, reply_markup=reply_markup)

@Client.on_message(filters.regex("^(📞 sᴜᴘᴘᴏʀᴛ|📞 Support)$") & filters.private)
async def support_handler(client, message):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ", url="https://t.me/pratilipifm0900")]
    ])
    await message.reply_text("<b>📞 ᴄᴜsᴛᴏᴍᴇʀ sᴜᴘᴘᴏʀᴛ:</b>\n\nɪғ ʏᴏᴜ ғᴀᴄᴇ ᴀɴʏ ɪssᴜᴇs, ғᴇᴇʟ ғʀᴇᴇ ᴛᴏ ᴄᴏɴᴛᴀᴄᴛ support.", reply_markup=kb)
