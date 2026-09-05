import re
import sys
import os
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL, LOG_CHANNEL

client = AsyncIOMotorClient(MONGO_URL)
db = client["story_seller_db"]
stories_col = db["stories"]
users_col = db["users"]        # Collection for User Registration, Wallet & Language
purchases_col = db["purchases"]  # Collection for Purchased Stories
episodes_col = db["episodes"]   # Collection for Fast Episode Indexing & Search

# -------------------- LOG HELPER FUNCTION --------------------
async def send_log(client_bot, text: str):
    """Log Channel में मैसेज भेजने के लिए Helper फ़ंक्शन"""
    if LOG_CHANNEL and LOG_CHANNEL != 0:
        try:
            await client_bot.send_message(chat_id=LOG_CHANNEL, text=text)
        except Exception as e:
            print(f"Log Error: {e}")

# -------------------- EPISODE EXTRACTION HELPERS --------------------
def extract_ep_from_file_or_caption(message) -> int:
    """
    कैप्शन या असली File Name से Regex द्वारा Episode Number निकालता है।
    """
    if not message:
        return None
        
    caption_text = message.caption or message.text or ""
    
    file_name = ""
    if message.document and message.document.file_name:
        file_name = message.document.file_name
    elif message.audio and message.audio.file_name:
        file_name = message.audio.file_name
    elif message.video and message.video.file_name:
        file_name = message.video.file_name

    # Pattern for Ep, Episode, Eps, etc.
    pattern = r'(?:ep|episode|eps|episodes)\b[\s._-]*(\d+)'
    
    # 1. First check caption
    match = re.search(pattern, caption_text, re.IGNORECASE)
    if match:
        return int(match.group(1))

    # 2. Check File Name if caption didn't match
    if file_name:
        match_file = re.search(pattern, file_name, re.IGNORECASE)
        if match_file:
            return int(match_file.group(1))

    # 3. Fallback: Search for first standalone number
    text_to_search = f"{caption_text} {file_name}"
    numbers = re.findall(r'\b\d+\b', text_to_search)
    if numbers:
        return int(numbers[0])

    return None

def get_exact_episode_range(fetched_messages) -> str:
    """
    फ़ाइलों की लिस्ट से Start Episode और End Episode की सटीक रेंज बनाता है (e.g. Episode 1 to 100)
    """
    if not fetched_messages:
        return "No Files"
        
    start_msg = fetched_messages[0]
    end_msg = fetched_messages[-1]

    first_ep = extract_ep_from_file_or_caption(start_msg)
    last_ep = extract_ep_from_file_or_caption(end_msg)

    if first_ep is not None and last_ep is not None:
        if first_ep == last_ep:
            return f"Episode {first_ep}"
        return f"Episode {first_ep} to {last_ep}"

    # Fallback to Message IDs if no numbers found in title/filename
    start_id = getattr(start_msg, 'id', getattr(start_msg, 'message_id', 0))
    end_id = getattr(end_msg, 'id', getattr(end_msg, 'message_id', 0))
    return f"Files {start_id} to {end_id}"

# -------------------- EPISODE INDEXING DATABASE HELPER FUNCTIONS --------------------
async def save_story_episodes_db(story_id: str, episode_list: list):
    """
    इंडेक्स किए गए एपिसोड्स की लिस्ट को MongoDB में Bulk इंसर्ट करता है
    और तेज़ खोज के लिए (story_id, episode_num) पर Compound Index बनाता है।
    """
    clean_id = story_id.strip().replace(" ", "_")
    # डुप्लीकेट एंट्रीज़ से बचने के लिए पहले का डेटा डिलीट करें
    await episodes_col.delete_many({"story_id": clean_id})
    
    if episode_list:
        # Array items me story_id add/confirm karein
        for item in episode_list:
            item["story_id"] = clean_id
            
        await episodes_col.insert_many(episode_list)
        # Faster DB Search Performance Indexing
        await episodes_col.create_index([("story_id", 1), ("episode_num", 1)])
        return len(episode_list)
    return 0

async def get_episodes_by_range_db(story_id: str, start_ep: int, end_ep: int) -> list:
    """
    यूज़र द्वारा माँगी गई एपिसोड रेंज (जैसे Ep 1 से 50) के Telegram Message IDs चुटकी में निकालता है।
    """
    clean_id = story_id.strip().replace(" ", "_")
    cursor = episodes_col.find({
        "story_id": clean_id,
        "episode_num": {"$gte": int(start_ep), "$lte": int(end_ep)}
    }).sort("episode_num", 1)
    
    results = await cursor.to_list(length=None)
    return [doc["message_id"] for doc in results if "message_id" in doc]

async def get_single_episode_db(story_id: str, ep_num: int) -> int:
    """
    सिंगल एपिसोड (जैसे Episode 15) की Message ID निकालता है।
    """
    clean_id = story_id.strip().replace(" ", "_")
    doc = await episodes_col.find_one({
        "story_id": clean_id,
        "episode_num": int(ep_num)
    })
    return doc.get("message_id") if doc else None

async def delete_story_episodes_db(story_id: str):
    """
    स्टोरी डिलीट होने पर उसके इंडेक्स किए गए सभी एपिसोड्स MongoDB से डिलीट करता है।
    """
    clean_id = story_id.strip().replace(" ", "_")
    res = await episodes_col.delete_many({"story_id": clean_id})
    return res.deleted_count

# -------------------- USER REGISTRATION & LANGUAGE --------------------
async def is_user_registered(user_id: int) -> bool:
    """चेक करेगा कि यूज़र पहले से रजिस्टर्ड है या नहीं (Returns True or False)"""
    user = await users_col.find_one({"user_id": user_id})
    if user:
        return user.get("is_registered", False)
    return False

