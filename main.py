import asyncio
import os
from aiohttp import web
from pyrogram import Client, idle
from config import API_ID, API_HASH, BOT_TOKEN, PORT
from database.db import stories_col  # Clean DB reference import

# Plugins setup
plugins = dict(root="plugins")

# 1. Serve Mini App HTML File
async def handle_miniapp(request):
    html_path = os.path.join(os.path.dirname(__file__), "web", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type="text/html")
    return web.Response(text="<h3>index.html not found in web/ folder!</h3>", content_type="text/html", status=404)

# 2. API Endpoint to Fetch Stories for Mini App
async def handle_get_stories(request):
    stories = []
    async for story in stories_col.find():
        stories.append({
            "title": story.get("title", "Untitled"),
            "price": story.get("price", 0),
            "platform": story.get("platform", story.get("category", "PRATILIPI FM")),
            "desc": story.get("desc", ""),
            "photo": story.get("photo", "https://picsum.photos/200")
        })
    return web.json_response(stories)

async def start_web_server():
    app_web = web.Application()
    
    # Routes Setup
    app_web.router.add_get("/", handle_miniapp)
    app_web.router.add_get("/api/stories", handle_get_stories)
    
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 Web server active on port {PORT}")

async def main():
    # 1. Start Web Server
    await start_web_server()

    # 2. Initialize Client inside active loop
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
