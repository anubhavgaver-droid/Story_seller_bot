"""
/admin (or /panel) - the complete admin panel.

Every admin job is one tap away: add / edit / delete stories, episodes, status, repost, broadcast, payment
setup, free-story ads, top-up bonus, DB channels, stats and version.
The old slash commands (/addstory, /deletestory ...) keep working exactly as before. The panel simply runs
the same handlers from buttons.
"""
import time
import html
import importlib

from pyrogram import Client, filters
try:  # defined in pyrogram/__init__.py in every Pyrogram / Kurigram release; the fallback only protects against a rename
    from pyrogram import ContinuePropagation, StopPropagation
except ImportError:  # pragma: no cover
    ContinuePropagation = StopPropagation = ()
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
    set_setting,
    send_log,
)
from style import sc
from richui import edit_panel, send_panel, rich_enabled, reset_failures

BOOT_TIME = time.time()
PAGE_SIZE = 8

# panel button -> (plugin module, handler function). These are the same handlers the slash commands use.
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

# Jobs that need an argument or a reply cannot run from a bare button, so the panel shows a short guide instead.
INFO_TEXT = {
    "broadcast": (
        f"📣 <b>{sc('Broadcast')}</b>\n\n"
        "1. Send the message you want to broadcast to this bot (or forward it).\n"
        "2. <b>Reply</b> to that message with:\n"
        "   <code>/broadcast</code>  → normal\n"
        "   <code>/broadcast -pin</code>  → also pins it"
    ),
    "addmoney": (
        f"💰 <b>{sc('Add or deduct wallet money')}</b>\n\n"
        "<code>/addmoney &lt;user_id&gt; &lt;amount&gt;</code>\n"
        "• <code>/addmoney 123456789 100</code> → adds ₹100\n"
        "• <code>/addmoney 123456789 -50</code> → deducts ₹50"
    ),
    "notifyep": (
        f"🔔 <b>{sc('Notify buyers of new episodes')}</b>\n\n"
        "<code>/notifyep Story Title | Episode 51-100</code>"
    ),
    "setkey": (
        f"🔑 <b>{sc('Set a key, UPI ID or ads value by command')}</b>\n\n"
        "<code>/setkey demotry api_key VALUE</code>\n"
        "<code>/setkey razorpay key_id VALUE</code>\n"
        "<code>/setkey upi yourname@bank</code>\n"
        "<code>/setkey ads api_url VALUE</code>\n"
        "<code>/setkey bonus percent 10</code>\n\n"
        "This always works, even if a button prompt does not."
    ),
}

HELP_TEXT = (
    f"❓ <b>{sc('All admin commands')}</b>\n\n"
    f"<b>{sc('Stories')}</b>\n"
    "/addstory, /allstories, /editname, /setepisodes, /changestatus\n"
    "/addepisodes, /markcomplete, /deletestory, /refreshstories\n"
    "/repoststory, /repost\n\n"
    f"<b>{sc('Users')}</b>\n"
    "/broadcast, /notifyep, /addmoney, /stats\n\n"
    f"<b>{sc('Payments, ads and bonus')}</b>\n"
    "/setup, /setkey, /autopay, /dbchannels\n\n"
    f"<b>{sc('Other')}</b>\n"
    "/admin (this panel), /version, /cancel"
)


def _btn(text, data):
    return InlineKeyboardButton(text, callback_data=data)


