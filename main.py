import asyncio
from aiohttp import web
from pyrogram import Client
from config import API_ID, API_HASH, BOT_TOKEN, PORT

plugins = dict(root="plugins")
bot = Client("StorySellerBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, plugins=plugins)

async def handle_ping(request):
    return web.Response(text="Render Web Server Active & Bot Online!")

async def start_services():
    app_web = web.Application()
    app_web.router.add_get("/", handle_ping)
    
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    await bot.start()
    print("Bot is successfully running...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(start_services())
    except KeyboardInterrupt:
        pass
