import asyncio
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import parse_qsl
from datetime import datetime, timezone, timedelta
from aiohttp import web
import aiofiles
from pyrogram import Client, idle
from config import API_ID, API_HASH, BOT_TOKEN, PORT, BOT_USERNAME, LOG_CHANNEL
from database.db import (
    stories_col, get_user_purchases, get_story_by_title, verified_orders_col,
    init_db, get_payment_order, delivery_link, demo_link
)
from gateway import check_order_status
from version import VERSION
from fulfill import fulfill_order


# Plugins setup
plugins = dict(root="plugins")

# Base Directory Path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")

# Pyrogram Bot Client Instance Reference
bot_instance = None

# Secret key from Render Environment Variables
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

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

# ------------------ 3. Webhook Handler for demotry.shop (/paytm) ------------------
async def _process_webhook_order(order_id: str):
    """Background me: provider API se status confirm karke order poora karo."""
    try:
        order = await get_payment_order(order_id)
        if not order or order.get("status") == "PAID":
            return

        is_paid, paid_amt, msg = await check_order_status(order_id)
        if not is_paid:
            print(f"ℹ️ Webhook for {order_id}: provider says not paid yet ({msg})")
            return

        await verified_orders_col.update_one(
            {"order_id": order_id},
            {"$set": {
                "order_id": order_id,
                "amount": paid_amt,
                "status": "PAID",
                "timestamp": datetime.now(timezone.utc)
            }},
            upsert=True
        )

        if bot_instance is None:
            print(f"⚠️ Webhook: bot abhi ready nahi, {order_id} Verify button se poora hoga")
            return

        result = await fulfill_order(bot_instance, order, paid_amt, "WEBHOOK")
        print(f"✅ Webhook order {order_id} -> {result}")
    except Exception as e:
        print(f"❌ Webhook processing error for {order_id}: {e}")


_ORDER_ID_RE = re.compile(r"ORD_\d+_\d+_[0-9a-f]{6}")


