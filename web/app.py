from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import os
import motor.motor_asyncio
from config import DB_URL, DB_NAME

app = FastAPI()

# MongoDB Connection
client = motor.motor_asyncio.AsyncIOMotorClient(DB_URL)
db = client[DB_NAME]
stories_collection = db["stories"]

@app.get("/", response_class=HTMLResponse)
async def serve_miniapp():
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

# Auto Fetch stories from Mongo DB for Mini App
@app.get("/api/stories")
async def get_stories_api():
    stories = []
    async for story in stories_collection.find():
        stories.append({
            "title": story.get("title", "Untitled"),
            "price": story.get("price", 0),  # Per-story dynamic price
            "platform": story.get("platform", "PRATILIPI FM"), # Auto platform
            "desc": story.get("desc", ""),
            "photo": story.get("photo", "https://picsum.photos/200")
        })
    return stories