async def register_user(user_id: int, first_name: str, username: str = None):
    """नए यूज़र को रजिस्टर करेगा और Default Wallet Balance (0.0) सेट करेगा"""
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
                "lang_code": "en"
            }
        },
        upsert=True
    )

async def get_all_users():
    """ब्रॉडकास्ट के लिए डेटाबेस से सभी रजिस्टर्ड यूज़र्स की लिस्ट निकालता है"""
    cursor = users_col.find({}, {"user_id": 1, "_id": 0})
    return await cursor.to_list(length=None)

async def get_user_lang_db(user_id: int) -> str:
    """यूज़र की सिलेक्टेड भाषा ढूँढता है (Default 'en')"""
    user = await users_col.find_one({"user_id": user_id})
    if user:
        return user.get("lang_code", "en")
    return "en"

async def set_user_lang_db(user_id: int, lang_code: str):
    """यूज़र की भाषा डेटाबेस में अपडेट करता है"""
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"lang_code": lang_code}},
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
        return_document=True
    )
    return float(user.get("wallet_balance", 0.0))

# -------------------- REFERRAL DATABASE FUNCTIONS --------------------
async def get_referred_users_count(user_id: int) -> int:
    """किसी यूज़र द्वारा रेफर किए गए कुल यूज़र्स की संख्या गिनता है"""
    return await users_col.count_documents({"referred_by": user_id})

# -------------------- USER PURCHASES & ACCESS CHECK --------------------
async def add_user_purchase(user_id: int, story_title: str, story_link: str = "#"):
    """ऑटो-पेमेंट या Wallet deduction कन्फर्म होने पर खरीदे गए टाइटल की पहली लाइन सेव करेगा"""
    clean_title = story_title.strip().split("\n")[0]
    await purchases_col.update_one(
        {"user_id": user_id, "story_title": clean_title},
        {"$set": {"user_id": user_id, "story_title": clean_title, "link": story_link}},
        upsert=True
    )

async def is_story_unlocked(user_id: int, story_title: str) -> bool:
    """चेक करता है कि यूज़र ने स्टोरी खरीदी है या नहीं"""
    clean_title = story_title.strip().split("\n")[0]
    purchase = await purchases_col.find_one({"user_id": user_id, "story_title": clean_title})
    return bool(purchase)

async def get_user_purchases(user_id: int):
    """यूज़र की खरीदी हुई सभी स्टोरीज़ की लिस्ट निकालने के लिए फ़ंक्शन"""
    cursor = purchases_col.find({"user_id": user_id})
    return await cursor.to_list(length=None)

# -------------------- STORY DATABASE FUNCTIONS --------------------
async def add_story_db(data: dict):
    """
    स्टोरी जोड़ते या अपडेट करते समय Title की केवल पहली लाइन को ही Clean Title बनाएगा।
    Status, Platform, Genre, Episodes काउंट, demo_enabled, demo_msg_ids और custom_ranges सपोर्ट करता है।
    """
    if "title" in data:
        data["title"] = data["title"].strip().split("\n")[0]
    
    demo_enabled = data.get("demo_enabled", False)
    demo_msg_ids = data.get("demo_msg_ids", [])
    first_msg_id = data.get("first_msg_id", 0)
    last_msg_id = data.get("last_msg_id", 0)
    custom_ranges = data.get("custom_ranges", [])

    # ऑटो-एपिसोड्स कैलकुलेशन
    episodes = data.get("episodes")
    if not episodes and first_msg_id and last_msg_id:
        episodes = (last_msg_id - first_msg_id + 1)
    elif not episodes:
        episodes = "N/A"

    story_doc = {
        "title": data["title"],
        "category": data.get("category", "Pocket FM"),
        "platform": data.get("platform", data.get("category", "Pocket FM")),
        "status": data.get("status", "Completed"),
        "genre": data.get("genre", "Drama"),
        "episodes": episodes,
        "photo": data.get("photo", ""),
        "price": data.get("price", 0),
        "desc": data.get("desc", ""),
        "demo_enabled": demo_enabled,
        "demo_msg_ids": demo_msg_ids,
        "first_msg_id": first_msg_id,
        "last_msg_id": last_msg_id,
        "custom_ranges": custom_ranges,
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
    clean_title = title.strip().split("\n")[0]
    res = await stories_col.update_one(
        {"title": clean_title},
        {"$set": {"demo_enabled": is_enabled}}
    )
    return res.modified_count > 0

async def update_story_range(title: str, first_msg_id: int, last_msg_id: int) -> bool:
    """किसी स्टोरी के लिए First और Last Message ID सेट करने का फ़ंक्शन"""
    clean_title = title.strip().split("\n")[0]
    res = await stories_col.update_one(
        {"title": clean_title},
        {"$set": {"first_msg_id": int(first_msg_id), "last_msg_id": int(last_msg_id)}}
    )
    return res.modified_count > 0

async def delete_story_db(title: str) -> bool:
    """स्टोरी डिलीट करने का फ़ंक्शन - Main List, Purchase List और Episode Indexing से डिलीट करता है"""
    clean_title = title.strip().split("\n")[0]
    story_id = clean_title.replace(" ", "_")
    
    res = await stories_col.delete_one({"title": clean_title})
    
    if res.deleted_count > 0:
        await purchases_col.delete_many({
            "$or": [
                {"story_title": clean_title},
                {"title": clean_title}
            ]
        })
        # Delete associated indexed episodes as well
        await episodes_col.delete_many({"story_id": story_id})
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
    clean_title = title.strip().split("\n")[0]
    return await stories_col.find_one({"title": clean_title})
