"""
Random emoji reactions: remembers the user's newest message and gives the admin controls.

  /reactions                      status and help
  /reactions on | off             switch all reactions
  /reactions event <name> on|off  start | search | story | range | payment
  /reactions list 🔥 👍 🎉        choose the emoji the bot picks from (only Telegram's reaction emoji work)
  /reactions reset                back to the default emoji
  /reactions test                 the bot reacts to your command so you can see it
"""
import html as _html

from pyrogram import Client, filters

import reactions
from config import ADMIN_ID

E = lambda s: _html.escape(str(s), quote=False)


@Client.on_message(filters.private, group=-80)
async def remember_last_message(client, message):
    """Runs before every handler. Only stores the message id (used for the 'payment verified' reaction)."""
    try:
        if message.from_user and not message.from_user.is_bot:
            reactions.remember_user_message(message.from_user.id, message.id)
    except Exception:
        pass


@Client.on_message(filters.command("reactions") & filters.user(ADMIN_ID) & filters.private)
async def reactions_command(client, message):
    args = message.command[1:]
    cfg = await reactions.get_config()
    sub = (args[0].lower() if args else "")

    if sub in ("on", "off"):
        cfg["enabled"] = sub == "on"
        await reactions.save_config(cfg)
        return await message.reply_text(f"✅ Reactions are now <b>{sub}</b>.")

    if sub == "event":
        name = (args[1].lower() if len(args) > 1 else "")
        value = (args[2].lower() if len(args) > 2 else "")
        if name not in reactions.EVENTS or value not in ("on", "off"):
            return await message.reply_text("❌ Example: <code>/reactions event payment off</code>\nEvents: <code>" + " ".join(reactions.EVENTS) + "</code>")
        cfg["events"][name] = value == "on"
        await reactions.save_config(cfg)
        return await message.reply_text(f"✅ <b>{name}</b> ({reactions.EVENTS[name]}): <b>{value}</b>")

    if sub == "list":
        chosen = reactions.clean_pool(" ".join(args[1:]).replace(",", " ").split())
        if not chosen:
            return await message.reply_text(
                "❌ Send the emoji after the command, for example <code>/reactions list 🔥 👍 🎉 😍</code>\n"
                "Only Telegram's reaction emoji work:\n" + " ".join(reactions.ALLOWED))
        cfg["pool"], cfg["custom_pool"] = chosen, True
        await reactions.save_config(cfg)
        return await message.reply_text("✅ The bot will pick from: " + " ".join(chosen))

    if sub == "reset":
        cfg["pool"], cfg["custom_pool"] = list(reactions.DEFAULT_POOL), False
        await reactions.save_config(cfg)
        return await message.reply_text("✅ Back to the default emoji:\n" + " ".join(reactions.DEFAULT_POOL))

    if sub == "test":
        reactions._COOL.clear()
        ok = await reactions.react(client, message.chat.id, message.id, "start", big=True)
        if ok:
            return
        return await message.reply_text("⚠️ No reaction was set. Check <code>/reactions</code>: it must be on and the event <b>start</b> on. "
                                        "If it is, Telegram refused it, see the logs.")

    lines = [
        "😀 <b>Random emoji reactions</b>\n",
        f"<b>Status:</b> {'on' if cfg['enabled'] else 'off'}",
    ]
    for name, text in reactions.EVENTS.items():
        lines.append(f"<b>{name}:</b> {'on' if cfg['events'][name] else 'off'}  ({text})")
    lines.append(f"<b>Emoji:</b> {' '.join(cfg['pool'])}" + ("" if cfg["custom_pool"] else "  (default)"))
    lines.append("")
    lines.append("<code>/reactions on</code> · <code>/reactions off</code>\n"
                 "<code>/reactions event payment off</code>\n"
                 "<code>/reactions list 🔥 👍 🎉</code> · <code>/reactions reset</code>\n"
                 "<code>/reactions test</code>")
    await message.reply_text("\n".join(lines))
