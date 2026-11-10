import re
import sys
import os
import time
import secrets
import string
from urllib.parse import unquote
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL, LOG_CHANNEL, BOT_USERNAME, CHANNEL_ID, DB_CHANNEL_IDS

# MongoDB Async Client Setup
client = AsyncIOMotorClient(MONGO_URL)
db = client["story_seller_db"]

# Collections
stories_col = db["stories"]
users_col = db["users"]              # User Registration, Wallet & Language
purchases_col = db["purchases"]        # Purchased Stories
verified_orders_col = db["verified_orders"]  # Webhook Auto-Payments
payment_orders_col = db["payment_orders"]    # Every payment order the bot creates (survives restarts)
settings_col = db["settings"]                # Admin switches (auto-pay maintenance, active DB channel)
claim_tokens_col = db["claim_tokens"]        # Free-story ad-gate tokens
used_utrs_col = db["used_utrs"]              # Manual-payment UTRs already approved (duplicate guard)
email_credits_col = db["email_credits"]      # Payment-received emails read from Gmail (one document per email)
deliveries_col = db["deliveries"]            # Audio/video files delivered to each user per story (what the Stream player shows)


# -------------------- DELIVERED FILES (Stream player) --------------------
async def record_delivered(user_id: int, story_id: str, items: list):
    """
    Saves the audio/video files that were delivered to this user for this story (id, title, size, file_id ...).
    The Stream player shows exactly these files and needs NO Telegram call to open.
    New items are added; an item that is delivered again just replaces its old entry.
    """
    if not items:
        return
    doc = await deliveries_col.find_one({"user_id": user_id, "story_id": story_id}, {"items": 1}) or {}
    merged = {it["id"]: it for it in (doc.get("items") or [])}
    for it in items:
        merged[it["id"]] = it
    ordered = [merged[k] for k in sorted(merged)]
    await deliveries_col.update_one(
        {"user_id": user_id, "story_id": story_id},
        {"$set": {"items": ordered, "updated_at": time.time()}},
        upsert=True
    )


async def get_delivered(user_id: int, story_id: str):
    """List of delivered files for this user+story, or None when nothing was recorded (delivered before this feature)."""
    doc = await deliveries_col.find_one({"user_id": user_id, "story_id": story_id}, {"items": 1})
    items = (doc or {}).get("items")
    return items or None


# -------------------- SETTINGS (admin switches) --------------------
async def get_setting(key: str, default=None):
    doc = await settings_col.find_one({"key": key})
    return doc["value"] if doc and "value" in doc else default


async def set_setting(key: str, value):
    await settings_col.update_one({"key": key}, {"$set": {"key": key, "value": value}}, upsert=True)


# -------------------- DB CHANNELS (multiple) --------------------
def story_channel(story) -> int:
    """Story ki files jis channel me hain. Purani stories (db_channel nahi) -> CHANNEL_ID."""
    try:
        return int((story or {}).get("db_channel") or CHANNEL_ID)
    except (TypeError, ValueError):
        return CHANNEL_ID


async def get_active_db_channel() -> int:
    """Naye stories ke liye channel (jab admin sirf message ID deta hai, link nahi)."""
    val = await get_setting("active_db_channel")
    try:
        val = int(val)
    except (TypeError, ValueError):
        return CHANNEL_ID
    return val if val in DB_CHANNEL_IDS else CHANNEL_ID


# -------------------- LOG HELPER FUNCTION --------------------
async def send_log(client_bot, text: str):
    """Log Channel में मैसेज भेजने के लिए Helper फ़ंक्शन"""
    if LOG_CHANNEL and LOG_CHANNEL != 0:
        try:
            await client_bot.send_message(chat_id=LOG_CHANNEL, text=text)
        except Exception as e:
            print(f"Log Error: {e}")


