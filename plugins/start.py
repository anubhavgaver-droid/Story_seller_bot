import json
import asyncio
import time
from pyrogram import Client, filters, enums
from pyrogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    ForceReply,
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
from strings import get_text, USER_LANG  # Language Engine Imported

# Storage Dictionaries for Clean Chat & Range Input
CLEAN_CHAT_STORAGE = {}
START_RANGE_WAITING = {}

# ------------------ Dynamic Main Menu Generator ------------------
def get_main_menu(user_id: int):
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(get_text(user_id, "btn_miniapp"))],
            [
                KeyboardButton(get_text(user_id, "btn_wallet"), style=enums.ButtonStyle.SUCCESS), 
                KeyboardButton(get_text(user_id, "btn_account"), style=enums.ButtonStyle.PRIMARY)
            ],
            [
                KeyboardButton(get_text(user_id, "btn_search"), style=enums.ButtonStyle.SUCCESS), 
                KeyboardButton(get_text(user_id, "btn_pocket"), style=enums.ButtonStyle.DANGER)
            ],
            [
                KeyboardButton(get_text(user_id, "btn_pratilipi"), style=enums.ButtonStyle.DANGER), 
                KeyboardButton(get_text(user_id, "btn_updates"), style=enums.ButtonStyle.PRIMARY)
            ],
            [
                KeyboardButton(get_text(user_id, "btn_support"), style=enums.ButtonStyle.SUCCESS),
                KeyboardButton(get_text(user_id, "btn_lang"), style=enums.ButtonStyle.PRIMARY)
            ]
        ],
        resize_keyboard=True
    )

# Custom Filter for WebApp Data
async def web_app_filter(_, __, message):
    return bool(message.web_app_data)

filter_webapp = filters.create(web_app_filter)

# ------------------ Helper: File Delivery Function ------------------
async def send_story_files_start(client, user_id, story, first_id, last_id, clean_title, custom_range_text=""):
    sent_message_ids = []
    success_count = 0
    total_files = (last_id - first_id) + 1

    fetching_text = get_text(user_id, "fetching_files").format(range_text=custom_range_text)
    status_msg = await client.send_message(user_id, fetching_text)
    
    for msg_id in range(first_id, last_id + 1):
        try:
            sent_msg = await client.copy_message(
                chat_id=user_id,
                from_chat_id=CHANNEL_ID,
                message_id=msg_id,
                protect_content=True
            )
            sent_message_ids.append(sent_msg.id)
            success_count += 1
            await asyncio.sleep(0.4)  # Avoid FloodWait
        except Exception as e:
            print(f"Error copying message {msg_id}: {e}")

    sent_message_ids.append(status_msg.id)
    
    delivery_key = f"{user_id}_{int(time.time())}"
    CLEAN_CHAT_STORAGE[delivery_key] = sent_message_ids

    clean_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, "btn_cleanchat"), callback_data=f"cleanchat_{delivery_key}")]
    ])

    delivered_msg = get_text(user_id, "files_delivered").format(
        range_text=custom_range_text,
        title=clean_title,
        success=success_count,
        total=total_files
    )

    await client.send_message(
        chat_id=user_id,
        text=delivered_msg,
        reply_markup=clean_kb
    )

# ------------------ Language Change System Handlers ------------------
@Client.on_message(filters.regex(r"^(🌐 Change Language|🌐 भाषा बदलें)$") & filters.private)
async def language_menu_handler(client, message):
    user_id = message.from_user.id
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇮🇳 हिंदी (Hindi)", callback_data="setlang_hi"),
            InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en")
        ]
    ])
    await message.reply_text(get_text(user_id, "choose_language"), reply_markup=kb, quote=True)

@Client.on_callback_query(filters.regex(r"^setlang_"))
async def save_language_callback(client, callback_query):
    user_id = callback_query.from_user.id
    selected_lang = callback_query.data.split("setlang_")[1]
    USER_LANG[user_id] = selected_lang

    await callback_query.answer(get_text(user_id, "lang_updated_alert"), show_alert=True)
    await callback_query.message.reply_text(
        get_text(user_id, "lang_saved_msg"),
        reply_markup=get_main_menu(user_id)
    )

