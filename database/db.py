import re
import sys
import os
import time
from urllib.parse import quote
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL, LOG_CHANNEL, CHANNEL_ID

client = AsyncIOMotorClient(MONGO_URL)
db = client["story_seller_db"]
stories_col = db["stories"]
users_col = db["users"]        # Collection for User Registration, Wallet & Language
purchases_col = db["purchases"]  # Collection for Purchased Stories

WATCH_BASE_URL = "https://story-seller-bot-0jtb.onrender.com"

# -------------------- STREAM LINK GENERATOR HELPER --------------------
def get_file_stream_info(msg, clean_title: str):
    """
    Message से Direct Streaming Link और File Title निकालता है।
    """
    clean_title_single_line = clean_title.strip().split("\n")[0]
    file_title = clean_title_single_line
    direct_audio_link = None

    if msg:
        if getattr(msg, 'audio', None):
            file_title = msg.audio.title or msg.audio.file_name or clean_title_single_line
        elif getattr(msg, 'document', None):
            file_title = msg.document.file_name or clean_title_single_line
        elif getattr(msg, 'video', None):
            file_title = msg.video.file_name or clean_title_single_line

        chat_id = getattr(msg.chat, 'id', 0)
        msg_id = getattr(msg, 'id', getattr(msg, 'message_id', 0))
        
        # डायरेक्ट स्ट्रीम लिंक फॉर्मेट
        direct_audio_link = f"{WATCH_BASE_URL}/stream/{chat_id}/{msg_id}"

    return file_title, direct_audio_link

def get_miniapp_watch_url(msg, clean_title: str, cover_url: str = "") -> str:
    """
    Telegram Mini App Inline Keyboard के लिए Safe Encoded WebApp Link उत्पन्न करता है।
    """
    file_title, stream_url = get_file_stream_info(msg, clean_title)
    if not stream_url:
        return ""
    
    encoded_name = quote(str(file_title))
    encoded_stream = quote(str(stream_url))
    
    miniapp_url = f"{WATCH_BASE_URL}/watch.html?name={encoded_name}&url={encoded_stream}"
    if cover_url:
        miniapp_url += f"&cover={quote(str(cover_url))}"
        
    return miniapp_url

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
        
    caption_text = getattr(message, 'caption', None) or getattr(message, 'text', None) or ""
    
    file_name = ""
    if getattr(message, 'document', None) and message.document.file_name:
        file_name = message.document.file_name
    elif getattr(message, 'audio', None) and message.audio.file_name:
        file_name = message.audio.file_name
    elif getattr(message, 'video', None) and message.video.file_name:
        file_name = message.video.file_name

    pattern = r'(?:ep|episode|eps|episodes)\b[\s._-]*(\d+)'
    
    match = re.search(pattern, caption_text, re.IGNORECASE)
    if match:
        return int(match.group(1))

    if file_name:
        match_file = re.search(pattern, file_name, re.IGNORECASE)
        if match_file:
            return int(match_file.group(1))

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

    start_id = getattr(start_msg, 'id', getattr(start_msg, 'message_id', 0))
    end_id = getattr(end_msg, 'id', getattr(end_msg, 'message_id', 0))
    return f"Files {start_id} to {end_id}"

# -------------------- USER REGISTRATION & LANGUAGE --------------------
async def is_user_registered(user_id: int) -> bool:
    """चेक करेगा कि यूज़र पहले से रजिस्टर्ड है या नहीं (Returns True or False)"""
    user = await users_col.find_one({"user_id": user_id})
    if user:
        return user.get("is_registered", False)
    return False

