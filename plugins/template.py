"""
Admin commands to change how the story cards look (post in the channel, card for users, "story added" message).

  /template                          all templates and their mode
  /template post                     every field of one template, with the exact commands to change it
  /tplemoji   <tpl> <field> <emoji>  change the emoji of a field            (use "none" to remove it)
  /tpllabel   <tpl> <field> <text>   change the text of a field              (Status -> Current State)
  /tplshow    <tpl> <field> on|off   show or hide a field                    (for example the story ID)
  /tplheading <tpl> <text|off>       big heading above the card
  /tplfooter  <tpl> <text|off>       line under the card
  /tplmode    <tpl> auto|rich|classic  auto = follows /richui, rich = boxes, classic = the old bold text
  /tplreset   <tpl> [field]          back to the default look
  /tplpreview <tpl>                  sends you a preview (with a sample button)
  /tplstyle   success 1|2|3          look of the "purchase successful" card (1 celebration, 2 receipt, 3 cover)
  /tplstream  <tpl> on|off           Stream button in the success / owned card

<tpl> = post | card | added | success | owned
<field> = story status platform genre episodes id price wallet paid method balance order_id date bought_on ...
"""
import html as _html

from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import cards
from config import ADMIN_ID
from database.db import get_all_stories

TPL_ALIASES = {"channel": "post", "users": "card", "user": "card", "admin": "added", "add": "added",
               "bought": "success", "buy": "success", "purchase": "success", "own": "owned", "already": "owned"}
COMMANDS = ["template", "tplemoji", "tpllabel", "tplshow", "tplheading", "tplfooter", "tplmode", "tplreset", "tplpreview",
            "tplstyle", "tplstream"]
E = lambda s: _html.escape(str(s), quote=False)


def _tpl(arg):
    arg = (arg or "").lower()
    arg = TPL_ALIASES.get(arg, arg)
    return arg if arg in cards.TEMPLATES else None


def _field(tpl, arg):
    key = cards.ALIASES.get((arg or "").lower(), (arg or "").lower())
    for group in cards.TEMPLATES[tpl]["groups"]:
        if key in group:
            return key
    return None


def _field_names(tpl):
    return ", ".join(k for g in cards.TEMPLATES[tpl]["groups"] for k in g)


def _usage():
    return (
        "<b>How to change a card</b>\n\n"
        "<code>/tplemoji post status 🟢</code>  (emoji of a field, <code>none</code> removes it)\n"
        "<code>/tpllabel post episodes Total Parts</code>  (text of a field)\n"
        "<code>/tplshow post id on</code>  (show or hide a field)\n"
        "<code>/tplheading post 🔥 New Story</code>  (heading, <code>off</code> removes it)\n"
        "<code>/tplfooter post Tap Buy Now 👇</code>  (line under the card)\n"
        "<code>/tplmode post auto</code>  (auto | rich | classic)\n"
        "<code>/tplreset post</code>  (back to default)\n"
        "<code>/tplpreview post</code>  (see it)\n"
        "<code>/tplstyle success 2</code>  (look of the purchase-success card: 1, 2 or 3)\n"
        "<code>/tplstream success off</code>  (hide the Stream button)\n\n"
        "Templates: <code>post</code> = channel post, <code>card</code> = story card for users, "
        "<code>added</code> = story added (admin), <code>success</code> = purchase successful card, "
        "<code>owned</code> = already purchased card."
    )


async def _describe(tpl):
    res = cards.resolve(tpl, await cards.saved_for(tpl))
    lines = [
        f"🧩 <b>Template: {E(cards.TEMPLATES[tpl]['name'])}</b>\n",
        f"<b>Mode:</b> {res['mode']}",
        f"<b>Heading:</b> {E(res['heading']) or '—'}",
        f"<b>Footer:</b> {E(res['footer']) or '—'}",
    ]
    if tpl == "success":
        lines.append(f"<b>Style:</b> {res['style']}  (1 celebration · 2 receipt · 3 cover photo)")
    if tpl in ("success", "owned"):
        lines.append(f"<b>Stream button:</b> {'on' if res['stream'] else 'off'}")
    for group in res["groups"]:
        for f in group:
            lines.append(f"<b>{E(f['key'])}:</b> {E(f['emoji']) or '(no emoji)'} · {E(f['label'])} · {'shown' if f['show'] else 'hidden'}")
    lines.append("")
    lines.append(f"Fields: <code>{_field_names(tpl)}</code>")
    lines.append(f"Try: <code>/tplemoji {tpl} status 🟢</code> then <code>/tplpreview {tpl}</code>")
    return "\n".join(lines)


