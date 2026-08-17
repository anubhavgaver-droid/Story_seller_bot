import os
import motor.motor_asyncio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from config import DB_URL, DB_NAME

app = FastAPI()

# Database Connection
client = motor.motor_asyncio.AsyncIOMotorClient(DB_URL)
db = client[DB_NAME]
stories_collection = db["stories"]

# 1. Root Route: Returns HTML Interface
@app.get("/", response_class=HTMLResponse)
async def serve_miniapp():
    # web/index.html file path
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>index.html file not found in web/ folder!</h3>"

# 2. API Route for Mini App Stories
@app.get("/api/stories")
async def get_stories_api():
    stories = []
    async for story in stories_collection.find():
        stories.append({
            "title": story.get("title", "Untitled"),
            "price": story.get("price", 0),
            "platform": story.get("platform", "PRATILIPI FM"),
            "desc": story.get("desc", ""),
            "photo": story.get("photo", "https://picsum.photos/200")
        })
    return stories
