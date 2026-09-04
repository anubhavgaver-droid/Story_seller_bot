import asyncio
import os
from aiohttp import web
import aiofiles  # Async file reading ke liye
from pyrogram import Client, idle
from config import API_ID, API_HASH, BOT_TOKEN, PORT
from database.db import stories_col, get_user_purchases, get_story_by_title

# Plugins setup
plugins = dict(root="plugins")

# Base Directory Path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")

# ------------------ Middleware: CORS Headers ------------------
@web.middleware
async def cors_middleware(request, handler):
    response = await handler(request)
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# ------------------ 1. Ping / Health-Check (For Cron-Job) ------------------
async def handle_ping(request):
    return web.Response(text="PONG / SERVER OK", status=200)

# ------------------ 2. Serve Mini App HTML File ------------------
async def handle_miniapp(request):
    html_path = os.path.join(WEB_DIR, "index.html")
    if os.path.exists(html_path):
        async with aiofiles.open(html_path, mode="r", encoding="utf-8") as f:
            content = await f.read()
            return web.Response(text=content, content_type="text/html")
    return web.Response(text="<h3>index.html not found in web/ folder!</h3>", content_type="text/html", status=404)

# ------------------ 3. API Endpoint: Fetch Stories ------------------
async def handle_get_stories(request):
    stories = []
    try:
        async for story in stories_col.find():
            raw_title = story.get("title", "Untitled")
            clean_title = raw_title.strip().splitlines()[0] if raw_title else "Untitled"
            
            stories.append({
                "title": clean_title,
                "price": story.get("price", 0),
                "platform": story.get("platform", story.get("category", "PRATILIPI FM")),
                "desc": story.get("desc", ""),
                "photo": story.get("photo", "https://picsum.photos/200")
            })
        return web.json_response(stories)
    except Exception as e:
        print(f"Error fetching stories: {e}")
        return web.json_response({"error": str(e)}, status=500)

# ------------------ 4. API Endpoint: User Purchases ------------------
async def handle_get_user_purchases(request):
    user_id = request.query.get("user_id")
    purchases_data = []
    if user_id:
        try:
            purchases = await get_user_purchases(int(user_id))
            for item in purchases:
                story = await get_story_by_title(item.get('story_title', ''))
                purchases_data.append({
                    "story_title": item.get('story_title', 'Untitled'),
                    "link": story.get("link", "#") if story else "#"
                })
        except Exception as e:
            print(f"Error fetching purchases for web app: {e}")
            
    return web.json_response(purchases_data)

# ------------------ Start Web Server ------------------
async def start_web_server():
    app_web = web.Application(middlewares=[cors_middleware])
    
    # Routes Setup
    app_web.router.add_get("/ping", handle_ping)          # For Cron Job Keep-Alive
    app_web.router.add_get("/", handle_miniapp)            # Mini App Index
    app_web.router.add_get("/api/stories", handle_get_stories)
    app_web.router.add_get("/api/user_purchases", handle_get_user_purchases)
    
    # Static files serving (CSS, JS, Images from web/ folder)
    if os.path.exists(WEB_DIR):
        app_web.router.add_static("/web/", path=WEB_DIR, name="web")

    runner = web.AppRunner(app_web)
    await runner.setup()
    
    server_port = int(PORT) if PORT else 8080
    site = web.TCPSite(runner, "0.0.0.0", server_port)
    await site.start()
    print(f"🌐 Advanced Web server active on port {server_port}")

# ------------------ Main Execution ------------------
async def main():
    # 1. Start Web Server
    await start_web_server()

    # 2. Initialize Pyrogram Client
    bot = Client(
        "StorySellerBot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        plugins=plugins
    )

    # 3. Start Pyrogram Bot
    await bot.start()
    print("🤖 Telegram Bot Started Successfully!")

    # 4. Keep alive
    await idle()

    # 5. Stop Bot on exit
    await bot.stop()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
