"""
STORY CARDS (templates) - one place for every story card the bot shows or posts.

  post   the post the bot sends to the Pocket FM / Pratilipi FM channel      (plugins/post.py)
  card   the story card a user sees (mini app order, /start link, search, "view story")
                                                                              (plugins/start.py, search.py, payment.py)
  added  the "Story added successfully" message for the admin                 (plugins/admin.py)

Two looks, same content
  rich     Telegram Rich Message: photo block + bordered table (every field in its own box) + buttons under it.
  classic  the old photo + bold-text caption.
The bot uses `rich` when the admin switch /richui is on (scope all / admin) and falls back to `classic` by itself
whenever a rich message cannot be sent, so a post or a card is never lost. Per template: /tplmode.

Everything the admin sees in a card (emoji, label, shown or hidden, heading, footer) can be changed with the
commands in plugins/template.py (/template shows how). The changes are saved in the database and are used by BOTH looks.
"""
import html as _html
import time
from html.parser import HTMLParser

from config import ADMIN_ID
from database.db import get_setting, set_setting

try:
    from style import sc, pretty_title
except Exception:                                   # pragma: no cover
    def sc(t):
        return t

    def pretty_title(t):
        return t


class Raw(str):
    """A value that already is safe HTML (for example <code>link</code>). Everything else is escaped."""


# ------------------------------- what every field is called by default -------------------------------
FIELD_DEFAULTS = {
    "story":     ("♨️", "Story"),
    "status":    ("🔰", "Status"),
    "platform":  ("🖥️", "Platform"),
    "genre":     ("🧩", "Genre"),
    "episodes":  ("🎬", "Episodes"),
    "id":        ("🆔", "ID"),
    "price":     ("💰", "Price"),
    "wallet":    ("👛", "Your Wallet"),
    "free_link": ("🔗", "Free Link"),
    "demo":      ("🎬", "Demo Status"),
    "demo_ids":  ("🎧", "Demo IDs"),
    "files":     ("📦", "Files"),
    "ranges":    ("🎯", "Custom Ranges"),
    "link":      ("🔗", "Shareable Link"),
}

_STORY_GROUP = ["story", "status", "platform", "genre", "episodes", "id"]

TEMPLATES = {
    "post": {
        "name": "Channel post",
        "groups": [_STORY_GROUP, ["price"]],
        "hidden": ["id"],
        "heading": "",
        "footer": "👇 नीचे दिए गए बटन पर क्लिक करके स्टोरी अनलॉक करें:",
    },
    "card": {
        "name": "Story card (users)",
        "groups": [_STORY_GROUP, ["price"], ["wallet"]],
        "hidden": ["id"],
        "heading": "",
        "footer": "👇 Choose an option below to view or purchase:",
    },
    "added": {
        "name": "Story added (admin)",
        "groups": [_STORY_GROUP + ["free_link"], ["price"], ["demo", "demo_ids", "files", "ranges"], ["link"]],
        "hidden": ["id"],
        "heading": "✅ " + sc("Story added successfully!"),
        "footer": "",
    },
}

ALIASES = {
    "name": "story", "title": "story", "state": "status", "ep": "episodes", "episode": "episodes",
    "eps": "episodes", "storyid": "id", "cost": "price", "freelink": "free_link", "demoids": "demo_ids",
    "sharelink": "link", "share": "link",
}
MODES = ("auto", "rich", "classic")
MAX_FAILS = 3
_STATE = {"fails": 0, "told": False}
_CACHE = {"t": 0.0, "v": {}}


# ------------------------------- saved changes -------------------------------
async def _saved() -> dict:
    if time.time() - _CACHE["t"] < 5:
        return _CACHE["v"]
    value = await get_setting("story_templates", {}) or {}
    _CACHE.update(t=time.time(), v=value if isinstance(value, dict) else {})
    return _CACHE["v"]


def invalidate():
    _CACHE["t"] = 0.0


async def save_template(name: str, data: dict):
    allv = dict(await get_setting("story_templates", {}) or {})
    if data:
        allv[name] = data
    else:
        allv.pop(name, None)
    await set_setting("story_templates", allv)
    invalidate()


async def saved_for(name: str) -> dict:
    return dict((await _saved()).get(name) or {})


def resolve(name: str, raw: dict, heading=None, footer=None) -> dict:
    """The template as it looks right now: defaults + the admin's changes."""
    base = TEMPLATES[name]
    over = (raw or {}).get("fields") or {}
    groups = []
    for group in base["groups"]:
        fields = []
        for key in group:
            emoji, label = FIELD_DEFAULTS[key]
            o = over.get(key) or {}
            fields.append({
                "key": key,
                "emoji": o.get("emoji", emoji),
                "label": o.get("label", label),
                "show": o.get("show", key not in base["hidden"]),
            })
        groups.append(fields)
    if "heading" in (raw or {}):
        head = raw["heading"]
    else:
        head = heading if heading is not None else base["heading"]
    if "footer" in (raw or {}):
        foot = raw["footer"]
    else:
        foot = footer if footer is not None else base["footer"]
    return {"name": name, "groups": groups, "heading": head or "", "footer": foot or "",
            "mode": (raw or {}).get("mode", "auto") if (raw or {}).get("mode") in MODES else "auto"}


