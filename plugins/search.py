import json
import asyncio
import re
import difflib
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
from database.db import (
    get_stories_by_cat, 
    search_stories_db, 
    get_story_by_title,
    get_all_stories,
    get_user_wallet,
    update_user_wallet,
    add_user_purchase,
    is_story_unlocked
)
from config import WEB_APP_URL, BOT_USERNAME, CHANNEL_ID
from strings import get_text  # Import Language System

# State and Storage Dictionaries
SEARCH_WAITING = {}

# 1. Dynamic Regex Filters for Buttons across Languages
MENU_BUTTON_REGEX = (
    "^(🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ|🚀 Open Mini App|🚀 मिनी ऐप खोलें|"
    "💼 ᴍʏ ᴡᴀʟʟᴇᴛ|💼 My Wallet|💼 मेरा वॉलेट|"
    "👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ|👤 My Account|👤 मेरा खाता|"
    "🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ|🔎 Search Story|🔎 कहानी खोजें|"
    "📻 ᴘᴏᴄᴋᴇᴛ ғᴍ|📻 Pocket FM|📻 पॉकेट एफएम|"
    "📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ|📚 Pratilipi FM|📚 प्रतिलिपि एफएम|"
    "📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ|📢 Updates Channel|📢 अपडेट्स चैनल|"
    "📞 sᴜᴘᴘᴏʀᴛ|📞 Support|📞 सहायता|"
    "🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ|🔙 Back to Main Menu|🔙 मुख्य मेनू)$"
)

# 2. 🚀 OPEN MINI APP Handler
@Client.on_message(filters.regex("^(🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ|🚀 Open Mini App|🚀 मिनी ऐप खोलें)$") & filters.private)
async def miniapp_button_handler(client, message):
    user_id = message.from_user.id
    text = get_text(user_id, "mini_app_desc")
    inner_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, "btn_launch_miniapp"), web_app=WebAppInfo(url=WEB_APP_URL))]
    ])
    await message.reply_text(text, reply_markup=inner_kb, quote=True)

# 3. 💼 MY WALLET Handler
@Client.on_message(filters.regex("^(💼 ᴍʏ ᴡᴀʟʟᴇᴛ|💼 My Wallet|💼 मेरा वॉलेट)$") & filters.private)
async def wallet_handler(client, message):
    user_id = message.from_user.id
    balance = await get_user_wallet(user_id)
    
    text = get_text(user_id, "wallet_details_card").format(bal=balance)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, "btn_add_wallet_funds"), callback_data="add_wallet_funds")]
    ])
    await message.reply_text(text, reply_markup=kb, quote=True)

# 4. Pocket FM / Pratilipi FM Category Handler
@Client.on_message(filters.regex("^(📻 ᴘᴏᴄᴋᴇᴛ ғᴍ|📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ|📻 Pocket FM|📚 Pratilipi FM|📻 पॉकेट एफएम|📚 प्रतिलिपि एफएम)$") & filters.private)
async def category_handler(client, message):
    user_id = message.from_user.id
    msg_text = message.text
    
    # Map all translated button strings to category keys
    if "Pocket" in msg_text or "ᴘᴏᴄᴋᴇᴛ" in msg_text or "पॉकेट" in msg_text:
        cat_key = "pocket_fm"
    else:
        cat_key = "pratilipi_fm"
        
    stories, total_pages = await get_stories_by_cat(cat_key, page=1, limit=50)
    main_menu_kb = get_main_menu(user_id)
    
    if not stories:
        no_stories_txt = get_text(user_id, "no_stories_in_cat").format(cat=msg_text)
        return await message.reply_text(no_stories_txt, reply_markup=main_menu_kb, quote=True)
        
    keyboard_buttons = [[KeyboardButton(f"📖 {s['title'].strip().splitlines()[0]}")] for s in stories]
    keyboard_buttons.append([KeyboardButton(get_text(user_id, "btn_back_main_menu"))])
    
    category_keyboard = ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True)
    avail_txt = get_text(user_id, "available_stories_cat_title").format(cat=msg_text)
    await message.reply_text(avail_txt, reply_markup=category_keyboard, quote=True)

# 5. Back to Main Menu Handler
@Client.on_message(filters.regex("^(🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ|🔙 Back to Main Menu|🔙 मुख्य मेनू)$") & filters.private)
async def back_to_main_menu(client, message):
    user_id = message.from_user.id
    SEARCH_WAITING.pop(user_id, None)
    await message.reply_text(get_text(user_id, "main_menu_title"), reply_markup=get_main_menu(user_id), quote=True)

# 6. Story Selection Click Handler
@Client.on_message(filters.regex("^📖 ") & filters.private)
async def story_selected_handler(client, message):
    user_id = message.from_user.id
    story_title = message.text.replace("📖 ", "").strip()
    story = await get_story_by_title(story_title)
    
    if not story:
        return await message.reply_text(get_text(user_id, "story_not_available_err"), quote=True)
        
    clean_title = story['title'].strip().splitlines()[0]
    encoded_title = clean_title.replace(" ", "_")
    wallet_bal = await get_user_wallet(user_id)
    
    inline_buttons = []
    
    if story.get('demo_enabled', False):
        inline_buttons.append([InlineKeyboardButton(get_text(user_id, "btn_demo_preview"), callback_data=f"viewdemo_{encoded_title}")])
        
    inline_buttons.extend([
        [InlineKeyboardButton(get_text(user_id, "btn_direct_pay").format(price=story['price']), callback_data=f"buy_{encoded_title}_{story['price']}")],
        [InlineKeyboardButton(get_text(user_id, "btn_pay_via_wallet").format(bal=wallet_bal), callback_data=f"walletpay_{encoded_title}_{story['price']}")]
    ])
    
    btn = InlineKeyboardMarkup(inline_buttons)
    photo_url = story.get('photo', 'https://picsum.photos/400/200')
    desc = story.get('desc', get_text(user_id, "no_desc"))
    
    caption_text = get_text(user_id, "story_details_card").format(
        title=clean_title,
        price=story['price'],
        bal=wallet_bal,
        desc=desc
    )
    
    try:
        await message.reply_photo(photo=photo_url, caption=caption_text, reply_markup=btn, quote=True)
    except Exception:
        await message.reply_text(caption_text, reply_markup=btn, quote=True)

