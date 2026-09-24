import os

API_ID = int(os.environ.get("API_ID", "1234567"))
API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "987654321"))
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "-1001234567890"))

# Database Channel Variable (जहाँ से फाइल्स PM में फॉरवर्ड होंगी)
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-1003970824423"))

# Category / Platform-wise Posting Channels
POCKET_FM_CHANNEL = int(os.environ.get("POCKET_FM_CHANNEL", "-1003525105249"))
PRATILIPI_FM_CHANNEL = int(os.environ.get("PRATILIPI_FM_CHANNEL", "-1003226074080"))

# Default / Fallback Channel
CHANNEL = int(os.environ.get("CHANNEL", "-1003226074080"))

UPI_ID = os.environ.get("UPI_ID", "anubhavcm@axl")
PORT = int(os.environ.get("PORT", "8080"))
BOT_USERNAME = os.environ.get("BOT_USERNAME", "YourStorySellerBot")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")

WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://story-seller-bot-0jtb.onrender.com")

# Auto-Post Tutorial Button Link
TUTORIAL_VIDEO_URL = os.environ.get("TUTORIAL_VIDEO_URL", "https://t.me/howanubhav/23")

# Gmail IMAP Configuration (Automatic Payment Verification)
GMAIL_USER = os.environ.get("GMAIL_USER", "81jokeryt@gmail.com") # Apni Gmail ID
GMAIL_PASS = os.environ.get("GMAIL_PASS", "abcdefghijklmnop") # 16-Digit App Password (Bina space ke)

# Stickers Config
DELIVERY_STICKER_ID = os.environ.get("DELIVERY_STICKER_ID", "CAACAgUAAxkBAAIekGqafK19rMDCkWo-XnCakyhwR7iEAAJaBAAC-qSxV4gJ0UQKykTsHgQ...")
SEARCH_RANGE_STICKER_ID = os.environ.get("SEARCH_RANGE_STICKER_ID", "")
