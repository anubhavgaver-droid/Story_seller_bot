import os

API_ID = int(os.environ.get("API_ID", "1234567"))
API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "987654321"))
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "-1001234567890"))

# Database Channel Variable (जहाँ से फाइल्स PM में फॉरवर्ड होंगी)
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-1002945761623"))

UPI_ID = os.environ.get("UPI_ID", "63983224472@fam")
PORT = int(os.environ.get("PORT", "8080"))
BOT_USERNAME = os.environ.get("BOT_USERNAME", "YourStorySellerBot")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")

WEB_APP_URL = "https://story-seller-bot-0jtb.onrender.com" # Apni hosted web app ka HTTPS link