# -------------------- STORY ID / LINK HELPERS --------------------
# IDs sirf a-z aur 0-9 se bante hain: Telegram deep-link (start / startapp) me valid,
# callback_data me chhote (64 byte limit), aur "_" na hone se parsing safe.
_ID_ALPHABET = string.ascii_lowercase + string.digits


def _random_id(length: int = 8) -> str:
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(length))


async def generate_story_id() -> str:
    """Naya random, unique story_id (title se koi lena-dena nahi)."""
    for _ in range(25):
        sid = _random_id(8)
        if not await stories_col.find_one({"story_id": sid}, {"_id": 1}):
            return sid
    return _random_id(12)


def delivery_link(story_id) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=get_{story_id}"


def share_link(story_id) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=story_{story_id}"


def demo_link(story_id) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=demo_{story_id}"


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
        "lang_code": "en",
        "joined_at": time.time()
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
        return_document=ReturnDocument.AFTER
    )
    return float(user.get("wallet_balance", 0.0))


async def deduct_wallet_if_enough(user_id: int, amount: float):
    """
    Atomic deduction: balance kam ho to kuch nahi katta aur None lautata hai.
    Double-click / ek saath do request aane par bhi balance minus me nahi jaata.
    Success par naya balance (float) lautata hai.
    """
    amount = round(float(amount), 2)
    if amount <= 0:
        return await get_user_wallet(user_id)

    doc = await users_col.find_one_and_update(
        {"user_id": user_id, "wallet_balance": {"$gte": amount - 0.005}},
        {"$inc": {"wallet_balance": -amount}},
        return_document=ReturnDocument.AFTER
    )
    if not doc:
        return None
    return round(float(doc.get("wallet_balance", 0.0)), 2)


# -------------------- REFERRAL DATABASE FUNCTIONS --------------------
async def get_referred_users_count(user_id: int) -> int:
    """किसी यूज़र द्वारा रेफर किए गए कुल यूज़र्स की संख्या गिनता है"""
    return await users_col.count_documents({"referred_by": user_id})


# -------------------- USER PURCHASES & ACCESS CHECK --------------------
async def add_user_purchase(user_id: int, story_title: str, story_link: str = "#", story_id: str = None):
    """
    Purchase save karta hai. Ab story_id ke saath save hota hai, isliye baad me
    title badalne / emoji hone par bhi access chalta rehta hai.
    Purani purchase (sirf title wali) mil jaye to usme story_id jud jaati hai.
    """
    clean_title = story_title.strip().split("\n")[0]

    if not story_id:
        story_doc = await get_story_by_title(clean_title)
        story_id = story_doc.get("story_id") if story_doc else None

    if story_id:
        story_id = str(story_id)
        story_link = delivery_link(story_id)

    set_fields = {
        "user_id": user_id,
        "story_title": clean_title,
        "story_link": story_link,
        "link": story_link,
        "timestamp": time.time()
    }
    if story_id:
        set_fields["story_id"] = story_id
        query = {"user_id": user_id, "$or": [{"story_id": story_id}, {"story_title": clean_title}]}
    else:
        query = {"user_id": user_id, "story_title": clean_title}

    await purchases_col.update_one(query, {"$set": set_fields}, upsert=True)

    # Users Collection में भी purchased_stories की लिस्ट में जोड़ना ताकि /addepisodes नोटिफिकेशन काम कर सके
    add_to_set = {"purchased_stories": clean_title}
    if story_id:
        add_to_set["purchased_story_ids"] = story_id
    await users_col.update_one({"user_id": user_id}, {"$addToSet": add_to_set})


async def is_story_unlocked(user_id: int, story_title: str, story_id: str = None) -> bool:
    """चेक करता है कि यूज़र ने स्टोरी खरीदी है या नहीं (pehle story_id se, phir title se)"""
    if story_id:
        if await purchases_col.find_one({"user_id": user_id, "story_id": str(story_id)}, {"_id": 1}):
            return True

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


