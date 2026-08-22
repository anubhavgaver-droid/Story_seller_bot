import os
import motor.motor_asyncio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from config import MONGO_URL

app = FastAPI()

# Database Connection
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = client["story_seller_db"]
stories_collection = db["stories"]

# 1. Root Route: Returns HTML Interface (Mini App)
@app.get("/", response_class=HTMLResponse)
async def serve_miniapp():
    # File path setup (works inside web/ or root directory)
    base_dir = os.path.dirname(__file__)
    html_path = os.path.join(base_dir, "index.html")
    
    # Fallback check for web/index.html structure
    if not os.path.exists(html_path):
        html_path = os.path.join(base_dir, "web", "index.html")

    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
            
    return "<h3 style='color:red;'>index.html file not found! Please verify the folder structure.</h3>"

# 2. API Route for Mini App Stories
@app.get("/api/stories")
async def get_stories_api():
    stories = []
    async for story in stories_collection.find():
        stories.append({
            # Document _id ko String me convert karke send kar rahe hain
            "id": str(story.get("_id", "")),
            "title": story.get("title", "Untitled"),
            "price": story.get("price", 0),
            "platform": story.get("platform", story.get("category", "PRATILIPI FM")),
            "description": story.get("desc", story.get("description", "")),
            "photo": story.get("photo", story.get("poster", "https://picsum.photos/200"))
        })
    return stories
