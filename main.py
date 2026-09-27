import asyncio
import os
import re
from datetime import datetime, timezone, timedelta
from aiohttp import web
import aiofiles
from pyrogram import Client, idle, filters
from config import API_ID, API_HASH, BOT_TOKEN, PORT, ADMIN_ID, BOT_USERNAME, LOG_CHANNEL
from database.db import stories_col, get_user_purchases, get_story_by_title, verified_orders_col


# Plugins setup
plugins = dict(root="plugins")

# Base Directory Path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")

# Pyrogram Bot Client Instance Reference
bot_instance = None

# ------------------ Middleware: CORS Headers ------------------
@web.middleware
async def cors_middleware(request, handler):
    response = await handler(request)
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# ------------------ 1. Ping / Health-Check ------------------
async def handle_ping(request):
    return web.Response(text="PONG / SERVER OK", status=200)

# ------------------ 2. Serve Mini App HTML File (Index) ------------------
async def handle_miniapp(request):
    html_path = os.path.join(WEB_DIR, "index.html")
    if os.path.exists(html_path):
        async with aiofiles.open(html_path, mode="r", encoding="utf-8") as f:
            content = await f.read()
            return web.Response(text=content, content_type="text/html")
    return web.Response(text="<h3>index.html not found in web/ folder!</h3>", content_type="text/html", status=404)

# ------------------ 3. MacroDroid Webhook Handler ------------------
async def handle_macrodroid_webhook(request):
    try:
        data = await request.json()
        notif_text = data.get("notification_text", "")
        
        # FamPay Notification madhun Order ID Extract Karne (e.g. FAMPAY2026092514001350BE74B1)
        match = re.search(r'(FAMPAY[A-Z0-9]+)', notif_text)
        if match:
            order_id = match.group(1)
            
            # Database madhe status PAID save karne
            await verified_orders_col.update_one(
                {"order_id": order_id},
                {"$set": {
                    "order_id": order_id,
                    "status": "PAID",
                    "raw_text": notif_text,
                    "timestamp": datetime.now(timezone.utc)
                }},
                upsert=True
            )
            print(f"✅ Webhook Payment Received & Saved: {order_id}")
            return web.json_response({"status": "success", "order_id": order_id})
            
        return web.json_response({"status": "ignored", "reason": "No Order ID found"}, status=400)
    except Exception as e:
        print(f"❌ Webhook Error: {e}")
        return web.json_response({"error": str(e)}, status=500)

# ------------------ 4. API Endpoint: Fetch Stories ------------------
async def handle_get_stories(request):
    stories = []
    try:
        async for story in stories_col.find():
            raw_title = story.get("title", "Untitled")
            clean_title = raw_title.strip().splitlines()[0] if raw_title else "Untitled"
            url_clean_title = clean_title.replace(" ", "_")
            
            first_id = story.get("first_msg_id")
            last_id = story.get("last_msg_id")
            if first_id and last_id and last_id >= first_id:
                total_files_count = (last_id - first_id) + 1
            else:
                total_files_count = len(story.get("custom_ranges", [])) * 50 or 24

            stories.append({
                "id": str(story.get("_id", "")),
                "title": clean_title,
                "price": story.get("price", 0),
                "platform": story.get("platform", story.get("category", "PRATILIPI FM")),
                "episodes": story.get("episodes", "N/A"),
                "total_files": f"{total_files_count} files",
                "desc": story.get("desc", story.get("description", "")),
                "photo": story.get("photo", "https://picsum.photos/200"),
                "demo_enabled": story.get("demo_enabled", False),
                "demo_msg_ids": story.get("demo_msg_ids", []),
                "demo_link": f"https://t.me/{BOT_USERNAME}?start=demo_{url_clean_title}"
            })
        return web.json_response(stories)
    except Exception as e:
        print(f"Error fetching stories: {e}")
        return web.json_response({"error": str(e)}, status=500)

# ------------------ 5. API Endpoint: User Purchases ------------------
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
    
    app_web.router.add_get("/ping", handle_ping)
    app_web.router.add_get("/", handle_miniapp)
    app_web.router.add_post("/webhook", handle_macrodroid_webhook)
    app_web.router.add_get("/api/stories", handle_get_stories)
    app_web.router.add_get("/api/user_purchases", handle_get_user_purchases)

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
    global bot_instance
    await start_web_server()

    bot_instance = Client(
        "StorySellerBot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        plugins=plugins
    )

    await bot_instance.start()
    bot_info = await bot_instance.get_me()
    print(f"🤖 Telegram Bot Started Successfully! (@{bot_info.username})")

    if LOG_CHANNEL and LOG_CHANNEL != 0:
        try:
            ist_offset = timezone(timedelta(hours=5, minutes=30))
            now = datetime.now(ist_offset)
            time_str = now.strftime("%I:%M:%S %p")
            date_str = now.strftime("%d %B %Y")

            restart_msg = (
                f"🚀 <b>ʙᴏᴛ ʀᴇsᴛᴀʀᴛᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
                f"🤖 <b>Bot Name:</b> {bot_info.first_name}\n"
                f"🔖 <b>Username:</b> @{bot_info.username}\n"
                f"⚙️ <b>Version:</b> <code>v2.0</code>\n"
                f"📅 <b>Date:</b> <code>{date_str}</code>\n"
                f"⏰ <b>Time:</b> <code>{time_str} (IST)</code>\n"
                f"🟢 <b>Status:</b> Online & Ready!"
            )
            await bot_instance.send_message(chat_id=LOG_CHANNEL, text=restart_msg)
        except Exception as e:
            print(f"Failed to send restart log: {e}")

    await idle()
    await bot_instance.stop()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