def _collect_order_ids(obj, found: set):
    """Webhook JSON me kahin bhi hamara order_id ho to nikaal lo (Demotry / Razorpay / Cashfree ka format alag hai)."""
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_order_ids(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _collect_order_ids(v, found)
    elif isinstance(obj, str):
        found.update(_ORDER_ID_RE.findall(obj))


async def handle_paytm_webhook(request):
    """
    /paytm, /webhook/razorpay, /webhook/cashfree - teeno yahin aate hain.
    SECURITY: webhook body par bharosa nahi. Sirf wahi order_id chalega jo hamare bot ne banaya hai,
    aur PAID tabhi mana jayega jab gateway ki apni API (hamari key ke saath) bhi paid bataye.
    """
    try:
        # Handle CORS OPTIONS request
        if request.method == 'OPTIONS':
            return web.Response(status=200)

        raw = await request.read()
        try:
            data = json.loads(raw.decode("utf-8", errors="ignore"))
        except Exception:
            data = {}
        print(f"📩 Webhook ({request.path}) payload: {str(data)[:500]}")

        found = set()
        _collect_order_ids(data, found)
        if not found:
            return web.json_response({"status": "ignored", "reason": "no order id"}, status=200)

        accepted = []
        for oid in found:
            if await get_payment_order(oid):
                asyncio.create_task(_process_webhook_order(oid))
                accepted.append(oid)

        if not accepted:
            return web.json_response({"status": "ignored", "reason": "unknown order"}, status=200)
        return web.json_response({"status": "accepted", "orders": accepted}, status=200)

    except Exception as e:
        print(f"❌ Website Webhook Error: {e}")
        return web.json_response({"error": "bad request"}, status=400)

# ------------------ 4. API Endpoint: Fetch Stories ------------------
async def handle_get_stories(request):
    stories = []
    try:
        async for story in stories_col.find():
            raw_title = story.get("title", "Untitled")
            clean_title = raw_title.strip().splitlines()[0] if raw_title else "Untitled"
            story_id = str(story.get("story_id") or story.get("_id", ""))
            
            first_id = story.get("first_msg_id")
            last_id = story.get("last_msg_id")
            if first_id and last_id and last_id >= first_id:
                total_files_count = (last_id - first_id) + 1
            else:
                total_files_count = len(story.get("custom_ranges", [])) * 50 or 24

            stories.append({
                "id": story_id,
                "story_id": story_id,
                "title": clean_title,
                "price": story.get("price", 0),
                "platform": story.get("platform", story.get("category", "PRATILIPI FM")),
                "episodes": story.get("episodes", "N/A"),
                "total_files": f"{total_files_count} files",
                "desc": story.get("desc", story.get("description", "")),
                "photo": story.get("photo", "https://picsum.photos/200"),
                "demo_enabled": story.get("demo_enabled", False),
                "demo_msg_ids": story.get("demo_msg_ids", []),
                "demo_link": demo_link(story_id),
                "link": delivery_link(story_id)
            })
        return web.json_response(stories)
    except Exception as e:
        print(f"Error fetching stories: {e}")
        return web.json_response({"error": str(e)}, status=500)

# ------------------ 5. API Endpoint: User Purchases ------------------
def verify_init_data(init_data: str, bot_token: str, max_age: int = 86400):
    """
    Checks the signed Telegram Mini App "initData" string (HMAC-SHA256 with the bot token).
    Returns the Telegram user dict when it is genuine and not older than max_age seconds, otherwise None.
    This is what proves WHO is calling the API, so nobody can read another user's purchases.
    """
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            return None
        if time.time() - int(pairs.get("auth_date", "0")) > max_age:
            return None
        user = json.loads(pairs.get("user", "{}"))
        return user if user.get("id") else None
    except Exception:
        return None


async def handle_get_user_purchases(request):
    # The user is identified ONLY from the signed initData (a plain user_id in the URL is ignored).
    tg_user = verify_init_data(request.query.get("init_data", ""), BOT_TOKEN)
    if not tg_user:
        return web.json_response({"error": "unauthorized"}, status=401)

    purchases_data = []
    try:
        purchases = await get_user_purchases(int(tg_user["id"]))
        for item in purchases:
            story = await get_story_by_title(item.get('story_title', ''))
            sid = item.get("story_id") or (story.get("story_id") if story else None)
            purchases_data.append({
                "story_title": item.get('story_title', 'Untitled'),
                "story_id": str(sid) if sid else None,
                "link": delivery_link(sid) if sid else "#"
            })
    except Exception as e:
        print(f"Error fetching purchases for web app: {e}")

    return web.json_response(purchases_data)

# ------------------ Start Web Server ------------------
async def start_web_server():
    app_web = web.Application(middlewares=[cors_middleware])
    
    app_web.router.add_get("/ping", handle_ping)
    app_web.router.add_get("/", handle_miniapp)
    
    # 🎯 Only Website Webhook Route (/paytm)
    app_web.router.add_post("/paytm", handle_paytm_webhook)
    app_web.router.add_options("/paytm", handle_paytm_webhook)

    # Razorpay / Cashfree webhooks (same secure handler)
    for _p in ("/webhook/razorpay", "/webhook/cashfree", "/webhook/demotry"):
        app_web.router.add_post(_p, handle_paytm_webhook)
        app_web.router.add_options(_p, handle_paytm_webhook)
    
    app_web.router.add_get("/api/stories", handle_get_stories)
    app_web.router.add_get("/api/user_purchases", handle_get_user_purchases)

    if os.path.exists(WEB_DIR):
        app_web.router.add_static("/web/", path=WEB_DIR, name="web")

    runner = web.AppRunner(app_web)
    await runner.setup()
    
    server_port = int(PORT) if PORT else 8080
    site = web.TCPSite(runner, "0.0.0.0", server_port)
    await site.start()
    print(f"🌐 Server active on port {server_port}")

# ------------------ Main Execution ------------------
async def main():
    global bot_instance
    await init_db()
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
    print(f"🤖 Telegram Bot v{VERSION} Started Successfully! (@{bot_info.username})")

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
                f"⚙️ <b>Version:</b> <code>v{VERSION}</code>\n"
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