def _legacy_title_pattern(key: str):
    """
    Purane links me title ke space "_" bane the. Isliye "_" ko space ya "_" dono se match karte hain
    (title me asli "_" ho to bhi chalta hai).
    """
    parts = []
    for ch in key:
        parts.append("[ _]" if ch in " _" else re.escape(ch))
    return re.compile("^" + "".join(parts) + "$", re.IGNORECASE)


async def get_story_by_title(title: str):
    """टाइटल के आधार पर स्टोरी ढूँढता है (Exact Match Case-Insensitive)"""
    clean_title = title.strip().split("\n")[0]
    pattern = re.compile(f"^{re.escape(clean_title)}$", re.IGNORECASE)
    return await stories_col.find_one({"title": pattern})


async def get_story_by_key(key: str):
    """
    Link / button se aayi key se story dhundhta hai.
      1. Naya tareeka: random story_id
      2. Purana tareeka: title (space -> "_") - taaki purane links na tootein
    """
    if not key:
        return None
    key = str(key).strip()
    if not key:
        return None

    story = await stories_col.find_one({"story_id": key})
    if story:
        return story

    candidates = [key]
    decoded = unquote(key)
    if decoded != key:
        candidates.append(decoded)

    for cand in candidates:
        story = await get_story_by_title(cand)
        if story:
            return story
        story = await stories_col.find_one({"title": _legacy_title_pattern(cand)})
        if story:
            return story
    return None


async def _find_story_exact(key: str):
    """Admin ke liye: story_id ya bilkul exact title (loose '_' matching nahi)."""
    if not key:
        return None
    story = await stories_col.find_one({"story_id": str(key).strip()})
    if story:
        return story
    return await get_story_by_title(key)


