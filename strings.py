from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.db import get_user_lang_db

USER_LANG = {}

STRINGS = {
    "en": {
        # --- UI & NAVIGATION BUTTONS ---
        "btn_miniapp": "🚀 ᴏᴘᴇɴ ᴍɪɴɪ ᴀᴘᴘ",
        "btn_launch_miniapp": "🚀 ʟᴀᴜɴᴄʜ ᴍɪɴɪ ᴀᴘᴘ",
        "btn_wallet": "💼 ᴍʏ ᴡᴀʟʟᴇᴛ",
        "btn_account": "👤 ᴍʏ ᴀᴄᴄᴏᴜɴᴛ",
        "btn_search": "🔎 sᴇᴀʀᴄʜ sᴛᴏʀʏ",
        "btn_pocket": "📻 ᴘᴏᴄᴋᴇᴛ ғᴍ",
        "btn_pratilipi": "📚 ᴘʀᴀᴛɪʟɪᴘɪ ғᴍ",
        "btn_updates": "📢 ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ",
        "btn_support": "📞 sᴜᴘᴘᴏʀᴛ",
        "btn_lang": "🌐 Change Language",
        "btn_back_main_menu": "🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ",
        "btn_cleanchat": "🧹 ᴄʟᴇᴀɴ / ᴅᴇʟᴇᴛᴇ ᴀʟʟ ғɪʟᴇs",

        # --- GENERAL & MAIN MENU ---
        "welcome_msg": "<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n🌟 <b>STORY SELLER BOT</b> 🌟\n<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n\n<b>HELLO {name}! 👋</b>\n\n<b>USE THE BUTTONS BELOW TO SEARCH OR PURCHASE YOUR FAVORITE STORIES.</b>",
        "main_menu_title": "<b>🌟 ᴍᴀɪɴ ᴍᴇɴᴜ:</b>",
        "choose_language": "<b>Choose your preferred language / अपनी भाषा चुनें:</b>",
        "lang_saved_msg": "✅ <b>Language set to English!</b>",
        "lang_updated_alert": "Language updated to English!",
        "mini_app_desc": "🚀 <b>ᴍɪɴɪ sᴛᴏʀᴇ ᴀᴘᴘ</b>\n\nClick the button below to open our official mini app and explore all stories!",

        # --- WALLET SYSTEM ---
        "wallet_details_card": "<b>👛 ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ ᴅᴇᴛᴀɪʟs</b>\n━━━━━━━━━━━━━━━━━━━\n<b>💳 ᴄᴜʀʀᴇɴᴛ ʙᴀʟᴀɴᴄᴇ:</b> ₹{bal}\n━━━━━━━━━━━━━━━━━━━\n\n💡 <i>Use wallet balance for 1-click instant purchases inside Mini App or Bot.</i>",
        "btn_add_wallet_funds": "➕ ᴀᴅᴅ ᴍᴏɴᴇʏ / ᴛᴏᴘ-ᴜᴘ",
        "enter_topup_amount_prompt": "💵 <b>ᴇɴᴛᴇʀ ᴛᴏᴘ-ᴜᴘ ᴀᴍᴏᴜɴᴛ:</b>\n\nPlease type the amount (in ₹) you want to add to your wallet:",
        "invalid_amount_msg": "❌ <b>Invalid Amount! Please enter numbers only (e.g. 50, 100, 200).</b>",
        "wallet_topup_qr_caption": "👛 <b>ᴡᴀʟʟᴇᴛ ᴛᴏᴘ-ᴜᴘ:</b> ₹{price}\n💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{price}\n\n📌 <b>ᴜᴘɪ ɪᴅ:</b> <code>{upi_id}</code>\n\n👇 <i>After making payment, click on Confirm Payment below.</i>",
        "admin_wallet_credited_notify": "🎉 <b>ᴡᴀʟʟᴇᴛ ᴄʀᴇᴅɪᴛᴇᴅ!</b>\n\n💰 <b>ᴀᴍᴏᴜɴᴛ ᴀᴅᴅᴇᴅ/ᴅᴇᴅᴜᴄᴛᴇᴅ:</b> ₹{amount}\n👛 <b>Total ʙᴀʟᴀɴᴄᴇ:</b> ₹{bal}\n\n<i>Now you can buy any story using your wallet in Mini App or Bot!</i>",
        "wallet_approved_user_msg": "🎉 <b>ᴡᴀʟʟᴇᴛ ᴛᴏᴘ-ᴜᴘ ᴀᴘᴘʀᴏᴠᴇᴅ!</b>\n\n💰 <b>ᴀᴅᴅᴇᴅ:</b> ₹{price}\n👛 <b>ɴᴇᴡ ʙᴀʟᴀɴᴄᴇ:</b> ₹{bal}\n\n<i>Now you can purchase stories using your wallet!</i>",

        # --- PAYMENT & CHECKOUT ---
        "btn_confirm_payment": "✅ ᴄᴏɴғɪʀᴍ ᴘᴀʏᴍᴇɴᴛ",
        "btn_direct_pay": "💳 ᴅɪʀᴇᴄᴛ ᴘᴀʏ (₹{price})",
        "btn_wallet_pay": "👛 ᴘᴀʏ ᴠɪᴀ ᴡᴀʟʟᴇᴛ (Bal: ₹{bal})",
        "btn_pay_via_wallet": "👛 ᴘᴀʏ ᴠɪᴀ ᴡᴀʟʟᴇᴛ (Bal: ₹{bal})",
        "qr_checkout_caption": "💳 <b>ᴏʀᴅᴇʀ ᴄʜᴇᴄᴋᴏᴜᴛ:</b> {title}\n💰 <b>ᴀᴍᴏᴜɴᴛ:</b> ₹{price}\n\n📌 <b>ᴜᴘɪ ɪᴅ:</b> <code>{upi_id}</code>\n\n👇 <i>After making payment, click on Confirm Payment below.</i>",
        "send_screenshot_prompt": "📸 <b>ᴘʟᴇᴀsᴇ sᴇɴᴅ ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ sᴄʀᴇᴇɴsʜᴏᴛ:</b>\n\nSend your screenshot as a photo in this chat.",
        "screenshot_received_msg": "✅ <b>sᴄʀᴇᴇɴsʜᴏᴛ ʀᴇᴄᴇɪᴠᴇᴅ!</b>\nYour payment is under verification by admin.",
        "order_initiated_card": "🛒 <b>ᴏʀᴅᴇʀ ɪɴɪᴛɪᴀᴛᴇᴅ ғʀᴏᴍ ᴍɪɴɪ ᴀᴘᴘ</b>\n\n📖 <b>ᴛɪᴛʟᴇ:</b> {title}\n💰 <b>ᴘʀɪᴄᴇ:</b> ₹{price}\n👛 <b>ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ:</b> ₹{bal}\n📝 <b>ᴅᴇsᴄ:</b> {desc}\n\n👇 <b>Select payment method to complete purchase:</b>",
        "direct_purchase_approved_user_msg": "🎉 <b>ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ʜᴀs ʙᴇᴇɴ ᴀᴘᴘʀᴏᴠᴇᴅ!</b>\n\n📖 <b>sᴛᴏʀʏ:</b> {title}\n\nClick the button below to access your content:",
        "payment_rejected_user_msg": "❌ <b>ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ʜᴀs ʙᴇᴇɴ ʀᴇᴊᴇᴄᴛᴇᴅ!</b>\n\n📌 <b>ITEM:</b> {item}\n\nIf you believe this is a mistake, please contact support.",
        "purchase_success_msg": "✅ <b>ᴘᴜʀᴄʜᴀsᴇ sᴜᴄᴄᴇssғᴜʟ!</b>\n\n📖 <b>sᴛᴏʀʏ:</b> {title}\n💸 <b>ᴅᴇᴅᴜᴄᴛᴇᴅ:</b> ₹{price}\n👛 <b>ʀᴇᴍᴀɪɴɪɴɢ ʙᴀʟᴀɴᴄᴇ:</b> ₹{bal}\n\n👇 Click below to access your story files:",
        "wallet_purchase_success_card": "✅ <b>ᴘᴜʀᴄʜᴀsᴇ sᴜᴄᴄᴇssғᴜʟ!</b>\n\n📖 <b>sᴛᴏʀʏ:</b> {title}\n💸 <b>ᴅᴇᴅᴜᴄᴛᴇᴅ:</b> ₹{price}\n👛 <b>ʀᴇᴍᴀɪɴɪɴɢ ʙᴀʟᴀɴᴄᴇ:</b> ₹{bal}\n\n👇 Click below to access your story:",
        "purchase_success_alert": "🎉 Purchase successful! Story unlocked.",
        "insufficient_balance_alert": "❌ Insufficient Balance!\nRequired: ₹{price}\nAvailable: ₹{bal}\n\nPlease top-up your wallet.",

        # --- STORY DETAILS & CATEGORIES ---
        "story_details_card": "📖 <b>ᴛɪᴛʟᴇ:</b> {title}\n💰 <b>ᴘʀɪᴄᴇ:</b> ₹{price}\n👛 <b>ʏᴏᴜʀ ᴡᴀʟʟᴇᴛ:</b> ₹{bal}\n📝 <b>ᴅᴇsᴄ:</b> {desc}\n\n<i>👇 Choose an option below to view or purchase:</i>",
        "no_stories_in_cat": "❌ <b>No stories available in {cat}.</b>",
        "available_stories_cat_title": "<b>📚 Available Stories ({cat}):</b>\n\nSelect your story for details:",
        "story_not_available_err": "❌ <b>This story is not available.</b>",
        "story_not_found": "❌ <b>sᴛᴏʀʏ ɴᴏᴛ ғᴏᴜɴᴅ.</b>",
        "no_desc": "ɴᴏ ᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴀᴠᴀɪʟᴀʙʟᴇ.",

        # --- DEMO / PREVIEW SYSTEM ---
        "btn_demo": "🎬 ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ",
        "btn_demo_preview": "🎬 ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ",
        "demo_not_available": "⚠️ Demo is not available for this story!",
        "demo_not_available_alert": "⚠️ Demo is not available for this story!",
        "no_demo_files": "❌ No Demo files available!",
        "no_demo_files_alert": "❌ No Demo files available!",
        "sending_demo_alert": "🎬 Sending Demo files... Please check your chat!",
        "demo_header": "🎬 <b>ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ ғᴏʀ:</b> <code>{title}</code>\n\n⏰ <i>This demo preview will automatically delete in 10 minutes!</i>",
        "demo_header_msg": "🎬 <b>ᴅᴇᴍᴏ / ᴘʀᴇᴠɪᴇᴡ ғᴏʀ:</b> <code>{title}</code>\n\n⏰ <i>This demo preview will automatically delete in 10 minutes!</i>",

        # --- FILE DELIVERY & CLEANUP ---
        "btn_get_files_unlocked": "📂 ɢᴇᴛ ғɪʟᴇs (Unlocked)",
        "fetching_files": "⏳ <b>ғᴇᴛᴄʜɪɴɢ ғɪʟᴇs {range_text}...</b>\n<i>ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...</i>",
        "files_delivered": "🎉 <b>ғɪʟᴇs ᴅᴇʟɪᴠᴇʀᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b> {range_text}\n\n📖 <b>sᴛᴏʀʏ:</b> {title}\n📦 <b>ᴅᴇʟɪᴠᴇʀᴇᴅ:</b> {success} / {total} Files\n\n👇 <i>Click button below to clean chat after listening:</i>",

        # --- SEARCH MODULE ---
        "search_prompt_msg": "<b>ɴᴏᴡ ʏᴏᴜ ᴄᴀɴ sᴇᴀʀᴄʜ ʏᴏᴜʀ sᴛᴏʀʏ!</b> 🔍\n\nType and send the story name:\n<i>(Even if spelling is slightly wrong, bot will find the correct result)</i>",
        "search_placeholder": "ᴛʏᴘᴇ sᴛᴏʀʏ ɴᴀᴍᴇ ʜᴇʀᴇ...",
        "no_story_found_err": "❌ <b>No story found with name '{query}'!</b>",
        "found_stories_title": "🔍 <b>Found stories matching '{query}':</b>"
    },

    "hi": {
        # --- UI & NAVIGATION BUTTONS ---
        "btn_miniapp": "🚀 मिनी ऐप खोलें",
        "btn_launch_miniapp": "🚀 मिनी ऐप खोलें",
        "btn_wallet": "💼 मेरा वॉलेट",
        "btn_account": "👤 मेरा खाता",
        "btn_search": "🔎 स्टोरी खोजें",
        "btn_pocket": "📻 पॉकेट एफएम",
        "btn_pratilipi": "📚 प्रतिलिपि एफएम",
        "btn_updates": "📢 अपडेट्स चैनल",
        "btn_support": "📞 सहायता",
        "btn_lang": "🌐 भाषा बदलें",
        "btn_back_main_menu": "🔙 मुख्य मेनू",
        "btn_cleanchat": "🧹 चैट साफ़ करें / डिलीट करें",

        # --- GENERAL & MAIN MENU ---
        "welcome_msg": "<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n🌟 <b>स्टोरी सेलर बॉट</b> 🌟\n<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n\n<b>नमस्ते {name}! 👋</b>\n\n<b>अपनी पसंदीदा कहानियां खोजने या खरीदने के लिए नीचे दिए गए बटनों का उपयोग करें।</b>",
        "main_menu_title": "<b>🌟 मुख्य मेनू:</b>",
        "choose_language": "<b>अपनी पसंदीदा भाषा चुनें / Choose your preferred language:</b>",
        "lang_saved_msg": "✅ <b>भाषा हिंदी सेट हो गई है!</b>",
        "lang_updated_alert": "भाषा हिंदी में बदल दी गई है!",
        "mini_app_desc": "🚀 <b>मिनी स्टोर ऐप</b>\n\nहमारे आधिकारिक मिनी ऐप को खोलने और सभी कहानियों को देखने के लिए नीचे दिए गए बटन पर क्लिक करें!",

        # --- WALLET SYSTEM ---
        "wallet_details_card": "<b>👛 आपके वॉलेट का विवरण</b>\n━━━━━━━━━━━━━━━━━━━\n<b>💳 वर्तमान बैलेंस:</b> ₹{bal}\n━━━━━━━━━━━━━━━━━━━\n\n💡 <i>मिनी ऐप या बॉट के अंदर 1-क्लिक में तुरंत खरीदारी के लिए वॉलेट बैलेंस का उपयोग करें।</i>",
        "btn_add_wallet_funds": "➕ पैसे जोड़ें / टॉप-अप",
        "enter_topup_amount_prompt": "💵 <b>टॉप-अप राशि दर्ज करें:</b>\n\nकृपया वह राशि (₹ में) लिखें जो आप अपने वॉलेट में जोड़ना चाहते हैं:",
        "invalid_amount_msg": "❌ <b>अमान्य राशि! कृपया केवल संख्याएं दर्ज करें (उदा. 50, 100, 200)।</b>",
        "wallet_topup_qr_caption": "👛 <b>वॉलेट टॉप-अप:</b> ₹{price}\n💰 <b>राशि:</b> ₹{price}\n\n📌 <b>यूपीआई आईडी:</b> <code>{upi_id}</code>\n\n👇 <i>भुगतान करने के बाद नीचे 'भुगतान की पुष्टि करें' पर क्लिक करें।</i>",
        "admin_wallet_credited_notify": "🎉 <b>वॉलेट क्रेडिट हुआ!</b>\n\n💰 <b>जोड़ी गई/काटी गई राशि:</b> ₹{amount}\n👛 <b>कुल बैलेंस:</b> ₹{bal}\n\n<i>अब आप मिनी ऐप या बॉट में अपने वॉलेट का उपयोग करके कोई भी कहानी खरीद सकते हैं!</i>",
        "wallet_approved_user_msg": "🎉 <b>वॉलेट टॉप-अप स्वीकृत!</b>\n\n💰 <b>जोड़ा गया:</b> ₹{price}\n👛 <b>नया बैलेंस:</b> ₹{bal}\n\n<i>अब आप अपने वॉलेट का उपयोग करके कहानियां खरीद सकते हैं!</i>",

        # --- PAYMENT & CHECKOUT ---
        "btn_confirm_payment": "✅ भुगतान की पुष्टि करें",
        "btn_direct_pay": "💳 सीधा भुगतान (₹{price})",
        "btn_wallet_pay": "👛 वॉलेट से भुगतान (शेष: ₹{bal})",
        "btn_pay_via_wallet": "👛 वॉलेट से भुगतान (बैलेंस: ₹{bal})",
        "qr_checkout_caption": "💳 <b>ऑर्डर चेकआउट:</b> {title}\n💰 <b>राशि:</b> ₹{price}\n\n📌 <b>यूपीआई आईडी:</b> <code>{upi_id}</code>\n\n👇 <i>भुगतान करने के बाद नीचे 'भुगतान की पुष्टि करें' पर क्लिक करें।</i>",
        "send_screenshot_prompt": "📸 <b>कृपया अपने भुगतान का स्क्रीनशॉट भेजें:</b>\n\nइस चैट में एक फोटो के रूप में अपना स्क्रीनशॉट भेजें।",
        "screenshot_received_msg": "✅ <b>स्क्रीनशॉट प्राप्त हुआ!</b>\nआपका भुगतान एडमिन द्वारा सत्यापन के अधीन है।",
        "order_initiated_card": "🛒 <b>मिनी ऐप से ऑर्डर शुरू किया गया</b>\n\n📖 <b>शीर्षक:</b> {title}\n💰 <b>कीमत:</b> ₹{price}\n👛 <b>आपका वॉलेट:</b> ₹{bal}\n📝 <b>विवरण:</b> {desc}\n\n👇 <b>खरीद पूरी करने के लिए भुगतान विधि चुनें:</b>",
        "direct_purchase_approved_user_msg": "🎉 <b>आपका भुगतान स्वीकृत हो गया है!</b>\n\n📖 <b>स्टोरी:</b> {title}\n\nअपनी सामग्री तक पहुँचने के लिए नीचे दिए गए बटन पर क्लिक करें:",
        "payment_rejected_user_msg": "❌ <b>आपका भुगतान अस्वीकृत कर दिया गया है!</b>\n\n📌 <b>वस्तु:</b> {item}\n\nयदि आपको लगता है कि यह कोई गलती है, तो कृपया सहायता टीम से संपर्क करें।",
        "purchase_success_msg": "✅ <b>खरीद सफ़ल रही!</b>\n\n📖 <b>स्टोरी:</b> {title}\n💸 <b>काटे गए पैसे:</b> ₹{price}\n👛 <b>शेष वॉलेट बैलेंस:</b> ₹{bal}\n\n👇 अपनी स्टोरी फाइलों तक पहुँचने के लिए नीचे क्लिक करें:",
        "wallet_purchase_success_card": "✅ <b>खरीदारी सफल!</b>\n\n📖 <b>कहानी:</b> {title}\n💸 <b>कटौती:</b> ₹{price}\n👛 <b>शेष बैलेंस:</b> ₹{bal}\n\n👇 अपनी सामग्री तक पहुँचने के लिए नीचे क्लिक करें:",
        "purchase_success_alert": "🎉 खरीद सफल रही! स्टोरी अनलॉक हो गई है।",
        "insufficient_balance_alert": "❌ अपर्याप्त बैलेंस!\nआवश्यक: ₹{price}\nउपलब्ध: ₹{bal}\n\nकृपया अपना वॉलेट रीचार्ज करें।",

        # --- STORY DETAILS & CATEGORIES ---
        "story_details_card": "📖 <b>शीर्षक:</b> {title}\n💰 <b>कीमत:</b> ₹{price}\n👛 <b>आपका वॉलेट:</b> ₹{bal}\n📝 <b>विवरण:</b> {desc}\n\n<i>👇 देखने या खरीदने के लिए नीचे दिए गए विकल्प को चुनें:</i>",
        "no_stories_in_cat": "❌ <b>{cat} में कोई कहानी उपलब्ध नहीं है।</b>",
        "available_stories_cat_title": "<b>📚 उपलब्ध कहानियां ({cat}):</b>\n\nविवरण के लिए अपनी कहानी चुनें:",
        "story_not_available_err": "❌ <b>यह कहानी उपलब्ध नहीं है।</b>",
        "story_not_found": "❌ <b>स्टोरी नहीं मिली।</b>",
        "no_desc": "कोई विवरण उपलब्ध नहीं है।",

        # --- DEMO / PREVIEW SYSTEM ---
        "btn_demo": "🎬 डेमो / झलक देखें",
        "btn_demo_preview": "🎬 डेमो / पूर्वावलोकन",
        "demo_not_available": "⚠️ इस स्टोरी के लिए डेमो उपलब्ध नहीं है!",
        "demo_not_available_alert": "⚠️ इस कहानी के लिए डेमो उपलब्ध नहीं है!",
        "no_demo_files": "❌ कोई डेमो फाइलें उपलब्ध नहीं हैं!",
        "no_demo_files_alert": "❌ कोई डेमो फाइल उपलब्ध नहीं है!",
        "sending_demo_alert": "🎬 डेमो फाइलें भेजी जा रही हैं... कृपया अपनी चैट देखें!",
        "demo_header": "🎬 <b>डेमो / झलक:</b> <code>{title}</code>\n\n⏰ <i>यह डेमो 10 मिनट में अपने आप डिलीट हो जाएगा!</i>",
        "demo_header_msg": "🎬 <b>डेमो / पूर्वावलोकन:</b> <code>{title}</code>\n\n⏰ <i>यह डेमो पूर्वावलोकन 10 मिनट में स्वतः हटा दिया जाएगा!</i>",

        # --- FILE DELIVERY & CLEANUP ---
        "btn_get_files_unlocked": "📂 फाइलें प्राप्त करें (अनलॉक)",
        "fetching_files": "⏳ <b>फाइलें लाई जा रही हैं {range_text}...</b>\n<i>कृपया प्रतीक्षा करें...</i>",
        "files_delivered": "🎉 <b>फाइलें सफलतापूर्वक भेज दी गईं!</b> {range_text}\n\n📖 <b>स्टोरी:</b> {title}\n📦 <b>भेजी गईं:</b> {success} / {total} फाइलें\n\n👇 <i>सुनने के बाद चैट साफ़ करने के लिए नीचे बटन पर क्लिक करें:</i>",

        # --- SEARCH MODULE ---
        "search_prompt_msg": "<b>अब आप अपनी कहानी खोज सकते हैं!</b> 🔍\n\nकहानी का नाम लिखकर भेजें:\n<i>(वर्तनी/स्पेलिंग थोड़ी गलत होने पर भी बॉट सही परिणाम ढूंढ लेगा)</i>",
        "search_placeholder": "यहाँ कहानी का नाम लिखें...",
        "no_story_found_err": "❌ <b>'{query}' नाम से कोई कहानी नहीं मिली!</b>",
        "found_stories_title": "🔍 <b>'{query}' से मेल खाती कहानियां मिलीं:</b>"
    }
}

def get_text(user_id: int, key: str) -> str:
    """यूजर की चुनी हुई भाषा के अनुसार टेक्स्ट रिटर्न करता है।"""
    lang = USER_LANG.get(user_id, "en")
    return STRINGS.get(lang, STRINGS["en"]).get(key, key)

async def get_main_menu(user_id: int):
    """यूज़र की भाषा के अनुसार Dynamic Inline Keyboard बनाएगा (Fixes NameError)"""
    lang = USER_LANG.get(user_id)
    if not lang:
        lang = await get_user_lang_db(user_id)
        USER_LANG[user_id] = lang

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(get_text(user_id, "btn_pocket"), callback_data="cat_pocket"),
            InlineKeyboardButton(get_text(user_id, "btn_pratilipi"), callback_data="cat_pratilipi")
        ],
        [
            InlineKeyboardButton(get_text(user_id, "btn_search"), callback_data="search_story"),
            InlineKeyboardButton(get_text(user_id, "btn_wallet"), callback_data="my_wallet")
        ],
        [
            InlineKeyboardButton(get_text(user_id, "btn_lang"), callback_data="change_lang"),
            InlineKeyboardButton(get_text(user_id, "btn_support"), callback_data="support_info")
        ]
    ])
