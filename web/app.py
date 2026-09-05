import os
import motor.motor_asyncio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from config import MONGO_URL, BOT_USERNAME

app = FastAPI()

# Database Connection
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = client["story_seller_db"]
stories_collection = db["stories"]

# 1. Root Route: Returns HTML Interface (Mini App)
@app.get("/", response_class=HTMLResponse)
async def serve_miniapp():
    base_dir = os.path.dirname(__file__)
    html_path = os.path.join(base_dir, "index.html")
    
    if not os.path.exists(html_path):
        html_path = os.path.join(base_dir, "web", "index.html")

    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
            
    return "<h3 style='color:red;'>index.html file not found! Please verify the folder structure.</h3>"

# 2. API Route for Mini App Stories (Demo Synced)
@app.get("/api/stories")
async def get_stories_api():
    stories = []
    async for story in stories_collection.find():
        raw_title = story.get("title", "Untitled")
        clean_title = raw_title.strip().splitlines()[0] if raw_title else "Untitled"
        url_clean_title = clean_title.replace(" ", "_")
        
        msg_ids = story.get("msg_ids", [])
        
        # Calculate total files from message IDs if available
        first_id = story.get("first_msg_id")
        last_id = story.get("last_msg_id")
        if first_id and last_id and last_id >= first_id:
            total_files_count = (last_id - first_id) + 1
        else:
            total_files_count = len(story.get("custom_ranges", [])) * 50 or 24

        # Check demo status
        demo_enabled = story.get("demo_enabled", False) or len(msg_ids) > 0
        demo_msg_ids = story.get("demo_msg_ids", [])

        stories.append({
            "id": str(story.get("_id", "")),
            "title": clean_title,
            "price": story.get("price", 0),
            "platform": story.get("platform", story.get("category", "Pocket FM")),
            "episodes": story.get("episodes", "N/A"),
            "total_files": f"{total_files_count} files",
            "description": story.get("desc", story.get("description", "Complete audio series package.")),
            "photo": story.get("photo", "https://picsum.photos/200"),
            
            # Mini App & Bot Sync Fields
            "has_demo": demo_enabled,
            "demo_enabled": demo_enabled,
            "demo_msg_ids": demo_msg_ids,
            "demo_link": f"https://t.me/{BOT_USERNAME}?start=demo_{url_clean_title}"
        })
    return stories