async def add_story_db(data: dict):
    """
    स्टोरी जोड़ते या अपडेट करते समय Title की केवल पहली लाइन को ही Clean Title बनाएगा।
    नई स्टोरी को random story_id मिलती है (title से लिंक नहीं बनता).
    पहले से मौजूद स्टोरी की story_id कभी नहीं बदलती, इसलिए पुराने लिंक चलते रहते हैं।
    data me 'story_id' aur 'link' bhar diye jaate hain taaki caller use kar sake.
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

    # फ़ाइलों की कुल गिनती
    total_files_count = (last_msg_id - first_msg_id + 1) if (first_msg_id and last_msg_id) else 0

    # ऑटो-एपिसोड्स कैलकुलेशन
    episodes = data.get("episodes")
    if not episodes and total_files_count > 0:
        episodes = f"{total_files_count} Episodes"
    elif not episodes:
        episodes = "N/A"

    # पहले से मौजूद ID या नई random ID सेट करना
    existing_story = await stories_col.find_one({"title": clean_title})
    story_id = existing_story.get("story_id") if existing_story else None
    if not story_id:
        story_id = data.get("story_id") or await generate_story_id()
    story_id = str(story_id)

    story_doc = {
        "story_id": story_id,
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
        "db_channel": int(data.get("db_channel") or (existing_story or {}).get("db_channel") or CHANNEL_ID),
        "link": delivery_link(story_id)
    }

    await stories_col.update_one(
        {"title": clean_title},
        {"$set": story_doc},
        upsert=True
    )

    data["story_id"] = story_id
    data["link"] = story_doc["link"]
    return True


async def rename_story_db(story: dict, new_title: str) -> str:
    """
    Story ka naam badalta hai. Purchases / buyers list bhi naye naam par le aata hai,
    taaki rename ke baad kharidne wale ka access na toote. story_id wahi rehti hai.
    """
    new_title = new_title.strip().split("\n")[0]
    old_title = story.get("title", "")
    story_id = story.get("story_id")
    if not story_id:
        story_id = await generate_story_id()
    story_id = str(story_id)
    link = delivery_link(story_id)

    await stories_col.update_one(
        {"_id": story["_id"]},
        {"$set": {"title": new_title, "story_id": story_id, "link": link}}
    )

    await purchases_col.update_many(
        {"$or": [{"story_id": story_id}, {"story_title": old_title}]},
        {"$set": {"story_title": new_title, "story_id": story_id, "story_link": link, "link": link}}
    )

    if old_title and old_title != new_title:
        await users_col.update_many({"purchased_stories": old_title}, {"$addToSet": {"purchased_stories": new_title}})
        await users_col.update_many({"purchased_stories": old_title}, {"$pull": {"purchased_stories": old_title}})

    return story_id


async def update_story_demo_status(title: str, is_enabled: bool) -> bool:
    """किसी स्टोरी के लिए Demo (Yes/No) टॉगल करने का फ़ंक्शन"""
    story = await _find_story_exact(title)
    if not story:
        return False
    await stories_col.update_one({"_id": story["_id"]}, {"$set": {"demo_enabled": is_enabled}})
    return True


async def update_story_range(title: str, first_msg_id: int, last_msg_id: int) -> bool:
    """किसी स्टोरी के लिए First और Last Message ID सेट करने का फ़ंक्शन"""
    story = await _find_story_exact(title)
    if not story:
        return False
    calc_files = (int(last_msg_id) - int(first_msg_id)) + 1
    await stories_col.update_one(
        {"_id": story["_id"]},
        {"$set": {
            "first_msg_id": int(first_msg_id), 
            "last_msg_id": int(last_msg_id),
            "total_files": f"{calc_files} files"
        }}
    )
    return True


async def delete_story_db(title: str) -> bool:
    """स्टोरी डिलीट करने का फ़ंक्शन - Main List और Purchase List दोनों से डिलीट करता है"""
    story = await _find_story_exact(title)
    if not story:
        return False

    clean_title = story.get("title", "")
    story_id = story.get("story_id")

    res = await stories_col.delete_one({"_id": story["_id"]})
    if res.deleted_count > 0:
        conditions = [{"story_title": clean_title}, {"title": clean_title}]
        if story_id:
            conditions.append({"story_id": story_id})
        await purchases_col.delete_many({"$or": conditions})
        return True
    return False


async def get_all_stories():
    """सभी स्टोरीज़ की लिस्ट निकालने के लिए फ़ंक्शन (Auto-Repost में प्रयोग के लिए)"""
    try:
        cursor = stories_col.find({})
        return await cursor.to_list(length=2000)
    except Exception as e:
        print(f"Error in get_all_stories: {e}")
        return []


async def get_stories_by_cat(cat_key, page=1, limit=10):
    """
    Case-insensitive Regex category fetcher.
    Matches 'Pocket FM', 'POCKET FM', 'pocket_fm', 'Pratilipi FM', etc.
    """
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
    """
    टाइटल या विवरण के आधार पर पेजिनेटेड सर्च परिणाम देता है।
    """
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


# -------------------- AUTO-PAYMENT & WEBHOOK DB FUNCTIONS --------------------
async def is_order_verified(order_id: str) -> bool:
    """
    Check करता है कि Order ID payment status 'PAID' हो चुका है या नहीं।
    """
    record = await verified_orders_col.find_one({"order_id": order_id, "status": "PAID"})
    return bool(record)


async def get_verified_order_details(order_id: str):
    """
    Order ID की सारी details (Amount, Txn ID, Time) fetch करने के लिए।
    """
    return await verified_orders_col.find_one({"order_id": order_id})


# -------------------- PAYMENT ORDERS (restart-safe, one-time fulfilment) --------------------
async def create_payment_order(order_id: str, user_id: int, amount: float, kind: str,
                               story_id: str = None, title: str = None, pay_url: str = None,
                               provider: str = None, provider_ref: str = None, payable_amount: float = None):
    """Har gateway order ka record. kind = 'STORY' ya 'WALLET'."""
    await payment_orders_col.insert_one({
        "order_id": order_id,
        "user_id": user_id,
        "amount": round(float(amount), 2),
        "kind": kind,
        "story_id": story_id,
        "title": title,
        "pay_url": pay_url,
        "provider": provider or "demotry",
        "provider_ref": provider_ref,
        "payable_amount": round(float(payable_amount), 2) if payable_amount is not None else None,
        "status": "CREATED",
        "created_at": time.time()
    })


async def get_payment_order(order_id: str):
    return await payment_orders_col.find_one({"order_id": order_id})


async def get_latest_open_order(user_id: int):
    """Purane 'auto_check_payment_<user>' buttons ke liye: user ka sabse naya unpaid order."""
    return await payment_orders_col.find_one(
        {"user_id": user_id, "status": "CREATED"},
        sort=[("created_at", -1)]
    )


async def set_order_utr(order_id: str, utr: str):
    """Saves the UTR the user submitted for an open order (the mail-payment check reads it from here)."""
    await payment_orders_col.update_one(
        {"order_id": order_id, "status": {"$ne": "PAID"}},
        {"$set": {"submitted_utr": utr, "utr_submitted_at": time.time()}}
    )


async def claim_payment_order(order_id: str, paid_amount: float):
    """
    Order ko atomic tareeke se PAID mark karta hai. Sirf EK caller ko order doc milta hai,
    baaki ko None -> isse wallet/story do baar nahi milta (double-click, webhook + verify dono).
    """
    return await payment_orders_col.find_one_and_update(
        {"order_id": order_id, "status": {"$ne": "PAID"}},
        {"$set": {"status": "PAID", "paid_amount": round(float(paid_amount), 2), "paid_at": time.time()}},
        return_document=ReturnDocument.AFTER
    )


async def release_payment_order(order_id: str):
    """Fulfilment beech me fail ho jaye to order wapas CREATED kar do taaki user dobara Verify dabaye."""
    await payment_orders_col.update_one({"order_id": order_id}, {"$set": {"status": "CREATED"}})


# -------------------- FREE STORY CLAIM TOKENS (ad gate) --------------------
async def create_claim_token(user_id: int, story_id: str) -> str:
    """Free story claim ke liye ek-baar-wala token (shortener ke baad verify hota hai)."""
    token = secrets.token_urlsafe(9)
    await claim_tokens_col.insert_one({
        "token": token,
        "user_id": user_id,
        "story_id": str(story_id),
        "short_url": None,
        "created_at": time.time(),
        "used": False
    })
    return token


async def set_claim_short_url(token: str, short_url: str):
    await claim_tokens_col.update_one({"token": token}, {"$set": {"short_url": short_url}})


async def get_claim_token(token: str):
    return await claim_tokens_col.find_one({"token": token})


async def use_claim_token(token: str):
    """Atomic: sirf pehli baar doc milta hai, dobara None (double-claim nahi)."""
    return await claim_tokens_col.find_one_and_update(
        {"token": token, "used": False},
        {"$set": {"used": True, "used_at": time.time()}},
        return_document=ReturnDocument.AFTER
    )


# -------------------- E-MAIL PAYMENTS (FamPay / bank "payment received" mails in Gmail) --------------------
async def get_open_email_payables(since_ts: float) -> set:
    """Unique amounts (in paise) that are already reserved by open e-mail orders."""
    cur = payment_orders_col.find(
        {"provider": "email", "status": "CREATED", "created_at": {"$gte": since_ts}},
        {"payable_amount": 1, "_id": 0}
    )
    return {int(round(float(d["payable_amount"]) * 100)) async for d in cur if d.get("payable_amount") is not None}


async def find_open_email_orders(amount: float, since_ts: float) -> list:
    """Open e-mail orders whose unique payable amount equals `amount` (oldest first)."""
    cur = payment_orders_col.find({
        "provider": "email", "status": "CREATED",
        "payable_amount": {"$gte": round(amount - 0.005, 3), "$lte": round(amount + 0.005, 3)},
        "created_at": {"$gte": since_ts},
    }).sort("created_at", 1)
    return await cur.to_list(length=5)


async def count_other_open_email_orders(user_id: int, since_ts: float) -> int:
    """Open mail-payment orders of OTHER users created since `since_ts` (decides: direct verify or ask for the UTR)."""
    return await payment_orders_col.count_documents({
        "provider": "email", "status": "CREATED",
        "created_at": {"$gte": since_ts}, "user_id": {"$ne": user_id},
    })


async def find_email_credit_by_order(order_id: str):
    """The payment mail already matched to this order (a delivery retry must not need a second mail)."""
    return await email_credits_col.find_one({"order_id": order_id, "status": "MATCHED"}, {"_id": 0})


async def save_email_credit(doc: dict) -> bool:
    """False when this e-mail was already stored (same msg_key), so one mail is never processed twice."""
    try:
        await email_credits_col.insert_one(doc)
        return True
    except DuplicateKeyError:
        return False


async def update_email_credit(msg_key: str, fields: dict):
    await email_credits_col.update_one({"msg_key": msg_key}, {"$set": fields})


async def claim_email_credit(msg_key: str, order_id: str) -> bool:
    """Atomic: a credit can be attached to exactly one order."""
    doc = await email_credits_col.find_one_and_update(
        {"msg_key": msg_key, "status": {"$in": ["NEW", "UNMATCHED"]}},
        {"$set": {"status": "MATCHED", "order_id": order_id, "matched_at": time.time()}},
        return_document=ReturnDocument.AFTER
    )
    return bool(doc)


async def release_email_credit(msg_key: str):
    await email_credits_col.update_one({"msg_key": msg_key, "status": "MATCHED"}, {"$set": {"status": "UNMATCHED"}})


async def get_unmatched_email_credits(since_ts: float, limit: int = 50) -> list:
    cur = email_credits_col.find({"status": "UNMATCHED", "received_at": {"$gte": since_ts}}).sort("received_at", -1)
    return await cur.to_list(length=limit)


async def get_recent_email_credits(limit: int = 8) -> list:
    cur = email_credits_col.find({}).sort("created_at", -1)
    return await cur.to_list(length=limit)


# -------------------- UTR DUPLICATE GUARD (manual payments) --------------------
async def utr_exists(utr: str) -> bool:
    return bool(await used_utrs_col.find_one({"utr": utr}, {"_id": 1}))


async def claim_utr(utr: str, user_id: int, order_id: str = None) -> bool:
    """True if this UTR was never approved before (and is now recorded). False if it was already used."""
    doc = {"utr": utr, "user_id": user_id, "at": time.time()}
    if order_id:
        doc["order_id"] = order_id
    try:
        await used_utrs_col.insert_one(doc)
        return True
    except DuplicateKeyError:
        return False


async def get_utr_doc(utr: str):
    """The record of a used UTR (user_id, and order_id for UTRs verified from the bank mail), or None."""
    return await used_utrs_col.find_one({"utr": utr}, {"_id": 0})


# -------------------- SUPPORT ("I paid but did not receive") --------------------
async def mark_order_sos(order_id: str) -> bool:
    """True only the first time a user raises a support request for this order (no spam)."""
    res = await payment_orders_col.update_one(
        {"order_id": order_id, "sos_at": {"$exists": False}},
        {"$set": {"sos_at": time.time()}}
    )
    return res.modified_count > 0


# -------------------- ADMIN STATS --------------------
async def get_stats() -> dict:
    now = time.time()
    day, week, month = 86400, 7 * 86400, 30 * 86400

    async def revenue(since):
        cur = payment_orders_col.aggregate([
            {"$match": {"status": "PAID", "paid_at": {"$gte": since}}},
            {"$group": {"_id": None, "sum": {"$sum": "$paid_amount"}, "n": {"$sum": 1}}}
        ])
        rows = await cur.to_list(length=1)
        return (round(rows[0]["sum"], 2), rows[0]["n"]) if rows else (0.0, 0)

    top_cur = purchases_col.aggregate([
        {"$group": {"_id": "$story_title", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": 5}
    ])
    wallet_cur = users_col.aggregate([{"$group": {"_id": None, "sum": {"$sum": "$wallet_balance"}}}])
    wallet_rows = await wallet_cur.to_list(length=1)

    return {
        "users_total": await users_col.count_documents({}),
        "users_today": await users_col.count_documents({"joined_at": {"$gte": now - day}}),
        "users_week": await users_col.count_documents({"joined_at": {"$gte": now - week}}),
        "stories_total": await stories_col.count_documents({}),
        "stories_free": await stories_col.count_documents({"price": {"$in": [0, 0.0, "0", None]}}),
        "purchases_total": await purchases_col.count_documents({}),
        "purchases_today": await purchases_col.count_documents({"timestamp": {"$gte": now - day}}),
        "purchases_week": await purchases_col.count_documents({"timestamp": {"$gte": now - week}}),
        "orders_today": await payment_orders_col.count_documents({"created_at": {"$gte": now - day}}),
        "rev_today": await revenue(now - day),
        "rev_week": await revenue(now - week),
        "rev_month": await revenue(now - month),
        "free_claims": await claim_tokens_col.count_documents({"used": True}),
        "wallet_total": round(wallet_rows[0]["sum"], 2) if wallet_rows else 0.0,
        "top_stories": [(r["_id"], r["n"]) async for r in top_cur],
    }


# -------------------- STARTUP: ID REPAIR + INDEXES --------------------
async def init_db():
    """
    Bot start hone par ek baar chalta hai:
      - jis story me story_id nahi (ya duplicate hai) use naya random ID deta hai
      - purani purchases me story_id jodta hai (taaki baad me rename par bhi access rahe)
      - zaroori indexes banata hai
    Purani stories ki maujooda story_id kabhi nahi badalti (duplicate ko chhodkar).
    """
    try:
        seen = set()
        fixed = 0
        async for s in stories_col.find({}, {"story_id": 1, "title": 1}):
            sid = s.get("story_id")
            sid = str(sid) if sid not in (None, "") else None

            if (not sid) or (sid in seen):
                new_id = _random_id(8)
                while new_id in seen or await stories_col.find_one({"story_id": new_id}, {"_id": 1}):
                    new_id = _random_id(8)
                await stories_col.update_one(
                    {"_id": s["_id"]},
                    {"$set": {"story_id": new_id, "link": delivery_link(new_id)}}
                )
                sid = new_id
                fixed += 1
            elif s.get("story_id") != sid:
                await stories_col.update_one({"_id": s["_id"]}, {"$set": {"story_id": sid}})

            seen.add(sid)

            title = s.get("title")
            if title:
                await purchases_col.update_many(
                    {"story_title": title, "story_id": {"$exists": False}},
                    {"$set": {"story_id": sid}}
                )
        if fixed:
            print(f"🔧 init_db: {fixed} stories ko story_id mil gayi")
    except Exception as e:
        print(f"⚠ init_db story-id repair error: {e}")

    index_jobs = [
        (stories_col, [("story_id", 1)], {"unique": True, "sparse": True}),
        (purchases_col, [("user_id", 1), ("story_id", 1)], {}),
        (purchases_col, [("user_id", 1), ("story_title", 1)], {}),
        (payment_orders_col, [("order_id", 1)], {"unique": True}),
        (payment_orders_col, [("user_id", 1), ("status", 1)], {}),
        (claim_tokens_col, [("token", 1)], {"unique": True}),
        (used_utrs_col, [("utr", 1)], {"unique": True}),
        (email_credits_col, [("msg_key", 1)], {"unique": True}),
        (deliveries_col, [("user_id", 1), ("story_id", 1)], {"unique": True}),
        (payment_orders_col, [("provider", 1), ("status", 1), ("payable_amount", 1)], {}),
    ]
    for col, keys, opts in index_jobs:
        try:
            await col.create_index(keys, **opts)
        except Exception as e:
            print(f"⚠ index warning on {col.name} {keys}: {e}")