async def register_user(user_id: int, first_name: str, username: str = None, referred_by: int = None):
    """नए यूज़र को रजिस्टर करेगा और Default Wallet Balance (0.0) सेट करेगा"""
    update_data = {
        "user_id": user_id,
        "first_name": first_name,
        "username": username,
        "is_registered": True
    }
    
    set_on_insert = {
        "wallet_balance": 0.0,
        "lang_code": "en"
    }
    
    if referred_by and referred_by != user_id:
        set_on_insert["referred_by"] = referred_by

    await users_col.update_one(
        {"user_id": user_id},
        {
            "$set": update_data,
            "$setOnInsert": set_on_insert
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
    """ऑटो-पेमेंट या Wallet deduction कन्फर्म होने पर खरीदे गए टाइटल की पहली लाइन और खरीदे गए टाइटल का रिकॉर्ड सेव करेगा"""
    clean_title = story_title.strip().split("\n")[0]
    
    await purchases_col.update_one(
        {"user_id": user_id, "story_title": clean_title},
        {
            "$set": {
                "user_id": user_id, 
                "story_title": clean_title, 
                "story_link": story_link,
                "link": story_link,
                "timestamp": time.time()
            }
        },
        upsert=True
    )

    await users_col.update_one(
        {"user_id": user_id},
        {"$addToSet": {"purchased_stories": clean_title}}
    )

async def is_story_unlocked(user_id: int, story_title: str) -> bool:
    """चेक करता है कि यूज़र ने स्टोरी खरीदी है या नहीं"""
    clean_title = story_title.strip().split("\n")[0]
    pattern = re.compile(f"^{re.escape(clean_title)}$", re.IGNORECASE)
    purchase = await purchases_col.find_one({"user_id": user_id, "story_title": pattern})
    return bool(purchase)

async def get_user_purchases(user_id: int):
    """यूज़र की खरीदी हुई सभी स्टोरीज़ की लिस्ट निकालने के लिए फ़ंक्शन"""
    cursor = purchases_col.find({"user_id": user_id})
    return await cursor.to_list(length=None)

# -------------------- STORY DATABASE FUNCTIONS --------------------
async def get_story_by_id(story_id: str):
    """नॉर्मल Story ID या MongoDB ObjectId से स्टोरी ढूँढता है"""
    story = await stories_col.find_one({"story_id": str(story_id)})
    if story:
        return story
    try:
        return await stories_col.find_one({"_id": ObjectId(story_id)})
    except Exception:
        return None

async def add_story_db(data: dict):
    """
    स्टोरी जोड़ते या अपडेट करते समय Title की केवल पहली लाइन को ही Clean Title बनाएगा।
    """
    if "title" in data:
        data["title"] = data["title"].strip().split("\n")[0]
    
    clean_title = data["title"]
    demo_enabled = data.get("demo_enabled", False)
    demo_msg_ids = data.get("demo_msg_ids", [])
    first_msg_id = data.get("first_msg_id", 0)
    last_msg_id = data.get("last_msg_id", 0)
    custom_ranges = data.get("custom_ranges", [])
    free_link = data.get("free_link", None)

    total_files_count = (last_msg_id - first_msg_id + 1) if (first_msg_id and last_msg_id) else 0

    episodes = data.get("episodes")
    if not episodes and total_files_count > 0:
        episodes = f"{total_files_count} Episodes"
    elif not episodes:
        episodes = "N/A"

    existing_story = await stories_col.find_one({"title": clean_title})
    story_id = existing_story.get("story_id") if existing_story else data.get("story_id", str(int(time.time())))

    story_doc = {
        "story_id": str(story_id),
        "title": clean_title,
        "category": data.get("category", "Pocket FM"),
        "platform": data.get("platform", data.get("category", "Pocket FM")),
        "status": data.get("status", "Completed"),
        "genre": data.get("genre", "Drama"),
        "episodes": episodes,
        "total_files": f"{total_files_count} files" if total_files_count > 0 else "N/A",
        "photo": data.get("photo", ""),
        "price": data.get("price", 0),
        "desc": data.get("desc", ""),
        "free_link": free_link,
        "demo_enabled": demo_enabled,
        "demo_msg_ids": demo_msg_ids,
        "first_msg_id": first_msg_id,
        "last_msg_id": last_msg_id,
        "custom_ranges": custom_ranges,
        "link": data.get("link", "")
    }

    await stories_col.update_one(
        {"title": clean_title},
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
    calc_files = (int(last_msg_id) - int(first_msg_id)) + 1
    res = await stories_col.update_one(
        {"title": clean_title},
        {"$set": {
            "first_msg_id": int(first_msg_id), 
            "last_msg_id": int(last_msg_id),
            "total_files": f"{calc_files} files"
        }}
    )
    return res.modified_count > 0

async def delete_story_db(title: str) -> bool:
    """स्टोरी डिलीट करने का फ़ंक्शन"""
    clean_title = title.strip().split("\n")[0]
    res = await stories_col.delete_one({"title": clean_title})
    
    if res.deleted_count > 0:
        await purchases_col.delete_many({
            "$or": [
                {"story_title": clean_title},
                {"title": clean_title}
            ]
        })
        return True
    return False

async def get_all_stories():
    """सभी स्टोरीज़ की लिस्ट निकालने के लिए फ़ंक्शन"""
    try:
        cursor = stories_col.find({})
        return await cursor.to_list(length=2000)
    except Exception as e:
        print(f"Error in get_all_stories: {e}")
        return []

async def get_stories_by_cat(cat_key, page=1, limit=10):
    if "pocket" in str(cat_key).lower():
        pattern = re.compile(r"pocket", re.IGNORECASE)
    elif "pratilipi" in str(cat_key).lower():
        pattern = re.compile(r"pratilipi", re.IGNORECASE)
    else:
        pattern = re.compile(re.escape(str(cat_key)), re.IGNORECASE)

    query = {
        "$or": [
            {"category": pattern},
            {"platform": pattern}
        ]
    }

    try:
        total_count = await stories_col.count_documents(query)
        if total_count == 0:
            return [], 0

        total_pages = (total_count + limit - 1) // limit
        skip = (page - 1) * limit

        cursor = stories_col.find(query).skip(skip).limit(limit)
        stories = await cursor.to_list(length=limit)
        
        return stories, total_pages
    except Exception as e:
        print(f"Error in get_stories_by_cat: {e}")
        return [], 0

async def search_stories_db(query_str, page=1, limit=10):
    pattern = re.compile(re.escape(query_str), re.IGNORECASE)
    query = {
        "$or": [
            {"title": pattern},
            {"desc": pattern}
        ]
    }
    
    try:
        total_count = await stories_col.count_documents(query)
        if total_count == 0:
            return [], 0

        total_pages = (total_count + limit - 1) // limit
        skip = (page - 1) * limit

        cursor = stories_col.find(query).skip(skip).limit(limit)
        stories = await cursor.to_list(length=limit)
        return stories, total_pages
    except Exception as e:
        print(f"Error in search_stories_db: {e}")
        return [], 0

async def get_story_by_title(title: str):
    clean_title = title.strip().split("\n")[0]
    pattern = re.compile(f"^{re.escape(clean_title)}$", re.IGNORECASE)
    return await stories_col.find_one({"title": pattern})

# -------------------- STREAM INFO FETCHING FOR WEB PLAYER --------------------
async def get_stream_info(story_title: str, is_demo: bool = False, range_idx: int = None):
    """
    स्टोरी टाइटल, डेमो मोड या कस्टम रेंज के आधार पर ऑनलाइन स्ट्रीमिंग के लिए एपिसोड्स की लिस्ट जनरेट करता है।
    """
    story = await get_story_by_title(story_title)
    if not story:
        return None

    target_msg_ids = []

    # 1. डेमो फ़ाइल्स (अगर डेमो मांगा गया हो)
    if is_demo:
        target_msg_ids = story.get("demo_msg_ids", [])
        if not target_msg_ids and story.get("first_msg_id"):
            target_msg_ids = [story["first_msg_id"]]

    # 2. कस्टम रेंज (अगर range_idx पास किया गया हो)
    elif range_idx is not None:
        custom_ranges = story.get("custom_ranges", [])
        if 0 <= range_idx < len(custom_ranges):
            r = custom_ranges[range_idx]
            target_msg_ids = list(range(r["first_id"], r["last_id"] + 1))

    # 3. फुल स्टोरी रेंज (first_msg_id से last_msg_id)
    if not target_msg_ids:
        first_id = story.get("first_msg_id", 0)
        last_id = story.get("last_msg_id", 0)
        if first_id and last_id and last_id >= first_id:
            target_msg_ids = list(range(first_id, last_id + 1))

    episodes = []
    for idx, msg_id in enumerate(target_msg_ids, start=1):
        episodes.append({
            "episode_number": idx,
            "message_id": msg_id,
            "stream_url": f"{WATCH_BASE_URL}/stream/{CHANNEL_ID}/{msg_id}",
            "title": f"Episode {idx}"
        })

    return {
        "title": story.get("title"),
        "cover": story.get("photo", ""),
        "total_episodes": len(episodes),
        "episodes": episodes
    }
