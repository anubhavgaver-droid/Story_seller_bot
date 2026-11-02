"""
/admin  (ya /panel)  -  Poora Admin Panel.

Har admin kaam ek button se: Add / Edit / Delete story, episodes, status, repost, broadcast,
payment setup, free-story ads, DB channels, stats, version.
Purane commands (/addstory, /deletestory ...) pehle ki tarah chalte rahenge; panel bas unhe buttons se chalata hai.
"""
import time
import html
import importlib

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_ID, BOT_USERNAME, DB_CHANNEL_IDS
from version import VERSION, CHANGELOG
from database.db import (
    get_all_stories,
    get_story_by_key,
    delete_story_db,
    get_stats,
    get_setting,
    send_log,
)

BOOT_TIME = time.time()
PAGE_SIZE = 8

# panel button -> (plugin module, handler function). Ye wahi handlers hain jo slash-commands chalate hain.
COMMANDS = {
    "addstory": ("plugins.admin", "start_add"),
    "allstories": ("plugins.admin", "list_stories"),
    "editname": ("plugins.admin", "start_edit_name"),
    "setepisodes": ("plugins.admin", "start_edit_episodes"),
    "changestatus": ("plugins.admin", "start_change_status"),
    "addepisodes": ("plugins.admin", "start_add_episodes_wizard"),
    "markcomplete": ("plugins.admin", "start_mark_complete"),
    "refreshstories": ("plugins.admin", "refresh_all_stories"),
    "cancel": ("plugins.admin", "cancel_action"),
    "repoststory": ("plugins.post", "start_repost_single_story"),
    "repost": ("plugins.post", "handle_repost_command"),
    "dbchannels": ("plugins.settings", "dbchannels_command"),
}

# Jin kaamo me argument / reply chahiye, unke liye guide text (button se command seedha nahi chalta)
INFO_TEXT = {
    "broadcast": (
        "📣 <b>Broadcast</b>\n\n"
        "1. Jo message sabko bhejna hai use bot me bhejein (ya forward karein).\n"
        "2. Us message par <b>Reply</b> karke likhein:\n"
        "   <code>/broadcast</code>  → normal\n"
        "   <code>/broadcast -pin</code>  → pin bhi hoga"
    ),
    "addmoney": (
        "💰 <b>User ke wallet me paise jodna / ghatana</b>\n\n"
        "<code>/addmoney &lt;user_id&gt; &lt;amount&gt;</code>\n"
        "• <code>/addmoney 123456789 100</code> → ₹100 jode\n"
        "• <code>/addmoney 123456789 -50</code> → ₹50 kate"
    ),
    "notifyep": (
        "🔔 <b>Naye episode ka notification (sirf kharidne walon ko)</b>\n\n"
        "<code>/notifyep Story Title | Episode 51-100</code>"
    ),
    "setkey": (
        "🔑 <b>Key / UPI / Ads value seedha command se</b>\n\n"
        "<code>/setkey demotry api_key VALUE</code>\n"
        "<code>/setkey razorpay key_id VALUE</code>\n"
        "<code>/setkey upi yourname@bank</code>\n"
        "<code>/setkey ads api_url VALUE</code>\n\n"
        "Button se value accept na ho to ye hamesha chalta hai."
    ),
}

HELP_TEXT = (
    "❓ <b>Saare Admin Commands</b>\n\n"
    "<b>📚 Stories</b>\n"
    "/addstory, /allstories, /editname, /setepisodes, /changestatus\n"
    "/addepisodes, /markcomplete, /deletestory, /refreshstories\n"
    "/repoststory, /repost\n\n"
    "<b>👥 Users</b>\n"
    "/broadcast, /notifyep, /addmoney, /stats\n\n"
    "<b>💳 Payments & Ads</b>\n"
    "/setup (gateway, UPI, Auto Pay, Free Story Ads), /setkey, /autopay, /dbchannels\n\n"
    "<b>🛠 Other</b>\n"
    "/admin (ye panel), /version, /cancel"
)


def _btn(text, data):
    return InlineKeyboardButton(text, callback_data=data)