# 6.1 View Demo Callback Handler
@Client.on_callback_query(filters.regex(r"^viewdemo_"))
async def view_demo_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    try:
        encoded_title = callback_query.data.split("viewdemo_")[1]
        story_title = encoded_title.replace("_", " ")
        
        story = await get_story_by_title(story_title)
        if not story or not story.get("demo_enabled"):
            return await callback_query.answer(get_text(user_id, "demo_not_available_alert"), show_alert=True)
            
        demo_ids = story.get("demo_msg_ids", [])
        if not demo_ids:
            return await callback_query.answer(get_text(user_id, "no_demo_files_alert"), show_alert=True)
            
        await callback_query.answer(get_text(user_id, "sending_demo_alert"))
        sent_messages = []
        
        header_txt = get_text(user_id, "demo_header_msg").format(title=story['title'])
        header_msg = await client.send_message(chat_id=user_id, text=header_txt)
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

# 7. Wallet Deduction Payment Callback Handler
@Client.on_callback_query(filters.regex(r"^walletpay_"))
async def process_wallet_payment(client, callback_query):
    user_id = callback_query.from_user.id
    try:
        data_parts = callback_query.data.split("_")
        price = float(data_parts[-1])
        story_title = " ".join(data_parts[1:-1])

        story = await get_story_by_title(story_title)
        if not story:
            return await callback_query.answer(get_text(user_id, "story_not_found"), show_alert=True)

        current_balance = await get_user_wallet(user_id)

        if current_balance < price:
            insufficient_txt = get_text(user_id, "insufficient_balance_alert").format(price=price, bal=current_balance)
            return await callback_query.answer(insufficient_txt, show_alert=True)

        clean_title = story['title'].strip().splitlines()[0]
        encoded_title = clean_title.replace(" ", "_")
        delivery_link = f"https://t.me/{BOT_USERNAME}?start=get_{encoded_title}"

        new_balance = current_balance - price
        await update_user_wallet(user_id, new_balance)
        await add_user_purchase(user_id, clean_title, story_link=delivery_link)

        await callback_query.answer(get_text(user_id, "purchase_success_alert"), show_alert=True)
        
        success_text = get_text(user_id, "wallet_purchase_success_card").format(
            title=clean_title,
            price=price,
            bal=new_balance
        )
        
        access_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text(user_id, "btn_get_files_unlocked"), url=delivery_link)]
        ])
        
        await callback_query.message.edit_text(success_text, reply_markup=access_btn)

    except Exception as e:
        print(f"Error in process_wallet_payment: {e}")
        await callback_query.answer("❌ Error processing wallet payment!", show_alert=True)

# 8. Search Prompt Handler
@Client.on_message(filters.regex("^(🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ|🔎 Search Story|🔎 कहानी खोजें)$") & filters.private)
async def search_prompt(client, message):
    user_id = message.from_user.id
    SEARCH_WAITING[user_id] = True
    
    await message.reply_text(
        get_text(user_id, "search_prompt_msg"),
        reply_markup=ForceReply(selective=True, placeholder=get_text(user_id, "search_placeholder")),
        quote=True
    )

# 9. Enhanced Fuzzy Search Process
@Client.on_message(
    filters.private 
    & filters.text 
    & ~filters.command(["start", "addstory", "deletestory", "allstories", "cancel", "addmoney"]) 
    & ~filters.regex(MENU_BUTTON_REGEX)
    & ~filters.regex("^📖 "),
    group=2
)
async def process_search(client, message):
    user_id = message.from_user.id
    
    if user_id not in SEARCH_WAITING:
        message.continue_propagation()
        return

    query = message.text.strip()
    SEARCH_WAITING.pop(user_id, None)
    
    # Fetch all stories for Fuzzy Matching
    all_stories = await get_all_stories()
    matched_stories = []
    
    if all_stories:
        title_map = {s['title'].strip().splitlines()[0]: s for s in all_stories}
        story_titles = list(title_map.keys())
        
        # Fuzzy Match using difflib
        close_matches = difflib.get_close_matches(query, story_titles, n=15, cutoff=0.35)
        
        if close_matches:
            matched_stories = [title_map[t] for t in close_matches]
            
    # Fallback to Database Substring Search
    if not matched_stories:
        db_stories, _ = await search_stories_db(query, page=1, limit=50)
        matched_stories = db_stories or []
    
    main_menu_kb = get_main_menu(user_id)
    if not matched_stories:
        no_found_txt = get_text(user_id, "no_story_found_err").format(query=query)
        return await message.reply_text(no_found_txt, reply_markup=main_menu_kb, quote=True)
        
    keyboard_buttons = [[KeyboardButton(f"📖 {s['title'].strip().splitlines()[0]}")] for s in matched_stories]
    keyboard_buttons.append([KeyboardButton(get_text(user_id, "btn_back_main_menu"))])
    
    search_keyboard = ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True)
    found_txt = get_text(user_id, "found_stories_title").format(query=query)
    await message.reply_text(found_txt, reply_markup=search_keyboard, quote=True)