# ------------------ Mini App Web Data Receiver ------------------
@Client.on_message(filters.service & filter_webapp & filters.private)
async def web_app_data_handler(client, message):
    try:
        user_id = message.from_user.id
        data = json.loads(message.web_app_data.data)
        action = data.get("action")
        story_title = data.get("title")
        price = float(data.get("price", 0))
        
        if action == "buy_story":
            story = await get_story_by_title(story_title)
            if not story:
                return await message.reply_text(get_text(user_id, "story_not_found"), quote=True)

            clean_title = story_title.strip().split("\n")[0]
            encoded_title = clean_title.replace(" ", "_")
            wallet_bal = await get_user_wallet(user_id)
            
            inline_buttons = []
            
            if story.get('demo_enabled', False):
                inline_buttons.append([InlineKeyboardButton(get_text(user_id, "btn_demo"), callback_data=f"viewdemo_{encoded_title}")])

            direct_pay_txt = get_text(user_id, "btn_direct_pay").format(price=price)
            wallet_pay_txt = get_text(user_id, "btn_wallet_pay").format(bal=wallet_bal)

            inline_buttons.extend([
                [InlineKeyboardButton(direct_pay_txt, callback_data=f"buy_{encoded_title}_{price}")],
                [InlineKeyboardButton(wallet_pay_txt, callback_data=f"walletpay_{encoded_title}_{price}")]
            ])
            
            btn = InlineKeyboardMarkup(inline_buttons)
            photo_url = story.get('photo', 'https://picsum.photos/400/200')
            desc = story.get('desc', get_text(user_id, "no_desc"))

            caption_text = get_text(user_id, "order_initiated_card").format(
                title=clean_title,
                price=price,
                bal=wallet_bal,
                desc=desc
            )
            
            try:
                await message.reply_photo(photo=photo_url, caption=caption_text, reply_markup=btn, quote=True)
            except Exception:
                await message.reply_text(caption_text, reply_markup=btn, quote=True)
    except Exception as e:
        print(f"WebApp Data Error: {e}")

# ------------------ View Demo Callback Handler ------------------
@Client.on_callback_query(filters.regex(r"^viewdemo_"))
async def view_demo_callback(client: Client, callback_query: CallbackQuery):
    try:
        user_id = callback_query.from_user.id
        encoded_title = callback_query.data.split("viewdemo_")[1]
        story_title = encoded_title.replace("_", " ")
        
        story = await get_story_by_title(story_title)
        if not story or not story.get("demo_enabled"):
            return await callback_query.answer(get_text(user_id, "demo_not_available"), show_alert=True)
            
        demo_ids = story.get("demo_msg_ids", [])
        if not demo_ids:
            return await callback_query.answer(get_text(user_id, "no_demo_files"), show_alert=True)
            
        await callback_query.answer(get_text(user_id, "sending_demo_alert"))
        
        sent_messages = []
        header_text = get_text(user_id, "demo_header").format(title=story['title'])
        header_msg = await client.send_message(chat_id=user_id, text=header_text)
        sent_messages.append(header_msg)
        
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

        async def auto_delete_task(messages_list):
            await asyncio.sleep(600)
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
        user_id = callback_query.from_user.id
        data_parts = callback_query.data.split("_")
        price = float(data_parts[-1])
        story_title = " ".join(data_parts[1:-1])

        story = await get_story_by_title(story_title)
        if not story:
            return await callback_query.answer(get_text(user_id, "story_not_found"), show_alert=True)

        current_balance = await get_user_wallet(user_id)

        if current_balance < price:
            return await callback_query.answer(
                get_text(user_id, "insufficient_balance_alert").format(price=price, bal=current_balance),
                show_alert=True
            )

        clean_title = story['title'].strip().split("\n")[0]
        encoded_title = clean_title.replace(" ", "_")
        delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"

        new_balance = current_balance - price
        await update_user_wallet(user_id, new_balance)
        await add_user_purchase(user_id, clean_title, story_link=delivery_link)

        await callback_query.answer(get_text(user_id, "purchase_success_alert"), show_alert=True)
        
        success_text = get_text(user_id, "purchase_success_msg").format(
            title=clean_title,
            price=price,
            bal=new_balance
        )
        
        access_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text(user_id, "btn_get_files_unlocked"), url=delivery_link)]
        ])
        
        await callback_query.message.edit_text(success_text, reply_markup=access_btn)

    except Exception as e:
        print(f"Error processing wallet payment: {e}")
        await callback_query.answer("❌ Error processing wallet payment!", show_alert=True)