class _CmdShim:
    """
    Callback ko 'command message' jaisa dikhata hai, taaki purane command handlers (jo message.from_user,
    message.command, message.reply_text use karte hain) bina badlaav button se chal sakein.
    """
    def __init__(self, callback, cmd):
        self._m = callback.message
        self.from_user = callback.from_user
        self.chat = callback.message.chat
        self.text = f"/{cmd}"
        self.command = [cmd]
        self.reply_to_message = None
        self.id = callback.message.id

    def __getattr__(self, name):
        return getattr(self._m, name)


async def _run_command(client, callback, cmd):
    mod_name, fn_name = COMMANDS[cmd]
    fn = getattr(importlib.import_module(mod_name), fn_name)
    await fn(client, _CmdShim(callback, cmd))


async def _show(callback, text, markup):
    try:
        await callback.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except MessageNotModified:
        pass
    except Exception:
        await callback.message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)


# ------------------------------- PANELS -------------------------------
def _home_panel():
    text = (
        f"🛠 <b>ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ</b>  <code>v{VERSION}</code>\n\n"
        "Neeche se jo kaam karna hai wo chunein. Har button wahi kaam karta hai jo uska command karta.\n"
        "<i>Chalte hue kaam ko rokne ke liye: Stories → ❌ Cancel.</i>"
    )
    rows = [
        [_btn("📚 Stories", "ap:sec:stories"), _btn("👥 Users & Broadcast", "ap:sec:users")],
        [_btn("💳 Payments", "ap:sec:pay"), _btn("🎁 Free & Ads", "st:ads")],
        [_btn("📊 Stats", "ap:stats"), _btn("ℹ️ Version & Help", "ap:ver")],
        [_btn("❌ Close", "ap:close")],
    ]
    return text, InlineKeyboardMarkup(rows)


def _section_panel(sec: str):
    if sec == "stories":
        text = "📚 <b>Stories</b>\n\nAdd, edit, episodes, status, delete aur repost yahin se."
        rows = [
            [_btn("➕ Add Story", "ap:run:addstory"), _btn("📋 All Stories", "ap:run:allstories")],
            [_btn("✏️ Edit Name", "ap:run:editname"), _btn("🔢 Set Episodes", "ap:run:setepisodes")],
            [_btn("🔰 Change Status", "ap:run:changestatus"), _btn("🆕 Add Episodes", "ap:run:addepisodes")],
            [_btn("✅ Mark Complete", "ap:run:markcomplete"), _btn("🗑 Delete Story", "ap:dl:0")],
            [_btn("📤 Repost One", "ap:run:repoststory"), _btn("📤 Repost All", "ap:rpall")],
            [_btn("🔄 Refresh Stories", "ap:run:refreshstories"), _btn("❌ Cancel Action", "ap:run:cancel")],
            [_btn("⬅️ Back", "ap:home")],
        ]
    elif sec == "users":
        text = "👥 <b>Users & Broadcast</b>"
        rows = [
            [_btn("📣 Broadcast", "ap:info:broadcast"), _btn("🔔 Notify Episode", "ap:info:notifyep")],
            [_btn("💰 Add / Deduct Money", "ap:info:addmoney"), _btn("📊 Stats", "ap:stats")],
            [_btn("⬅️ Back", "ap:home")],
        ]
    else:  # pay
        text = "💳 <b>Payments</b>\n\nGateway, UPI, Auto Pay aur DB channels."
        rows = [
            [_btn("⚙️ Payment Setup (full)", "st:home"), _btn("💳 Gateways", "st:gws")],
            [_btn("⚡ Auto Pay ON/OFF", "st:toggle"), _btn("🏦 UPI ID", "st:upi")],
            [_btn("📡 DB Channels", "ap:run:dbchannels"), _btn("🔑 /setkey guide", "ap:info:setkey")],
            [_btn("⬅️ Back", "ap:home")],
        ]
    return text, InlineKeyboardMarkup(rows)


