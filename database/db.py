from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument
from config import MONGO_URL, LOG_CHANNEL

client = AsyncIOMotorClient(MONGO_URL)
db = client["story_seller_db"]
stories_col = db["stories"]
users_col = db["users"]        # Collection for User Registration, Wallet & Language
purchases_col = db["purchases"]  # Collection for Purchased Stories

# --- FAST IN-MEMORY CACHE FOR LANGUAGE ---
USER_LANG = {}

# -------------------- HELPER FUNCTIONS --------------------
def clean_title(title: str) -> str:
    """टाइटल की केवल पहली लाइन निकालता है"""
    if not title:
        return ""
    return str(title).strip().split("\n")[0]

async def send_log(client_bot, text: str):
    """Log Channel में मैसेज भेजने के लिए Helper फ़ंक्शन"""
    if LOG_CHANNEL and LOG_CHANNEL != 0:
        try:
            await client_bot.send_message(chat_id=LOG_CHANNEL, text=text)
        except Exception as e:
            print(f"Log Error: {e}")

# -------------------- LANGUAGE DATABASE FUNCTIONS --------------------
async def set_user_lang_db(user_id: int, lang_code: str):
    """यूज़र की चुनी हुई भाषा को Database और Cache दोनों में अपडेट करता है"""
    USER_LANG[user_id] = lang_code
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"language": lang_code}},
        upsert=True
    )

async def get_user_lang_db(user_id: int) -> str:
    """यूज़र की भाषा सबसे पहले Cache से, वरना Database से निकालता है (By Default: 'en')"""
    if user_id in USER_LANG:
        return USER_LANG[user_id]
    
    user = await users_col.find_one({"user_id": user_id})
    lang = user.get("language", "en") if user else "en"
        
    USER_LANG[user_id] = lang
    return lang

# -------------------- USER REGISTRATION FUNCTIONS --------------------
async def is_user_registered(user_id: int) -> bool:
    """चेक करेगा कि यूज़र पहले से रजिस्टर्ड है या नहीं"""
    user = await users_col.find_one({"user_id": user_id})
    if user:
        return user.get("is_registered", False)
    return False

async def register_user(user_id: int, first_name: str, username: str = None):
    """नए यूज़र को रजिस्टर करेगा और Default Wallet Balance (0.0) व Language ('en') सेट करेगा"""
    await users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "first_name": first_name,
                "username": username,
                "is_registered": True
            },
            "$setOnInsert": {
                "wallet_balance": 0.0,
                "language": "en"
            }
        },
        upsert=True
    )

# -------------------- WALLET DATABASE FUNCTIONS --------------------
async def get_user_wallet(user_id: int) -> float:
    """यूज़र का Wallet Balance निकालता है"""
    user = await users_col.find_one({"user_id": user_id})
    if user:
        return float(user.get("wallet_balance", 0.0))
    return 0.0

async def update_user_wallet(user_id: int, new_balance: float):
    """Wallet Balance को direct update करने के लिए"""
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"wallet_balance": round(float(new_balance), 2)}},
        upsert=True
    )

async def add_wallet_balance(user_id: int, amount: float) -> float:
    """Wallet में Balance जोड़ने या घटाने के लिए ($inc)"""
    user = await users_col.find_one_and_update(
        {"user_id": user_id},
        {"$inc": {"wallet_balance": round(float(amount), 2)}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    if user:
        return float(user.get("wallet_balance", 0.0))
    return 0.0

# -------------------- USER PURCHASES & ACCESS CHECK --------------------
async def add_user_purchase(user_id: int, story_title: str, story_link: str = "#"):
    """खरीदे गए टाइटल की पहली लाइन सेव करेगा"""
    title_clean = clean_title(story_title)
    await purchases_col.update_one(
        {"user_id": user_id, "story_title": title_clean},
        {"$set": {"user_id": user_id, "story_title": title_clean, "link": story_link}},
        upsert=True
    )

async def is_story_unlocked(user_id: int, story_title: str) -> bool:
    """चेक करता है कि यूज़र ने स्टोरी खरीदी है या नहीं"""
    title_clean = clean_title(story_title)
    purchase = await purchases_col.find_one({"user_id": user_id, "story_title": title_clean})
    return bool(purchase)

async def get_user_purchases(user_id: int):
    """यूज़र की खरीदी हुई सभी स्टोरीज़ की लिस्ट निकालने के लिए फ़ंक्शन"""
    cursor = purchases_col.find({"user_id": user_id})
    return await cursor.to_list(length=None)

# -------------------- STORY DATABASE FUNCTIONS --------------------
async def add_story_db(data: dict):
    """स्टोरी जोड़ते या अपडेट करते समय Title की केवल पहली लाइन ही स्टोर होगी"""
    if "title" in data:
        data["title"] = clean_title(data["title"])
    
    story_doc = {
        "title": data["title"],
        "category": data.get("category", ""),
        "photo": data.get("photo", ""),
        "price": data.get("price", 0),
        "desc": data.get("desc", ""),
        "demo_enabled": data.get("demo_enabled", False),
        "demo_msg_ids": data.get("demo_msg_ids", []),
        "first_msg_id": data.get("first_msg_id", 0),
        "last_msg_id": data.get("last_msg_id", 0),
        "custom_ranges": data.get("custom_ranges", []),
        "link": data.get("link", "")
    }

    await stories_col.update_one(
        {"title": data["title"]},
        {"$set": story_doc},
        upsert=True
    )
    return True

async def update_story_demo_status(title: str, is_enabled: bool) -> bool:
    """किसी स्टोरी के लिए Demo (Yes/No) टॉगल करने का फ़ंक्शन"""
    title_clean = clean_title(title)
    res = await stories_col.update_one(
        {"title": title_clean},
        {"$set": {"demo_enabled": is_enabled}}
    )
    return res.modified_count > 0

async def update_story_range(title: str, first_msg_id: int, last_msg_id: int) -> bool:
    """किसी स्टोरी के लिए First और Last Message ID सेट करने का फ़ंक्शन"""
    title_clean = clean_title(title)
    res = await stories_col.update_one(
        {"title": title_clean},
        {"$set": {"first_msg_id": int(first_msg_id), "last_msg_id": int(last_msg_id)}}
    )
    return res.modified_count > 0

async def delete_story_db(title: str) -> bool:
    """स्टोरी डिलीट करने का फ़ंक्शन - Main List और Purchase List दोनों से डिलीट करता है"""
    title_clean = clean_title(title)
    res = await stories_col.delete_one({"title": title_clean})
    
    if res.deleted_count > 0:
        await purchases_col.delete_many({
            "$or": [
                {"story_title": title_clean},
                {"title": title_clean}
            ]
        })
        return True
    return False

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

async def get_story_by_title(title: str):
    title_clean = clean_title(title)
    return await stories_col.find_one({"title": title_clean})