# ------------------------------- the two looks -------------------------------
def _v(value) -> str:
    return str(value) if isinstance(value, Raw) else _html.escape(str(value), quote=False)


def _visible(res: dict, values: dict):
    for group in res["groups"]:
        yield [f for f in group if f["show"] and f["key"] in values and values[f["key"]] not in (None, "")]


def render_classic(res: dict, values: dict) -> str:
    """The bold-text caption (the old look), built from the template."""
    blocks = []
    if res["heading"]:
        blocks.append(f"<b>{_html.escape(res['heading'], quote=False)}</b>")
    for group in _visible(res, values):
        lines = []
        for f in group:
            val = _v(values[f["key"]])
            emoji = f"{f['emoji']} " if f["emoji"] else ""
            label = _html.escape(f["label"], quote=False)
            if f["key"] == "price":
                lines.append(f"░▒▓█ {label.upper()} - {val} █▓▒░")
            elif f["key"] == "link":
                lines.append(f"{emoji}<b>{label}:</b>\n{val}")
            else:
                lines.append(f"{emoji}<b>{label} :</b> {val}")
        if lines:
            blocks.append("\n".join(lines))
    if res["footer"]:
        blocks.append(f"<i>{_html.escape(res['footer'], quote=False)}</i>")
    return "\n\n".join(blocks)


def render_rich(res: dict, values: dict, photo_html: str = "") -> str:
    """Rich Message HTML: photo block, optional heading, a bordered table (one box per field), footer."""
    out = photo_html
    if res["heading"]:
        out += f"<h1>{_html.escape(pretty_title(res['heading']), quote=False)}</h1>"
    rows = ""
    for group in _visible(res, values):
        for f in group:
            val = _v(values[f["key"]])
            if f["key"] in ("story", "price"):
                val = f"<b>{val}</b>"
            emoji = f"{f['emoji']} " if f["emoji"] else ""
            rows += f"<tr><td>{emoji}{_html.escape(f['label'], quote=False)}</td><td>{val}</td></tr>"
    if rows:
        out += f"<table bordered>{rows}</table>"
    if res["footer"]:
        out += f"<p><i>{_html.escape(res['footer'], quote=False)}</i></p>"
    return out


class _Balance(HTMLParser):
    VOID = {"br", "hr", "img"}

    def __init__(self):
        super().__init__()
        self.stack, self.ok = [], True

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.ok = False
        else:
            self.stack.pop()


def well_formed(markup: str) -> bool:
    p = _Balance()
    try:
        p.feed(markup)
        p.close()
    except Exception:
        return False
    return p.ok and not p.stack


async def classic_text(name: str, values: dict, heading=None, footer=None) -> str:
    """The classic caption of a template (used for text-only messages and the log channel)."""
    return render_classic(resolve(name, await saved_for(name), heading, footer), values)


# ------------------------------- buttons -> Bot API JSON -------------------------------
def markup_to_json(markup):
    """Pyrogram InlineKeyboardMarkup -> Bot API reply_markup dict. None when a button cannot be expressed."""
    if markup is None:
        return {}
    rows = getattr(markup, "inline_keyboard", None)
    if rows is None:
        return None
    out = []
    for row in rows:
        cells = []
        for b in row:
            cell = {"text": getattr(b, "text", "")}
            data = getattr(b, "callback_data", None)
            url = getattr(b, "url", None)
            web = getattr(b, "web_app", None)
            if data:
                cell["callback_data"] = data.decode("utf-8", "ignore") if isinstance(data, bytes) else str(data)
            elif url:
                cell["url"] = str(url)
            elif web is not None and getattr(web, "url", None):
                cell["web_app"] = {"url": web.url}
            else:
                return None
            style = getattr(b, "style", None)
            if style is not None:
                name = str(getattr(style, "name", style)).lower().split(".")[-1]
                if name in ("primary", "success", "danger"):
                    cell["style"] = name
            cells.append(cell)
        if cells:
            out.append(cells)
    return {"inline_keyboard": out}


# ------------------------------- sending -------------------------------
def _photo_parts(photo):
    """(img html, media list) for the rich message. Needs a link (http/https) or a Telegram file_id."""
    if not photo or not isinstance(photo, str):
        return "", []
    p = photo.strip()
    if p.startswith(("http://", "https://")):
        return f'<img src="{_html.escape(p, quote=True)}"/>', []
    if len(p) > 10:
        return '<img src="tg://photo?id=cover"/>', [{"id": "cover", "media": {"type": "photo", "media": p}}]
    return "", []