# ------------------ Start Batch Callback Router ------------------
@Client.on_callback_query(filters.regex(r"^(sendall_|sendcustom_|askrange_|cleanchat_)"))
async def start_batch_callback_router(client, callback_query):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    if data.startswith("sendall_"):
        encoded_title = data.split("sendall_")[1]
        story_title = encoded_title.replace("_", " ")
        story = await get_story_by_title(story_title)
        if not story:
            return await callback_query.answer(get_text(user_id, "story_not_found"), show_alert=True)
            
        await callback_query.message.edit_text(get_text(user_id, "preparing_files"))
        clean_title = story['title'].strip().split("\n")[0]
        await send_story_files_start(client, user_id, story, story['first_msg_id'], story['last_msg_id'], clean_title)
        await callback_query.answer()

    elif data.startswith("sendcustom_"):
        parts = data.split(":")
        encoded_title = parts[0].replace("sendcustom_", "")
        range_idx = int(parts[1])

        story_title = encoded_title.replace("_", " ")
        story = await get_story_by_title(story_title)
        if not story:
            return await callback_query.answer(get_text(user_id, "story_not_found"), show_alert=True)

        custom_ranges = story.get('custom_ranges', [])
        if range_idx >= len(custom_ranges):
            return await callback_query.answer("❌ Invalid Range Selected!", show_alert=True)

        selected_range = custom_ranges[range_idx]
        range_name = selected_range['name']
        f_id = selected_range['first_id']
        l_id = selected_range['last_id']

        await callback_query.message.edit_text(get_text(user_id, "fetching_range_files").format(range_name=range_name))
        clean_title = story['title'].strip().split("\n")[0]
        await send_story_files_start(client, user_id, story, f_id, l_id, clean_title, custom_range_text=f"({range_name})")
        await callback_query.answer()
        
    elif data.startswith("askrange_"):
        encoded_title = data.split("askrange_")[1]
        story_title = encoded_title.replace("_", " ")
        story = await get_story_by_title(story_title)
        if not story:
            return await callback_query.answer(get_text(user_id, "story_not_found"), show_alert=True)
        
        START_RANGE_WAITING[user_id] = {
            "story": story,
            "encoded_title": encoded_title
        }
        
        total_episodes = (story['last_msg_id'] - story['first_msg_id']) + 1
        
        await callback_query.message.reply_text(
            get_text(user_id, "enter_range_prompt").format(total=total_episodes),
            reply_markup=ForceReply(selective=True)
        )
        await callback_query.answer()

    elif data.startswith("cleanchat_"):
        key = data.split("cleanchat_")[1]
        msg_ids = CLEAN_CHAT_STORAGE.get(key, [])

        if not msg_ids:
            return await callback_query.answer(get_text(user_id, "already_cleaned"), show_alert=True)

        await callback_query.answer(get_text(user_id, "cleaning_files"))

        for m_id in msg_ids:
            try:
                await client.delete_messages(chat_id=user_id, message_ids=m_id)
                await asyncio.sleep(0.1)
            except Exception:
                pass

        try:
            await callback_query.message.edit_text(get_text(user_id, "clean_success"))
        except Exception:
            pass

        CLEAN_CHAT_STORAGE.pop(key, None)

