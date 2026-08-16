import asyncio
from aiohttp import web
from pyrogram import Client, idle
from config import API_ID, API_HASH, BOT_TOKEN, PORT

# Plugins Setup
plugins = dict(root="plugins")
bot = Client("StorySellerBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, plugins=plugins)

# Render Web Server Ping Handler
async def handle_ping(request):
    return web.Response(text="Render Web Server Active & Bot Online!")

async def main():
    # 1. Start Aiohttp Web Server (Render Port Binding)
    app_web = web.Application()
    app_web.router.add_get("/", handle_ping)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f" Web Server active on port {PORT}")

    # 2. Start Pyrogram Client
    await bot.start()
    print("🤖 Telegram Bot Started Successfully!")

    # 3. Keep Bot Running & Listening for Events
    await idle()
    
    # Graceful Shutdown
    await bot.stop()

if __name__ == "__main__":
    asyncio.run(main())
