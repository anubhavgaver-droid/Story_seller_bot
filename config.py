import os

API_ID = int(os.environ.get("API_ID", "1234567"))
API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "987654321"))
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "-1001234567890"))

# Helper Function: कॉमा (,) से सेपरेटेड IDs को Int List में कन्वर्ट करने के लिए
def parse_channel_ids(env_val, default_val=""):
    raw_ids = os.environ.get(env_val, default_val)
    ids = []
    for x in str(raw_ids).split(","):
        x = x.strip()
        if x.replace("-", "").isdigit():
            ids.append(int(x))
    return ids

# Database Channel Variable (अब इसमें मल्टीपल चैनल्स डाल सकते हैं: "-100111,-100222")
CHANNEL_ID = parse_channel_ids("CHANNEL_ID", "-1003970824423, -1003986144843")

# Category / Platform-wise Posting Channels (इनमें भी मल्टीपल चैनल्स सपोर्टेड हैं)
POCKET_FM_CHANNEL = parse_channel_ids("POCKET_FM_CHANNEL", "-1003525105249")
PRATILIPI_FM_CHANNEL = parse_channel_ids("PRATILIPI_FM_CHANNEL", "-1003226074080")

# Default / Fallback Channel
CHANNEL = parse_channel_ids("CHANNEL", "-1003226074080")

UPI_ID = os.environ.get("UPI_ID", "paytm.s417pfl@pty")
PORT = int(os.environ.get("PORT", "8080"))
BOT_USERNAME = os.environ.get("BOT_USERNAME", "YourStorySellerBot")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")

WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://story-seller-bot-0jtb.onrender.com")

# Auto-Post Tutorial Button Link
TUTORIAL_VIDEO_URL = os.environ.get("TUTORIAL_VIDEO_URL", "https://t.me/howanubhav/23")

# Stickers Config
DELIVERY_STICKER_ID = os.environ.get("DELIVERY_STICKER_ID", "CAACAgUAAxkBAAIekGqafK19rMDCkWo-XnCakyhwR7iEAAJaBAAC-qSxV4gJ0UQKykTsHgQ...")
SEARCH_RANGE_STICKER_ID = os.environ.get("SEARCH_RANGE_STICKER_ID", "")

CREATE_ORDER_URL = "https://demotry.shop/api/create-order"
CHECK_STATUS_URL = "https://demotry.shop/api/check-status"

# 🔑 API Credentials
API_KEY_VALUE = os.environ.get("API_KEY_VALUE", "")
API_SECRET_VALUE = os.environ.get("API_SECRET_VALUE", "")