async def _sample(tpl):  # returns (values, photo, story)
    """Sample values built from the newest story (or made-up ones), shaped like the real cards."""
    story = {}
    try:
        stories = await get_all_stories()
        story = stories[0] if stories else {}
    except Exception:
        pass
    title = (story.get("title") or "Sample Story Name").strip().splitlines()[0]
    price = story.get("price", 49)
    price_text = "FREE 🎁" if not price else f"₹{price}"
    values = {
        "user": cards.mention(1, "Rahul"),
        "story": title,
        "status": story.get("status") or "Completed",
        "platform": story.get("platform") or story.get("category") or "Pocket FM",
        "genre": story.get("genre") or "Drama",
        "episodes": story.get("episodes") or "120",
        "id": story.get("story_id") or "ab12cd34",
        "price": price_text,
        "wallet": "₹0",
        "free_link": story.get("free_link") or "N/A",
        "demo": "✅ Enabled",
        "demo_ids": "[12, 40]",
        "files": "120 (Msg 1 to 120)",
        "ranges": "2 Configured",
        "link": cards.Raw("<code>https://t.me/YourBot?start=story_ab12cd34</code>"),
        "paid": price_text,
        "method": "Wallet",
        "balance": "₹120",
        "order_id": "ord_8f3a21",
        "date": cards.fmt_time(),
        "bought_on": cards.fmt_time(),
    }
    return values, story.get("photo"), story


def _only_admin():
    return filters.command(COMMANDS) & filters.user(ADMIN_ID) & filters.private