async def _delete_list(page: int):
    stories = await get_all_stories()
    stories = [s for s in stories if s.get("story_id")]
    stories.sort(key=lambda s: (s.get("title") or "").lower())
    total = len(stories)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))

    rows = []
    for s in stories[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
        title = (s.get("title") or "Untitled").strip().split("\n")[0]
        rows.append([_btn(f"🗑 {title[:40]}", f"ap:dc:{s['story_id']}")])

    nav = []
    if page > 0:
        nav.append(_btn("⏪ Prev", f"ap:dl:{page - 1}"))
    if page < pages - 1:
        nav.append(_btn("Next ⏩", f"ap:dl:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([_btn("⬅️ Back", "ap:sec:stories")])

    text = (
        f"🗑 <b>Story Delete</b>  (Page {page + 1}/{pages}, kul {total})\n\n"
        "Jo story delete karni hai uspe tap karein. Confirm poochhne ke baad hi delete hogi."
        if total else "🗑 <b>Koi story nahi mili.</b>"
    )
    return text, InlineKeyboardMarkup(rows)


def _fmt_money(pair):
    amount, count = pair
    return f"₹{amount:g} ({count} orders)"


async def _stats_text():
    st = await get_stats()
    maintenance = await get_setting("auto_pay_maintenance", True)
    top = "\n".join(f"  {i}. {html.escape(str(t))} — {n}" for i, (t, n) in enumerate(st["top_stories"], 1)) or "  —"
    return (
        f"📊 <b>Stats</b>  <code>v{VERSION}</code>\n\n"
        f"👥 <b>Users:</b> {st['users_total']}  (aaj +{st['users_today']}, 7 din +{st['users_week']})\n"
        f"📚 <b>Stories:</b> {st['stories_total']}  (free: {st['stories_free']})\n"
        f"🛒 <b>Purchases:</b> {st['purchases_total']}  (aaj {st['purchases_today']}, 7 din {st['purchases_week']})\n"
        f"🎁 <b>Free claims (ad se):</b> {st['free_claims']}\n"
        f"👛 <b>Users ke wallet me kul:</b> ₹{st['wallet_total']:g}\n\n"
        f"💰 <b>Gateway kamai</b> <i>(sirf gateway se aaya paisa)</i>\n"
        f"  • Aaj: {_fmt_money(st['rev_today'])}\n"
        f"  • 7 din: {_fmt_money(st['rev_week'])}\n"
        f"  • 30 din: {_fmt_money(st['rev_month'])}\n"
        f"  • Aaj bane orders: {st['orders_today']}\n\n"
        f"🏆 <b>Top stories</b>\n{top}\n\n"
        f"⚡ Auto Pay: {'🛠 Maintenance' if maintenance else '✅ ON'}   |   📡 DB channels: {len(DB_CHANNEL_IDS)}"
    )


def _version_text():
    uptime = int(time.time() - BOOT_TIME)
    h, rem = divmod(uptime, 3600)
    m, _ = divmod(rem, 60)
    lines = [f"ℹ️ <b>Bot Version:</b> <code>v{VERSION}</code>", f"🤖 @{BOT_USERNAME}", f"⏱ Uptime: {h}h {m}m", "", "<b>Changelog</b>"]
    for ver, items in CHANGELOG:
        lines.append(f"\n<b>v{ver}</b>")
        lines.extend(f"• {it}" for it in items)
    return "\n".join(lines)


# ------------------------------- COMMANDS -------------------------------
@Client.on_message(filters.command(["admin", "panel"]) & filters.user(ADMIN_ID) & filters.private, group=1)
async def admin_panel_command(client, message):
    text, markup = _home_panel()
    await message.reply_text(text, reply_markup=markup)


@Client.on_message(filters.command("stats") & filters.user(ADMIN_ID) & filters.private, group=1)
async def stats_command(client, message):
    await message.reply_text(await _stats_text(), reply_markup=InlineKeyboardMarkup([[_btn("🏠 Admin Panel", "ap:home")]]))


@Client.on_message(filters.command("version") & filters.user(ADMIN_ID) & filters.private, group=1)
async def version_command(client, message):
    await message.reply_text(_version_text(), reply_markup=InlineKeyboardMarkup([[_btn("🏠 Admin Panel", "ap:home")]]))


# ------------------------------- CALLBACKS -------------------------------
@Client.on_callback_query(filters.regex(r"^ap:") & filters.user(ADMIN_ID))
async def admin_panel_callbacks(client, callback):
    parts = callback.data.split(":")
    action = parts[1]

    if action == "home":
        text, markup = _home_panel()
        return await _show(callback, text, markup)

    if action == "close":
        try:
            await callback.message.delete()
        except Exception:
            pass
        return await callback.answer()

    if action == "sec":
        text, markup = _section_panel(parts[2])
        return await _show(callback, text, markup)

    # ---- purana command button se chalana ----
    if action == "run":
        cmd = parts[2]
        if cmd not in COMMANDS:
            return await callback.answer("❌ Command nahi mila", show_alert=True)
        await callback.answer()
        try:
            await _run_command(client, callback, cmd)
        except Exception as e:
            print(f"[admin panel] /{cmd} failed: {type(e).__name__}: {e}")
            await callback.message.reply_text(f"❌ <b>/{cmd} chalane me dikkat:</b> <code>{html.escape(str(e))[:200]}</code>")
        return

    # ---- guide text ----
    if action == "info":
        key = parts[2]
        back = "ap:sec:pay" if key == "setkey" else "ap:sec:users"
        return await _show(callback, INFO_TEXT.get(key, "—"), InlineKeyboardMarkup([[_btn("⬅️ Back", back)]]))

    # ---- stats / version / help ----
    if action == "stats":
        await callback.answer("📊 Load ho raha hai...")
        return await _show(callback, await _stats_text(), InlineKeyboardMarkup([
            [_btn("🔄 Refresh", "ap:stats")], [_btn("⬅️ Back", "ap:home")]
        ]))

    if action == "ver":
        return await _show(callback, _version_text(), InlineKeyboardMarkup([
            [_btn("❓ Saare Commands", "ap:help")], [_btn("⬅️ Back", "ap:home")]
        ]))

    if action == "help":
        return await _show(callback, HELP_TEXT, InlineKeyboardMarkup([[_btn("⬅️ Back", "ap:ver")]]))

    # ---- Repost All (confirm) ----
    if action == "rpall":
        stories = await get_all_stories()
        text = (
            f"📤 <b>Repost All</b>\n\nKul <b>{len(stories)}</b> stories chanel par dobara post hongi, "
            "har post ke beech 3 minute ka gap. Pakka?"
        )
        return await _show(callback, text, InlineKeyboardMarkup([
            [_btn("✅ Haan, shuru karein", "ap:rpy"), _btn("⬅️ Nahi", "ap:sec:stories")]
        ]))

    if action == "rpy":
        await callback.answer("📤 Repost shuru...")
        try:
            await _run_command(client, callback, "repost")
        except Exception as e:
            await callback.message.reply_text(f"❌ Repost me dikkat: <code>{html.escape(str(e))[:200]}</code>")
        return

    # ---- Delete: list -> confirm -> delete ----
    if action == "dl":
        text, markup = await _delete_list(int(parts[2]))
        return await _show(callback, text, markup)

    if action == "dc":
        story = await get_story_by_key(parts[2])
        if not story:
            return await callback.answer("❌ Story nahi mili (pehle hi delete?)", show_alert=True)
        title = html.escape((story.get("title") or "").strip().split("\n")[0])
        text = (
            f"⚠️ <b>Pakka delete karein?</b>\n\n📖 <b>{title}</b>\n\n"
            "Story aur uske kharidne walon ka record database se hat jayega. "
            "<i>DB channel ki files delete nahi hoti.</i>"
        )
        return await _show(callback, text, InlineKeyboardMarkup([
            [_btn("✅ Haan, delete karo", f"ap:dy:{story['story_id']}")],
            [_btn("⬅️ Nahi, wapas", "ap:dl:0")],
        ]))

    if action == "dy":
        story = await get_story_by_key(parts[2])
        if not story:
            return await callback.answer("❌ Story nahi mili", show_alert=True)
        title = (story.get("title") or "").strip().split("\n")[0]
        deleted = await delete_story_db(title)
        await callback.answer("✅ Delete ho gayi" if deleted else "❌ Delete nahi hui", show_alert=True)
        if deleted:
            try:
                await send_log(client, f"🗑 <b>Story deleted (admin panel)</b>\n\n📖 {html.escape(title)}")
            except Exception:
                pass
        text, markup = await _delete_list(0)
        return await _show(callback, text, markup)

    await callback.answer()
