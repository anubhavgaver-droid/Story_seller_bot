from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL, LOG_CHANNEL

client = AsyncIOMotorClient(MONGO_URL)
db = client["story_seller_db"]
stories_col = db["stories"]
users_col = db["users"]  # New Collection for User Registration
purchases_col = db["purchases"]  # New Collection for Purchased Stories

# -------------------- LOG HELPER FUNCTION --------------------
async def send_log(client_bot, text: str):
    """Log Channel में मैसेज भेजने के लिए Helper फ़ंक्शन"""
    if LOG_CHANNEL and LOG_CHANNEL != 0:
        try:
            await client_bot.send_message(chat_id=LOG_CHANNEL, text=text)
        except Exception as e:
            print(f"Log Error: {e}")

# -------------------- USER REGISTRATION FUNCTIONS --------------------
async def is_user_registered(user_id: int) -> bool:
    """चेक करेगा कि यूज़र पहले से रजिस्टर्ड है या नहीं (Returns True or False)"""
    user = await users_col.find_one({"user_id": user_id})
    if user:
        return user.get("is_registered", False)
    return False

async def register_user(user_id: int, first_name: str, username: str = None):
    """नए यूज़र को रजिस्टर करेगा और status True सेट करेगा"""
    await users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "first_name": first_name,
                "username": username,
                "is_registered": True
            }
        },
        upsert=True
    )

# -------------------- USER PURCHASES FUNCTIONS --------------------
async def add_user_purchase(user_id: int, story_title: str):
    """ऑटो-पेमेंट कन्फर्म होने पर यूज़र की खरीदी गई स्टोरी डेटाबेस में सेव करेगा"""
    await purchases_col.update_one(
        {"user_id": user_id, "story_title": story_title},
        {"$set": {"user_id": user_id, "story_title": story_title}},
        upsert=True
    )

async def get_user_purchases(user_id: int):
    """यूज़र की खरीदी हुई सभी स्टोरीज़ की लिस्ट निकालने के लिए फ़ंक्शन"""
    cursor = purchases_col.find({"user_id": user_id})
    return await cursor.to_list(length=None)

# -------------------- STORY DATABASE FUNCTIONS --------------------
async def add_story_db(data):
    await stories_col.insert_one(data)

async def delete_story_db(title: str) -> bool:
    """स्टोरी डिलीट करने के लिए फ़ंक्शन"""
    res = await stories_col.delete_one({"title": title})
    return res.deleted_count > 0

async def get_all_stories():
    """सभी स्टोरीज़ की लिस्ट निकालने के लिए फ़ंक्शन"""
    cursor = stories_col.find({})
    return await cursor.to_list(length=None)

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