# ------------------ Process Start Custom Range Input Text ------------------
@Client.on_message(filters.private & filters.text, group=4)
async def process_start_range_input(client, message):
    user_id = message.from_user.id
    if user_id not in START_RANGE_WAITING:
        return message.continue_propagation()
        
    text = message.text.strip()
    if "-" not in text:
        return await message.reply_text(get_text(user_id, "invalid_range_format"), quote=True)
        
    try:
        start_ep, end_ep = map(int, text.split("-"))
    except ValueError:
        return await message.reply_text(get_text(user_id, "numbers_only_range"), quote=True)
        
    data = START_RANGE_WAITING.get(user_id)
    story = data['story']
    
    db_first = story['first_msg_id']
    db_last = story['last_msg_id']
    total_story_episodes = (db_last - db_first) + 1
    
    if start_ep < 1 or start_ep > end_ep:
        return await message.reply_text(get_text(user_id, "invalid_range_bounds"), quote=True)
        
    if start_ep > total_story_episodes or end_ep > total_story_episodes:
        return await message.reply_text(
            get_text(user_id, "range_out_of_bounds").format(total=total_story_episodes),
            quote=True
        )

    START_RANGE_WAITING.pop(user_id, None)

    target_first = db_first + (start_ep - 1)
    target_last = db_first + (end_ep - 1)
    clean_title = story['title'].strip().split("\n")[0]
    
    await send_story_files_start(
        client, 
        user_id, 
        story, 
        target_first, 
        target_last, 
        clean_title, 
        custom_range_text=f"(Episodes {start_ep} - {end_ep})"
    )