class _CmdShim:
    """
    Makes a button press look like a command message, so the existing command handlers
    (which use message.from_user, message.command and message.reply_text) run unchanged.
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
    try:
        await fn(client, _CmdShim(callback, cmd))
    except (ContinuePropagation, StopPropagation):
        # Some old handlers end with message.continue_propagation(); that is normal, not an error.
        pass


async def _show(callback, text, markup, notice=None):
    """Edits the panel message in place (never sends a new page unless editing is impossible)."""
    await edit_panel(callback, text, markup, notice)


# ------------------------------- PANELS -------------------------------
def _home_panel():
    text = (
        f"🛠 <b>{sc('Admin panel')}</b>  <code>v{VERSION}</code>\n\n"
        "Choose what you want to do. Each button runs the same job as its command.\n"
        "<i>To stop a running job: Stories → Cancel action.</i>"
    )
    rows = [
        [_btn(f"📚 {sc('Stories')}", "ap:sec:stories"), _btn(f"👥 {sc('Users')}", "ap:sec:users")],
        [_btn(f"💳 {sc('Payments')}", "ap:sec:pay"), _btn(f"🎁 {sc('Free & ads')}", "st:ads")],
        [_btn(f"📊 {sc('Stats')}", "ap:stats"), _btn(f"ℹ️ {sc('Version & help')}", "ap:ver")],
        [_btn(f"✨ {sc('Big headings on/off')}", "ap:rich")],
        [_btn(f"❌ {sc('Close')}", "ap:close")],
    ]
    return text, InlineKeyboardMarkup(rows)


def _section_panel(sec: str):
    if sec == "stories":
        text = f"📚 <b>{sc('Stories')}</b>\n\nAdd, edit, episodes, status, delete and repost."
        rows = [
            [_btn(f"➕ {sc('Add story')}", "ap:run:addstory"), _btn(f"📋 {sc('All stories')}", "ap:run:allstories")],
            [_btn(f"✏️ {sc('Edit name')}", "ap:run:editname"), _btn(f"🔢 {sc('Set episodes')}", "ap:run:setepisodes")],
            [_btn(f"🔰 {sc('Change status')}", "ap:run:changestatus"), _btn(f"🆕 {sc('Add episodes')}", "ap:run:addepisodes")],
            [_btn(f"✅ {sc('Mark complete')}", "ap:run:markcomplete"), _btn(f"🗑 {sc('Delete story')}", "ap:dl:0")],
            [_btn(f"📤 {sc('Repost one')}", "ap:run:repoststory"), _btn(f"📤 {sc('Repost all')}", "ap:rpall")],
            [_btn(f"🔄 {sc('Refresh stories')}", "ap:run:refreshstories"), _btn(f"❌ {sc('Cancel action')}", "ap:run:cancel")],
            [_btn(f"⬅️ {sc('Back')}", "ap:home")],
        ]
    elif sec == "users":
        text = f"👥 <b>{sc('Users')}</b>"
        rows = [
            [_btn(f"📣 {sc('Broadcast')}", "ap:info:broadcast"), _btn(f"🔔 {sc('Notify episode')}", "ap:info:notifyep")],
            [_btn(f"💰 {sc('Add or deduct money')}", "ap:info:addmoney"), _btn(f"📊 {sc('Stats')}", "ap:stats")],
            [_btn(f"⬅️ {sc('Back')}", "ap:home")],
        ]
    else:  # pay
        text = f"💳 <b>{sc('Payments')}</b>\n\nGateways, UPI ID, Auto Pay, top-up bonus and DB channels."
        rows = [
            [_btn(f"⚙️ {sc('Full setup')}", "st:home"), _btn(f"💳 {sc('Gateways')}", "st:gws")],
            [_btn(f"⚡ {sc('Auto pay on/off')}", "st:toggle"), _btn(f"🏦 {sc('UPI ID')}", "st:upi")],
            [_btn(f"💰 {sc('Top-up bonus')}", "st:bonus"), _btn(f"📡 {sc('DB channels')}", "ap:run:dbchannels")],
            [_btn(f"🔑 {sc('Setkey guide')}", "ap:info:setkey")],
            [_btn(f"⬅️ {sc('Back')}", "ap:home")],
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
        nav.append(_btn(f"⏪ {sc('Prev')}", f"ap:dl:{page - 1}"))
    if page < pages - 1:
        nav.append(_btn(f"{sc('Next')} ⏩", f"ap:dl:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([_btn(f"⬅️ {sc('Back')}", "ap:sec:stories")])

    if total:
        text = (
            f"🗑 <b>{sc('Delete story')}</b>  (page {page + 1} of {pages}, {total} in total)\n\n"
            "Tap the story you want to delete. You will be asked to confirm first."
        )
    else:
        text = f"🗑 <b>{sc('No stories found')}</b>"
    return text, InlineKeyboardMarkup(rows)


def _fmt_money(pair):
    amount, count = pair
    return f"₹{amount:g} ({count} orders)"


async def _stats_text():
    st = await get_stats()
    maintenance = await get_setting("auto_pay_maintenance", True)
    top = "\n".join(f"  {i}. {html.escape(str(t))} — {n}" for i, (t, n) in enumerate(st["top_stories"], 1)) or "  —"
    return (
        f"📊 <b>{sc('Stats')}</b>  <code>v{VERSION}</code>\n\n"
        f"👥 <b>{sc('Users')}:</b> {st['users_total']}  (today +{st['users_today']}, 7 days +{st['users_week']})\n"
        f"📚 <b>{sc('Stories')}:</b> {st['stories_total']}  (free: {st['stories_free']})\n"
        f"🛒 <b>{sc('Purchases')}:</b> {st['purchases_total']}  (today {st['purchases_today']}, 7 days {st['purchases_week']})\n"
        f"🎁 <b>{sc('Free claims via ads')}:</b> {st['free_claims']}\n"
        f"👛 <b>{sc('Total in user wallets')}:</b> ₹{st['wallet_total']:g}\n\n"
        f"💰 <b>{sc('Gateway revenue')}</b> <i>(only money received through the gateway)</i>\n"
        f"  • Today: {_fmt_money(st['rev_today'])}\n"
        f"  • 7 days: {_fmt_money(st['rev_week'])}\n"
        f"  • 30 days: {_fmt_money(st['rev_month'])}\n"
        f"  • Orders created today: {st['orders_today']}\n\n"
        f"🏆 <b>{sc('Top stories')}</b>\n{top}\n\n"
        f"⚡ Auto Pay: {'🛠 Maintenance' if maintenance else '✅ ON'}   |   📡 DB channels: {len(DB_CHANNEL_IDS)}"
    )


def _version_text():
    uptime = int(time.time() - BOOT_TIME)
    h, rem = divmod(uptime, 3600)
    m, _ = divmod(rem, 60)
    lines = [
        f"ℹ️ <b>{sc('Bot version')}:</b> <code>v{VERSION}</code>",
        f"🤖 @{BOT_USERNAME}",
        f"⏱ Uptime: {h}h {m}m",
        "",
        f"<b>{sc('Changelog')}</b>",
    ]
    for ver, items in CHANGELOG:
        lines.append(f"\n<b>v{ver}</b>")
        lines.extend(f"• {it}" for it in items)
    return "\n".join(lines)


# ------------------------------- COMMANDS -------------------------------
@Client.on_message(filters.command(["admin", "panel"]) & filters.user(ADMIN_ID) & filters.private, group=1)
async def admin_panel_command(client, message):
    text, markup = _home_panel()
    await send_panel(message, text, markup)


@Client.on_message(filters.command("stats") & filters.user(ADMIN_ID) & filters.private, group=1)
async def stats_command(client, message):
    await send_panel(message, await _stats_text(), InlineKeyboardMarkup([[_btn(f"🏠 {sc('Admin panel')}", "ap:home")]]))


@Client.on_message(filters.command("version") & filters.user(ADMIN_ID) & filters.private, group=1)
async def version_command(client, message):
    await send_panel(message, _version_text(), InlineKeyboardMarkup([[_btn(f"🏠 {sc('Admin panel')}", "ap:home")]]))


@Client.on_message(filters.command("richui") & filters.user(ADMIN_ID) & filters.private, group=1)
async def richui_command(client, message):
    """/richui  -> status   |   /richui on   |   /richui off   (big real headings in /admin and /setup)"""
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    if arg in ("on", "off"):
        await set_setting("rich_ui", arg == "on")
        reset_failures()
    state = await rich_enabled()
    await message.reply_text(
        f"✨ <b>{sc('Big headings')}:</b> {'✅ ON' if state else '❌ OFF'}\n\n"
        "<code>/richui on</code>  → big headings in /admin and /setup\n"
        "<code>/richui off</code> → normal messages only\n\n"
        "<i>If a panel ever looks wrong, send /richui off.</i>"
    )


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

    # ---- big headings on / off ----
    if action == "rich":
        current = bool(await get_setting("rich_ui", True))
        await set_setting("rich_ui", not current)
        reset_failures()
        await callback.answer("Big headings are ON." if not current else "Big headings are OFF.", show_alert=True)
        text, markup = _home_panel()
        return await _show(callback, text, markup)

    # ---- run an existing command from a button ----
    if action == "run":
        cmd = parts[2]
        if cmd not in COMMANDS:
            return await callback.answer("Command not found.", show_alert=True)
        await callback.answer()
        try:
            await _run_command(client, callback, cmd)
        except Exception as e:
            print(f"[admin panel] /{cmd} failed: {type(e).__name__}: {e}")
            await callback.message.reply_text(f"❌ <b>/{cmd} failed:</b> <code>{html.escape(str(e))[:200]}</code>")
        return

    # ---- guide text ----
    if action == "info":
        key = parts[2]
        back = "ap:sec:pay" if key == "setkey" else "ap:sec:users"
        return await _show(callback, INFO_TEXT.get(key, "—"), InlineKeyboardMarkup([[_btn(f"⬅️ {sc('Back')}", back)]]))

    # ---- stats / version / help ----
    if action == "stats":
        await callback.answer("Loading...")
        return await _show(callback, await _stats_text(), InlineKeyboardMarkup([
            [_btn(f"🔄 {sc('Refresh')}", "ap:stats")], [_btn(f"⬅️ {sc('Back')}", "ap:home")]
        ]))

    if action == "ver":
        return await _show(callback, _version_text(), InlineKeyboardMarkup([
            [_btn(f"❓ {sc('All commands')}", "ap:help")], [_btn(f"⬅️ {sc('Back')}", "ap:home")]
        ]))

    if action == "help":
        return await _show(callback, HELP_TEXT, InlineKeyboardMarkup([[_btn(f"⬅️ {sc('Back')}", "ap:ver")]]))

    # ---- repost all (with confirmation) ----
    if action == "rpall":
        stories = await get_all_stories()
        text = (
            f"📤 <b>{sc('Repost all')}</b>\n\n<b>{len(stories)}</b> stories will be posted to the channel again, "
            "with a 3-minute gap between posts. Are you sure?"
        )
        return await _show(callback, text, InlineKeyboardMarkup([
            [_btn(f"✅ {sc('Yes, start')}", "ap:rpy"), _btn(f"⬅️ {sc('No')}", "ap:sec:stories")]
        ]))

    if action == "rpy":
        await callback.answer("Reposting started...")
        try:
            await _run_command(client, callback, "repost")
        except Exception as e:
            await callback.message.reply_text(f"❌ <b>Repost failed:</b> <code>{html.escape(str(e))[:200]}</code>")
        return

    # ---- delete: list -> confirm -> delete ----
    if action == "dl":
        text, markup = await _delete_list(int(parts[2]))
        return await _show(callback, text, markup)

    if action == "dc":
        story = await get_story_by_key(parts[2])
        if not story:
            return await callback.answer("Story not found (already deleted?).", show_alert=True)
        title = html.escape((story.get("title") or "").strip().split("\n")[0])
        text = (
            f"⚠️ <b>{sc('Delete this story?')}</b>\n\n📖 <b>{title}</b>\n\n"
            "The story and its buyers' records will be removed from the database. "
            "<i>Files in the DB channel are not deleted.</i>"
        )
        return await _show(callback, text, InlineKeyboardMarkup([
            [_btn(f"✅ {sc('Yes, delete')}", f"ap:dy:{story['story_id']}")],
            [_btn(f"⬅️ {sc('No, go back')}", "ap:dl:0")],
        ]))

    if action == "dy":
        story = await get_story_by_key(parts[2])
        if not story:
            return await callback.answer("Story not found.", show_alert=True)
        title = (story.get("title") or "").strip().split("\n")[0]
        deleted = await delete_story_db(title)
        await callback.answer("Deleted." if deleted else "Could not delete.", show_alert=True)
        if deleted:
            try:
                await send_log(client, f"🗑 <b>{sc('Story deleted (admin panel)')}</b>\n\n📖 {html.escape(title)}")
            except Exception:
                pass
        text, markup = await _delete_list(0)
        return await _show(callback, text, markup)

    await callback.answer()