@Client.on_message(_only_admin())
async def template_commands(client, message):
    cmd = message.command[0].lower()
    args = message.command[1:]

    if cmd == "template":
        tpl = _tpl(args[0]) if args else None
        if tpl:
            return await message.reply_text(await _describe(tpl))
        lines = ["🧩 <b>Story templates</b>\n"]
        for name, base in cards.TEMPLATES.items():
            mode = cards.resolve(name, await cards.saved_for(name))["mode"]
            lines.append(f"<b>{name}:</b> {E(base['name'])} · {mode}")
        lines.append("")
        lines.append("<code>/template post</code> shows every field of a template.\n")
        lines.append(_usage())
        st = cards.status()
        if st["paused"]:
            lines.append("\n⚠️ The rich look is paused (it failed 3 times). It starts again after a restart or <code>/tplmode post rich</code>.")
        return await message.reply_text("\n".join(lines))

    tpl = _tpl(args[0]) if args else None
    if not tpl:
        return await message.reply_text("❌ Tell me the template: <code>post</code>, <code>card</code> or <code>added</code>.\n\n" + _usage())
    raw = await cards.saved_for(tpl)

    if cmd == "tplpreview":
        values, photo, story = await _sample(tpl)
        cards.reset_failures()
        if tpl in ("success", "owned"):
            values["user"] = cards.mention(message.from_user.id, message.from_user.first_name)
            sample_story = dict(story or {})
            sample_story.setdefault("story_id", "preview")
            markup = await cards.story_buttons(tpl, sample_story, "https://t.me", account=(tpl == "success"))
            await cards.send_event_card(client, message.chat.id, tpl, values, photo=photo, markup=markup)
            return
        markup = None
        if tpl in ("post", "card"):
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Buy Now (sample)", style=enums.ButtonStyle.PRIMARY, url="https://t.me")],
            ])
        await cards.send_card(client, message.chat.id, tpl, values, photo=photo, markup=markup)
        return

    if cmd == "tplstyle":
        if tpl != "success":
            return await message.reply_text("❌ Styles exist only for the purchase-success card: <code>/tplstyle success 1</code> (or 2, 3)")
        style = (args[1] if len(args) > 1 else "").strip()
        if style not in cards.STYLES:
            return await message.reply_text("❌ Use <code>/tplstyle success 1</code>, <code>2</code> or <code>3</code>\n"
                                            "1 = celebration (Hindi box open) · 2 = receipt · 3 = cover photo")
        raw["style"] = style
        cards.reset_failures()
        await cards.save_template(tpl, raw)
        return await message.reply_text(f"✅ Success card style: <b>{style}</b>\nSee it: <code>/tplpreview success</code>")

    if cmd == "tplstream":
        if tpl not in ("success", "owned"):
            return await message.reply_text("❌ The Stream button is in <code>success</code> and <code>owned</code> only.")
        value = (args[1] if len(args) > 1 else "").lower()
        if value not in ("on", "off"):
            return await message.reply_text(f"❌ Example: <code>/tplstream {tpl} off</code>")
        raw["stream"] = value == "on"
        await cards.save_template(tpl, raw)
        return await message.reply_text(f"✅ Stream button in <b>{tpl}</b>: <b>{value}</b>")

    if cmd == "tplreset":
        if len(args) >= 2:
            key = _field(tpl, args[1])
            if not key:
                return await message.reply_text(f"❌ Unknown field. Fields: <code>{_field_names(tpl)}</code>")
            (raw.get("fields") or {}).pop(key, None)
            await cards.save_template(tpl, raw)
            return await message.reply_text(f"✅ <b>{key}</b> is back to default in <b>{tpl}</b>.")
        await cards.save_template(tpl, {})
        return await message.reply_text(f"✅ Template <b>{tpl}</b> is back to the default look.")

    if cmd == "tplmode":
        mode = (args[1] if len(args) > 1 else "").lower()
        if mode not in cards.MODES:
            return await message.reply_text("❌ Use: <code>/tplmode post auto</code> · <code>rich</code> · <code>classic</code>\n"
                                            "auto = follows /richui, rich = boxes, classic = old bold text")
        raw["mode"] = mode
        cards.reset_failures()
        await cards.save_template(tpl, raw)
        return await message.reply_text(f"✅ <b>{tpl}</b> mode: <b>{mode}</b>\nSee it: <code>/tplpreview {tpl}</code>")

    if cmd in ("tplheading", "tplfooter"):
        key = "heading" if cmd == "tplheading" else "footer"
        text = " ".join(args[1:]).strip()
        if not text:
            return await message.reply_text(f"❌ Example: <code>/{cmd} {tpl} Your text</code>  (<code>off</code> removes it)")
        if len(text) > 120:
            return await message.reply_text("❌ Maximum 120 characters.")
        raw[key] = "" if text.lower() in ("off", "none", "-") else text
        await cards.save_template(tpl, raw)
        return await message.reply_text(f"✅ {key} of <b>{tpl}</b>: <b>{E(raw[key]) or 'removed'}</b>\nSee it: <code>/tplpreview {tpl}</code>")

    # field commands: /tplemoji /tpllabel /tplshow
    key = _field(tpl, args[1]) if len(args) > 1 else None
    if not key:
        return await message.reply_text(f"❌ Tell me the field. Fields of <b>{tpl}</b>: <code>{_field_names(tpl)}</code>\n\n" + _usage())
    value = " ".join(args[2:]).strip()
    if not value:
        return await message.reply_text(f"❌ Missing value.\n\n" + _usage())
    fields = dict(raw.get("fields") or {})
    cur = dict(fields.get(key) or {})

    if cmd == "tplemoji":
        cur["emoji"] = "" if value.lower() in ("none", "off", "-") else value[:12]
        note = f"emoji of <b>{key}</b>: {E(cur['emoji']) or 'removed'}"
    elif cmd == "tpllabel":
        if len(value) > 40:
            return await message.reply_text("❌ Maximum 40 characters.")
        cur["label"] = value
        note = f"text of <b>{key}</b>: <b>{E(value)}</b>"
    else:  # tplshow
        if value.lower() not in ("on", "off", "yes", "no", "show", "hide"):
            return await message.reply_text(f"❌ Example: <code>/tplshow {tpl} {key} on</code> or <code>off</code>")
        cur["show"] = value.lower() in ("on", "yes", "show")
        note = f"<b>{key}</b> is now {'shown' if cur['show'] else 'hidden'}"

    fields[key] = cur
    raw["fields"] = fields
    await cards.save_template(tpl, raw)
    await message.reply_text(f"✅ {note} in <b>{tpl}</b>.\nSee it: <code>/tplpreview {tpl}</code>")