async def _use_rich(chat_id, mode: str) -> bool:
    if mode == "classic" or _STATE["fails"] >= MAX_FAILS:
        return False
    try:
        import richui
        if mode == "rich":
            return True
        if not await richui.rich_enabled():
            return False
        scope = await richui.get_scope()
        if scope == "all":
            return True
        return scope == "admin" and isinstance(chat_id, int) and chat_id == ADMIN_ID
    except Exception:
        return False


async def _tell_admin(client, text: str):
    if _STATE["told"]:
        return
    _STATE["told"] = True
    try:
        await client.send_message(
            ADMIN_ID,
            "⚠️ <b>Rich story cards could not be sent</b>\n\n"
            f"<code>{_html.escape(str(text)[:300], quote=False)}</code>\n\n"
            "The bot sends the normal (classic) card instead, nothing is lost. "
            "After 3 failures in a row the rich look pauses until the bot restarts. "
            "Send this message to the developer. Use /tplmode to choose the look yourself."
        )
    except Exception:
        pass


async def _try_rich(client, chat_id, html_body, media, markup, reply_to, quote):
    import richui
    rm = markup_to_json(markup)
    if rm is None:
        return None
    rich = {"html": html_body}
    if media:
        rich["media"] = media
    payload = {"chat_id": chat_id, "rich_message": rich}
    if rm:
        payload["reply_markup"] = rm
    if reply_to is not None and quote:
        payload["reply_parameters"] = {"message_id": reply_to.id}
    res = await richui._api("sendRichMessage", payload)
    if res.get("ok"):
        _STATE["fails"] = 0
        mid = (res.get("result") or {}).get("message_id")
        return richui.SentRef(client, chat_id, mid)
    _STATE["fails"] += 1
    desc = res.get("description")
    print(f"[cards] rich send failed ({_STATE['fails']}/{MAX_FAILS}): {desc}")
    await _tell_admin(client, desc)
    return None


async def _send_classic(client, chat_id, caption, photo, markup, reply_to, quote, fallback_photo):
    qk = {} if quote is None else {"quote": quote}

    async def send_photo(p):
        if reply_to is not None:
            return await reply_to.reply_photo(photo=p, caption=caption, reply_markup=markup, **qk)
        return await client.send_photo(chat_id=chat_id, photo=p, caption=caption, reply_markup=markup)

    async def send_text():
        if reply_to is not None:
            return await reply_to.reply_text(caption, reply_markup=markup, **qk)
        return await client.send_message(chat_id=chat_id, text=caption, reply_markup=markup)

    if photo:
        try:
            return await send_photo(photo)
        except Exception as e:
            print(f"[cards] photo send failed: {type(e).__name__}: {e}")
            if fallback_photo and fallback_photo != photo:
                try:
                    return await send_photo(fallback_photo)
                except Exception as e2:
                    print(f"[cards] fallback photo failed: {type(e2).__name__}: {e2}")
    return await send_text()


async def send_card(client, chat_id, name: str, values: dict, *, photo=None, markup=None,
                    heading=None, footer=None, reply_to=None, quote=None, fallback_photo=None):
    """
    Sends one story card. Rich message when allowed, otherwise (or when it fails) the classic photo + caption.
    `values` = {field_key: text}. `heading` / `footer` are the defaults of THIS place; the admin's own text wins.
    reply_to = the Message to reply to (keeps the old message.reply_photo behaviour).
    """
    res = resolve(name, await saved_for(name), heading, footer)
    if await _use_rich(chat_id, res["mode"]):
        try:
            photo_html, media = _photo_parts(photo)
            body = render_rich(res, values, photo_html)
            if well_formed(body):
                sent = await _try_rich(client, chat_id, body, media, markup, reply_to, quote)
                if sent is not None:
                    return sent
        except Exception as e:
            print(f"[cards] rich card error: {type(e).__name__}: {e}")
    return await _send_classic(client, chat_id, render_classic(res, values), photo, markup, reply_to, quote, fallback_photo)


async def send_text_card(client, chat_id, name: str, values: dict, *, heading=None, footer=None, markup=None, reply_to=None):
    """A card without a photo (for example the admin's 'story added' message)."""
    return await send_card(client, chat_id, name, values, photo=None, markup=markup, heading=heading, footer=footer, reply_to=reply_to)


def status() -> dict:
    return {"fails": _STATE["fails"], "paused": _STATE["fails"] >= MAX_FAILS}


def reset_failures():
    _STATE["fails"] = 0
    _STATE["told"] = False
