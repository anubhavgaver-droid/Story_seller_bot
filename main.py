import asyncio
from aiohttp import web
from pyrogram import Client, idle
from config import API_ID, API_HASH, BOT_TOKEN, PORT

# Plugins setup
plugins = dict(root="plugins")

async def handle_ping(request):
    return web.Response(text="Render Web Server Active & Bot Online!")

async def start_web_server():
    app_web = web.Application()
    app_web.router.add_get("/", handle_ping)
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
