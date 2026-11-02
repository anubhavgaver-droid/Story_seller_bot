import os

API_ID = int(os.environ.get("API_ID", "1234567"))
API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "987654321"))
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "-1001234567890"))

def _id_list(raw: str):
    """'-100111, -100222' (comma / space se alag) -> [-100111, -100222]. Galat entries chhod deta hai."""
    out = []
    for part in str(raw or "").replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            val = int(part)
        except ValueError:
            continue
        if val not in out:
            out.append(val)
    return out


# DB (database) channel(s). CHANNEL_ID me EK ya KAI ID (comma se) de sakte hain; pehli ID "primary" hai
# (purani stories isi se chalti hain). Alag se DB_CHANNELS variable bhi chalta hai. Dono me se kuch bhi use karein.
_primary = _id_list(os.environ.get("CHANNEL_ID", "-1003970824423,-1003523854665")) or [-1003970824423]
CHANNEL_ID = _primary[0]


def _parse_db_channels():
    ids = list(_primary)
    for val in _id_list(os.environ.get("DB_CHANNELS", "")):
        if val not in ids:
            ids.append(val)
    return ids


DB_CHANNEL_IDS = _parse_db_channels()

# Category / Platform-wise Posting Channels
POCKET_FM_CHANNEL = int(os.environ.get("POCKET_FM_CHANNEL", "-1003525105249"))
PRATILIPI_FM_CHANNEL = int(os.environ.get("PRATILIPI_FM_CHANNEL", "-1003226074080"))

CHANNEL = int(os.environ.get("CHANNEL", "-1003226074080"))


UPI_ID = os.environ.get("UPI_ID", "BHARATPE2L0U0G8F4J64101@unitype")
PORT = int(os.environ.get("PORT", "8080"))
BOT_USERNAME = os.environ.get("BOT_USERNAME", "YourStorySellerBot")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")

WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://story-seller-bot-0jtb.onrender.com")

# Gateway server-to-server webhook (main.py me /paytm route). Gateway dashboard me bhi yahi URL rakhein.
PAYMENT_CALLBACK_URL = os.environ.get("PAYMENT_CALLBACK_URL", WEB_APP_URL.rstrip("/") + "/paytm")

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
