from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from db import get_user_lang_db

# Store user session languages in memory for quick access
USER_LANG = {}

LANG = {
    "en": {
        # --- Common & General ---
        "welcome": "Welcome {name}! 👋\n\nChoose an option from the menu below:",
        "choose_lang": "🌐 **Select your preferred language:**",
        "lang_changed": "✅ Language updated to **English**!",
        "back_btn": "🔙 Back",
        "close_btn": "❌ Close",
        "next_btn": "Next ➡️",
        "prev_btn": "⬅️ Prev",
        "btn_pocket": "📻 Pocket FM",
        "btn_pratilipi": "📚 Pratilipi FM",
        "btn_search": "🔎 Search Story",
        "btn_wallet": "💼 My Wallet",
        "btn_lang": "🌐 Change Language",
        "btn_support": "📞 Support",
        
        # --- User Registration & Main Menu ---
        "must_register": "⚠️ You need to register first before using the bot.",
        "reg_success": "✅ Registration successful! Welcome, {name}.",
        "already_registered": "ℹ️ You are already registered.",
        
        # --- Wallet System ---
        "wallet_title": "💳 **Your Wallet**\n\n👤 **User:** {name}\n💰 **Balance:** ₹{balance}",
        "add_funds_btn": "➕ Add Funds",
        "insufficient_balance": "⚠️ **Insufficient Balance!**\n\nYour Balance: ₹{balance}\nRequired: ₹{price}\n\nPlease add funds to your wallet to purchase this story.",
        
        # --- Story & Purchasing ---
        "story_details": "📚 **{title}**\n\n📁 **Category:** {category}\n💵 **Price:** ₹{price}\n\n📝 **Description:**\n{desc}",
        "buy_now_btn": "💳 Buy Now (₹{price})",
        "demo_btn": "👁️ Read Demo",
        "already_bought": "✅ You already own this story!",
        "purchase_success": "🎉 **Purchase Successful!**\n\nYou bought: **{title}**\nRemaining Balance: ₹{balance}\n\nClick below to read your story:",
        "read_story_btn": "📖 Read Story",
        "no_demo": "❌ Demo is not available for this story.",
        
        # --- Search & Categories ---
        "search_prompt": "🔍 Send me the name or keyword of the story you want to search:",
        "no_results": "❌ No stories found matching your query.",
        "search_results": "🔎 **Search Results for:** `{query}`",
        
        # --- Errors ---
        "error_generic": "❌ Something went wrong. Please try again later.",
        "story_not_found": "❌ Story not found."
    },
    
    "hi": {
        # --- Common & General ---
        "welcome": "स्वागत है {name}! 👋\n\nनीचे दिए गए मेनू से एक विकल्प चुनें:",
        "choose_lang": "🌐 **अपनी पसंदीदा भाषा चुनें:**",
        "lang_changed": "✅ भाषा बदलकर **हिंदी** कर दी गई है!",
        "back_btn": "🔙 पीछे जाएँ",
        "close_btn": "❌ बंद करें",
        "next_btn": "आगे ➡️",
        "prev_btn": "⬅️ पीछे",
        "btn_pocket": "📻 पॉकेट एफएम",
        "btn_pratilipi": "📚 प्रतिलिपि एफएम",
        "btn_search": "🔎 स्टोरी खोजें",
        "btn_wallet": "💼 मेरा वॉलेट",
        "btn_lang": "🌐 भाषा बदलें",
        "btn_support": "📞 सहायता",
        
        # --- User Registration & Main Menu ---
        "must_register": "⚠️ बॉट का उपयोग करने से पहले आपको रजिस्ट्रेशन करना होगा।",
        "reg_success": "✅ रजिस्ट्रेशन सफल रहा! आपका स्वागत है, {name}।",
        "already_registered": "ℹ️ आप पहले से ही रजिस्टर्ड हैं।",
        
        # --- Wallet System ---
        "wallet_title": "💳 **आपका वॉलेट**\n\n👤 **यूज़र:** {name}\n💰 **बैलेंस:** ₹{balance}",
        "add_funds_btn": "➕ बैलेंस जोड़ें",
        "insufficient_balance": "⚠️ **अपर्याप्त बैलेंस!**\n\nआपका बैलेंस: ₹{balance}\nज़रूरी बैलेंस: ₹{price}\n\nकृपया इस कहानी को खरीदने के लिए अपने वॉलेट में पैसे जोड़ें।",
        
        # --- Story & Purchasing ---
        "story_details": "📚 **{title}**\n\n📁 **कैटेगरी:** {category}\n💵 **कीमत:** ₹{price}\n\n📝 **विवरण:**\n{desc}",
        "buy_now_btn": "💳 अभी खरीदें (₹{price})",
        "demo_btn": "👁️ डेमो पढ़ें",
        "already_bought": "✅ आपके पास यह कहानी पहले से मौजूद है!",
        "purchase_success": "🎉 **खरीद सफल रही!**\n\nआपने खरीदा: **{title}**\nबाकी बैलेंस: ₹{balance}\n\nअपनी कहानी पढ़ने के लिए नीचे क्लिक करें:",
        "read_story_btn": "📖 कहानी पढ़ें",
        "no_demo": "❌ इस कहानी के लिए डेमो उपलब्ध नहीं है।",
        
        # --- Search & Categories ---
        "search_prompt": "🔍 आप जो कहानी खोजना चाहते हैं उसका नाम या कीवर्ड भेजें:",
        "no_results": "❌ आपकी खोज से मेल खाती कोई कहानी नहीं मिली।",
        "search_results": "🔎 **खोज के परिणाम:** `{query}`",
        
        # --- Errors ---
        "error_generic": "❌ कुछ गलत हो गया। कृपया बाद में पुनः प्रयास करें।",
        "story_not_found": "❌ कहानी नहीं मिली।"
    }
}

def get_text(user_or_lang, key: str) -> str:
    """
    यूजर ID (int) या भाषा कोड (str) दोनों स्वीकार करता है और सही टेक्स्ट रिटर्न करता है।
    """
    if isinstance(user_or_lang, int):
        lang_code = USER_LANG.get(user_or_lang, "en")
    else:
        lang_code = str(user_or_lang) if user_or_lang in LANG else "en"
        
    user_lang = LANG.get(lang_code, LANG["en"])
    return user_lang.get(key, LANG["en"].get(key, f"[{key}]"))

async def get_main_menu(user_id: int):
    """
    यूज़र के लिए मेनू कीबोर्ड जनरेट करता है। (NameError को फ़िक्स करता है)
    """
    lang_code = USER_LANG.get(user_id)
    if not lang_code:
        lang_code = await get_user_lang_db(user_id)
        USER_LANG[user_id] = lang_code or "en"

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
