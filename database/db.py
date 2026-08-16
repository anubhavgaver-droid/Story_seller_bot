from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL, LOG_CHANNEL

client = AsyncIOMotorClient(MONGO_URL)
db = client["story_seller_db"]
stories_col = db["stories"]

# -------------------- LOG HELPER FUNCTION --------------------
async def send_log(client_bot, text: str):
    """Log Channel में मैसेज भेजने के लिए Helper फ़ंक्शन"""
    if LOG_CHANNEL and LOG_CHANNEL != 0:
        try:
            await client_bot.send_message(chat_id=LOG_CHANNEL, text=text)
        except Exception as e:
            print(f"Log Error: {e}")

# -------------------- DATABASE FUNCTIONS --------------------
async def add_story_db(data):
    await stories_col.insert_one(data)

async def get_stories_by_cat(category, page=1, limit=10):
    skip = (page - 1) * limit
    cursor = stories_col.find({"category": category}).skip(skip).limit(limit)
    stories = await cursor.to_list(length=limit)
    total = await stories_col.count_documents({"category": category})
    total_pages = (total + limit - 1) // limit if total > 0 else 1
    return stories, total_pages

async def search_stories_db(query, page=1, limit=10):
    skip = (page - 1) * limit
    filter_q = {"$or": [{"title": {"$regex": query, "$options": "i"}}, {"desc": {"$regex": query, "$options": "i"}}]}
    cursor = stories_col.find(filter_q).skip(skip).limit(limit)
    stories = await cursor.to_list(length=limit)
    total = await stories_col.count_documents(filter_q)
    total_pages = (total + limit - 1) // limit if total > 0 else 1
    return stories, total_pages

async def get_story_by_title(title):
    return await stories_col.find_one({"title": title})