# ------------------ Start & Deep-Link Batch Delivery Handler ------------------
@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    user = message.from_user
    user_id = user.id
    
    try:
        registered = await is_user_registered(user_id)
        if not registered:
            await register_user(user_id, user.first_name, user.username)
            try:
                log_text = (
                    f"<b>🆕 ɴᴇᴡ ᴜsᴇʀ ʀᴇɢɪsᴛᴇʀᴇᴅ!</b>\n"
                    f"<b>ɴᴀᴍᴇ:</b> {user.first_name}\n"
                    f"<b>ᴜsᴇʀ ɪᴅ:</b> <code>{user_id}</code>\n"
                    f"<b>ᴜsᴇʀɴᴀᴍᴇ:</b> @{user.username if user.username else 'None'}"
                )
                await send_log(client, log_text)
            except Exception as e:
                print(f"Log Error: {e}")
    except Exception as db_err:
        print(f"Database Error in /start registration: {db_err}")

    args = message.text.split(maxsplit=1)
    
    if len(args) > 1 and args[1].startswith("get_"):
        raw_param = args[1]
        try:
            encoded_title = raw_param.replace("get_", "")
            story_title = encoded_title.replace("_", " ")
        except Exception:
            return await message.reply_text("❌ <b>ɪɴᴠᴀʟɪᴅ ᴏʀ ᴄᴏʀʀᴜᴘᴛᴇᴅ ʟɪɴᴋ!</b>", quote=True)

        story = await get_story_by_title(story_title)
        if not story:
            return await message.reply_text(get_text(user_id, "story_not_found"), quote=True)

        clean_title = story['title'].strip().split("\n")[0]

        unlocked = await is_story_unlocked(user_id, clean_title)
        if not unlocked:
            buy_btn = InlineKeyboardMarkup([
                [InlineKeyboardButton(get_text(user_id, "btn_buy_now"), callback_data=f"buy_{encoded_title}_{story['price']}")]
            ])
            return await message.reply_text(
                get_text(user_id, "access_denied").format(title=clean_title),
                reply_markup=buy_btn,
                quote=True
            )

        first_id = story.get('first_msg_id')
        last_id = story.get('last_msg_id')

        if not first_id or not last_id:
            return await message.reply_text("⚠️ <b>ɴᴏ ғɪʟᴇs ᴀssᴏᴄɪᴀᴛᴇᴅ ᴡɪᴛʜ ᴛʜɪs sᴛᴏʀʏ!</b>\nPlease contact support.", quote=True)

        total_files = (last_id - first_id) + 1
        custom_ranges = story.get('custom_ranges', [])

        if custom_ranges:
            buttons = []
            for idx, r in enumerate(custom_ranges):
                buttons.append([InlineKeyboardButton(f"📁 {r['name']}", callback_data=f"sendcustom_{encoded_title}:{idx}")])
            
            buttons.append([InlineKeyboardButton(get_text(user_id, "btn_all_episodes").format(total=total_files), callback_data=f"sendall_{encoded_title}")])
            buttons.append([InlineKeyboardButton(get_text(user_id, "btn_custom_range_input"), callback_data=f"askrange_{encoded_title}")])

            choice_kb = InlineKeyboardMarkup(buttons)
            return await message.reply_text(
                get_text(user_id, "story_options_prompt").format(title=clean_title, total=total_files),
                reply_markup=choice_kb,
                quote=True
            )

        if total_files > 100:
            choice_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(get_text(user_id, "btn_all_episodes").format(total=total_files), callback_data=f"sendall_{encoded_title}")],
                [InlineKeyboardButton(get_text(user_id, "btn_custom_range_input"), callback_data=f"askrange_{encoded_title}")]
            ])
            return await message.reply_text(
                get_text(user_id, "story_options_prompt").format(title=clean_title, total=total_files),
                reply_markup=choice_kb,
                quote=True
            )

        await send_story_files_start(client, user_id, story, first_id, last_id, clean_title)
        return

    if len(args) > 1 and args[1].startswith("story_"):
        raw_param = args[1]
        story_title = raw_param.replace("story_", "").replace("_", " ")
        story = await get_story_by_title(story_title)
        
        if story:
            clean_title = story['title'].strip().split("\n")[0]
            encoded_title = clean_title.replace(" ", "_")
            photo_url = story.get('photo', 'https://picsum.photos/400/200')
            desc = story.get('desc', get_text(user_id, "no_desc"))
            wallet_bal = await get_user_wallet(user_id)
            
            miniapp_direct_url = f"{WEB_APP_URL}?tgWebAppStartParam={raw_param}"
            
            buttons = [
                [
                    InlineKeyboardButton(
                        get_text(user_id, "btn_open_miniapp_direct"), 
                        web_app=WebAppInfo(url=miniapp_direct_url)
                    )
                ]
            ]
            
            if story.get('demo_enabled', False):
                buttons.append([InlineKeyboardButton(get_text(user_id, "btn_demo"), callback_data=f"viewdemo_{encoded_title}")])

            direct_pay_txt = get_text(user_id, "btn_direct_pay").format(price=story['price'])
            wallet_pay_txt = get_text(user_id, "btn_wallet_pay").format(bal=wallet_bal)

            buttons.append([InlineKeyboardButton(direct_pay_txt, callback_data=f"buy_{encoded_title}_{story['price']}")])
            buttons.append([InlineKeyboardButton(wallet_pay_txt, callback_data=f"walletpay_{encoded_title}_{story['price']}")])
            
            btn = InlineKeyboardMarkup(buttons)
            
            caption_text = get_text(user_id, "story_details_card").format(
                title=clean_title,
                price=story['price'],
                bal=wallet_bal,
                desc=desc
            )
            
            try:
                return await message.reply_photo(photo=photo_url, caption=caption_text, reply_markup=btn, quote=True)
            except Exception:
                return await message.reply_text(caption_text, reply_markup=btn, quote=True)
        else:
            return await message.reply_text(get_text(user_id, "story_not_found"), reply_markup=get_main_menu(user_id), quote=True)

    # Welcome message with dynamic menu
    welcome_text = get_text(user_id, "welcome_msg").format(name=user.first_name)
    await message.reply_text(welcome_text, reply_markup=get_main_menu(user_id), quote=True)
