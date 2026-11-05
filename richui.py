"""
Rich Messages for the WHOLE bot (Telegram Bot API 10.1+), built the same way as the working test board (bot.py).

What the user sees
  - the first line of a message becomes a big, dark <h1> heading,
  - "Label: value" lines become a <table bordered>,
  - buttons sit INSIDE the message (<tg-button-row><tg-button ...>),
  - a button press EDITS the same message instead of sending a new page.

How it is applied to every screen without rewriting every handler
  install() wraps two Pyrogram methods that every reply / edit goes through:
      Client.send_message        (message.reply_text, client.send_message ...)
      Client.edit_message_text   (message.edit_text, callback.edit_message_text ...)
  A message is converted to a Rich Message only when it is safe to do so:
      - private chat, plain text (HTML), no reply-quote / entities / protect_content / schedule
      - no markdown markers, no <pre>/<blockquote>, well-formed after conversion, short enough
      - the keyboard is an inline keyboard whose buttons are ALL callback buttons (or there is no keyboard)
  Everything else (photos and captions, URL buttons, ForceReply, the reply-keyboard main menu, group and
  channel posts, copies) goes through the normal path, untouched.

Safety
  - Any problem on the rich path falls back to the normal message with the same text and buttons.
  - A real formatting refusal from Telegram is logged and sent to the admin once. After 3 of them in a row the
    rich path is switched off until restart. Harmless errors (message not modified, a photo cannot be edited
    as text, user blocked the bot ...) are never counted.
  - Scope switch for the admin:  /richui all | admin | off | status   (also a button in /admin).
"""
import contextvars
import html as _html
import re
import time
import types as _types
from html.parser import HTMLParser

import aiohttp

from config import BOT_TOKEN, ADMIN_ID
from database.db import get_setting
from style import pretty_title, unsc

try:
    from pyrogram.errors import MessageNotModified
except Exception:  # pragma: no cover
    class MessageNotModified(Exception):
        pass

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

_STATE = {"fails": 0, "soft": 0, "admin_told": False}
MAX_FAILS = 3
MAX_SOFT_FAILS = 12
_session = None
_BYPASS = contextvars.ContextVar("richui_bypass", default=False)   # True while sending the normal fallback

# ---------------------------------------------------------------------------------------------
_HEADING_RE = re.compile(r"^\s*([^<]{0,6}?)\s*<b>(.+?)</b>(.*)$")
_KV_RE = re.compile(r"^\s*(?P<pre>\S{1,3})?\s*<b>(?P<key>[^<]+?):</b>\s*(?P<val>.+)$")
_TAG_RE = re.compile(r"<[^>]+>")
_MD_RE = re.compile(r"\*\*|__|~~|\|\||`|\]\(|--")
_UNSAFE_RE = re.compile(r"<\s*(pre|blockquote|tg-)", re.I)
_DANGER_RE = re.compile(r"\b(close|cancel|delete|remove|decline|reject|stop)\b")
_SUCCESS_RE = re.compile(r"\b(yes|make active|approve|verify)\b|turn (ads|bonus|auto pay) on")
_STYLES = {"primary", "success", "danger"}

# Errors that say "this message is not suitable", not "rich messages are broken": never counted.
_BENIGN = (
    "not modified", "not found", "no text", "can't be edited", "cannot be edited", "can't edit",
    "chat not found", "blocked", "deactivated", "forbidden", "kicked", "peer", "too many requests",
    "retry after", "flood", "message to edit", "message_id_invalid", "is not a text",
)
_FORMAT_HINTS = ("rich", "html", "tag", "parse", "entit", "unsupported", "not supported", "button", "table", "markup")

_ALLOWED_KW = {"parse_mode", "reply_markup", "disable_web_page_preview", "link_preview_options", "disable_notification"}


# ------------------------------- low level -------------------------------
async def _api(method: str, payload: dict) -> dict:
    """POST to the Bot API. Never raises: returns {"ok": False, "description": ...} on any problem."""
    global _session
    try:
        if _session is None or _session.closed:
            _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
        async with _session.post(f"{API}/{method}", json=payload) as r:
            return await r.json()
    except Exception as e:
        return {"ok": False, "description": f"{type(e).__name__}: {e}"}


# ------------------------------- switches -------------------------------
_SCOPE_CACHE = {"t": 0.0, "v": "all"}


def invalidate_scope_cache():
    _SCOPE_CACHE["t"] = 0.0


async def get_scope() -> str:
    """'all' | 'admin' | 'off'. Cached for 5 seconds so it does not hit the database for every message."""
    if time.time() - _SCOPE_CACHE["t"] < 5:
        return _SCOPE_CACHE["v"]
    if not await get_setting("rich_ui", True):
        value = "off"
    else:
        scope = await get_setting("rich_scope", "all")
        value = scope if scope in ("all", "admin", "off") else "all"
    _SCOPE_CACHE.update(t=time.time(), v=value)
    return value


async def rich_enabled() -> bool:
    """True when the admin panels may use rich messages (scope all or admin) and nothing disabled it."""
    return _STATE["fails"] < MAX_FAILS and _STATE["soft"] < MAX_SOFT_FAILS and (await get_scope()) != "off"


def _ok():
    _STATE["fails"] = 0
    _STATE["soft"] = 0


def reset_failures():
    _STATE["fails"] = 0
    _STATE["soft"] = 0
    _STATE["admin_told"] = False
    invalidate_scope_cache()


async def _scope_allows(chat_id) -> bool:
    """Rich messages only in private chats, and only for the admin when the scope is 'admin'."""
    if not isinstance(chat_id, int) or isinstance(chat_id, bool) or chat_id <= 0:
        return False
    scope = await get_scope()
    if scope == "off" or _STATE["fails"] >= MAX_FAILS or _STATE["soft"] >= MAX_SOFT_FAILS:
        return False
    return scope == "all" or chat_id == ADMIN_ID


async def _failed(where: str, description, client=None):
    """Called for an error from the Bot API. Counts only errors that are not clearly harmless."""
    desc = str(description or "")
    low = desc.lower()
    hard = low.strip() in ("not found", "bad request: method not found", "method not found")
    if not hard and any(b in low for b in _BENIGN):
        return
    if hard or any(h in low for h in _FORMAT_HINTS):
        _STATE["fails"] += 1
        print(f"[richui] {where} refused ({_STATE['fails']}/{MAX_FAILS}): {desc}")
        if _STATE["fails"] >= MAX_FAILS:
            print("[richui] Rich messages disabled until restart. Normal messages are used now.")
        if client is not None and not _STATE["admin_told"]:
            _STATE["admin_told"] = True
            await _tell_admin(client, desc)
    else:
        _STATE["soft"] += 1
        print(f"[richui] {where} error ({_STATE['soft']}/{MAX_SOFT_FAILS}): {desc}")


async def _tell_admin(client, desc: str):
    token = _BYPASS.set(True)
    try:
        await client.send_message(
            ADMIN_ID,
            "⚠️ <b>A rich message was refused by Telegram</b>\n"
            f"<code>{_html.escape(desc)[:300]}</code>\n\n"
            "The bot shows that screen as a normal message instead. Send this text to the developer. "
            "Use /richui off to stop trying."
        )
    except Exception:
        pass
    finally:
        _BYPASS.reset(token)


# ------------------------------- HTML building -------------------------------
def _kv_table(rows, headers):
    out = "<table bordered>"
    if headers:
        out += f"<tr><th>{_html.escape(headers[0])}</th><th>{_html.escape(headers[1])}</th></tr>"
    for pre, key, val in rows:
        label = f"{pre} {pretty_title(key)}".strip() if pre else pretty_title(key)
        out += f"<tr><td>{label}</td><td>{val}</td></tr>"
    return out + "</table>"


def _paragraph(lines, headers):
    """One block of lines -> HTML. Runs of 2+ 'Label: value' lines become a table, the rest stays text."""
    parts, text_run, kv_run = [], [], []

    def flush_text():
        if text_run:
            parts.append("<p>" + "<br>".join(text_run) + "</p>")
            text_run.clear()

    def flush_kv():
        if len(kv_run) >= 2:
            flush_text()
            parts.append(_kv_table(list(kv_run), headers))
        else:  # a single "Label: value" line stays normal text
            for pre, key, val in kv_run:
                text_run.append(f"{pre + ' ' if pre else ''}<b>{key}:</b> {val}")
        kv_run.clear()

    for line in lines:
        m = _KV_RE.match(line)
        if m:
            kv_run.append((m.group("pre") or "", m.group("key"), m.group("val")))
        else:
            flush_kv()
            text_run.append(line)
    flush_kv()
    flush_text()
    return "".join(parts)


def to_rich_html(text: str, notice: str = None, headers=("Setting", "Status")) -> str:
    """
    Telegram HTML text (with \\n line breaks) -> Rich HTML, without the buttons.
      first line "<emoji> <b>Title</b>rest" -> <h1>Emoji Title rest</h1>   (only when it really is a title)
      "Label: value" lines                  -> bordered table
      blank line -> new block               single newline -> <br>
    `notice` (for example "✅ saved") is shown right under the heading.
    """
    lines = (text or "").split("\n")
    heading = ""
    body_lines = lines
    m = _HEADING_RE.match(lines[0]) if lines else None
    if m:
        emoji, title, rest = m.group(1).strip(), m.group(2), m.group(3)
        # a real title: nothing before it except emoji / symbols, no trailing colon, and not a long sentence
        looks_like_title = (
            not re.search(r"[A-Za-z0-9\u0900-\u097F]", emoji)   # emoji / symbols only (note: the symbol "ℹ" counts as a letter for \w)
            and not title.rstrip().endswith(":")
            and len(_TAG_RE.sub("", rest).strip()) <= 40
        )
        if looks_like_title:
            lead = f"{emoji} " if emoji else ""
            heading = f"<h1>{lead}{pretty_title(title)}{rest}</h1>"
            body_lines = lines[1:]

    out = heading
    if notice:
        out += f"<p>{notice}</p>"
    body = "\n".join(body_lines).strip("\n")
    if body:
        for block in re.split(r"\n\s*\n", body):
            block_lines = [ln for ln in block.strip("\n").split("\n") if ln.strip()]
            if block_lines:
                out += _paragraph(block_lines, headers)

    # A bare "&" must be written as &amp; (existing entities such as &lt; or &#39; are left alone)
    return re.sub(r"&(?!#?\w+;)", "&amp;", out)


def _button_style(button, guess: bool):
    own = getattr(button, "style", None)
    if own is not None:
        name = str(getattr(own, "name", own)).lower()
        name = name.split(".")[-1]
        return name if name in _STYLES else None
    if not guess:
        return None
    data = getattr(button, "callback_data", "") or ""
    if isinstance(data, bytes):
        data = data.decode("utf-8", "ignore")
    plain = unsc(getattr(button, "text", "")).lower()
    if data in ("ap:close", "st:close") or _DANGER_RE.search(plain):
        return "danger"
    if _SUCCESS_RE.search(plain):
        return "success"
    return None


def buttons_html(markup, guess: bool = False):
    """
    Pyrogram InlineKeyboardMarkup -> <tg-button-row> blocks.
    Returns None when a button cannot be expressed (anything other than a callback button), so the caller uses the
    normal message and no button is ever lost.
    """
    if markup is None:
        return ""
    rows = getattr(markup, "inline_keyboard", None)
    if rows is None:
        rows = getattr(markup, "rows", None)
    if rows is None:
        return None            # ForceReply, reply keyboard ...
    out = ""
    for row in rows:
        cells = ""
        for b in row:
            data = getattr(b, "callback_data", None)
            if not data:
                return None
            if isinstance(data, bytes):
                data = data.decode("utf-8", "ignore")
            style = _button_style(b, guess)
            st = f' style="{style}"' if style else ""
            cells += (f'<tg-button type="callback_data"{st} data="{_html.escape(data, quote=True)}">'
                      f'{_html.escape(getattr(b, "text", ""))}</tg-button>')
        if cells:
            out += f"<tg-button-row>{cells}</tg-button-row>"
    return out


class _Balance(HTMLParser):
    """Checks that every tag we produce is closed, so Telegram never receives broken HTML."""
    VOID = {"br", "hr", "img"}

    def __init__(self):
        super().__init__()
        self.stack, self.ok = [], True

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.ok = False
        else:
            self.stack.pop()


def _well_formed(markup_html: str) -> bool:
    p = _Balance()
    try:
        p.feed(markup_html)
        p.close()
    except Exception:
        return False
    return p.ok and not p.stack


def build_message(text: str, markup, notice: str = None, headers=("Setting", "Status"), guess: bool = False):
    """Full rich HTML (content + buttons), or None when this message should not be sent as a rich message."""
    if not isinstance(text, str) or not text.strip() or len(text) > 3500:
        return None
    if _UNSAFE_RE.search(text):
        return None
    btns = buttons_html(markup, guess)
    if btns is None:
        return None
    result = to_rich_html(text, notice, headers) + btns
    return result if _well_formed(result) else None


def _plain_text(text: str, notice: str = None) -> str:
    return f"{notice}\n\n{text}" if notice else text


def _is_not_modified(desc) -> bool:
    return "not modified" in str(desc or "").lower()


# ------------------------------- "sent message" reference -------------------------------
class SentRef:
    """
    What the hook returns instead of a Pyrogram Message. The old code only ever uses .id, .delete() and
    .edit_text() on a message it just sent. Anything else is forwarded to the real Message, fetched on demand.
    """
    def __init__(self, client, chat_id, message_id):
        self._client = client
        self.id = self.message_id = message_id
        self.chat = _types.SimpleNamespace(id=chat_id)
        self.from_user = None
        self._real = None

    async def _get(self):
        if self._real is None:
            self._real = await self._client.get_messages(self.chat.id, self.id)
        return self._real

    async def delete(self, *args, **kwargs):
        return await self._client.delete_messages(self.chat.id, self.id)

    async def edit_text(self, text, *args, **kwargs):
        return await self._client.edit_message_text(self.chat.id, self.id, text, *args, **kwargs)

    async def reply_text(self, text, *args, **kwargs):
        return await self._client.send_message(self.chat.id, text, *args, **kwargs)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        async def _delegate(*args, **kwargs):
            real = await self._get()
            return await getattr(real, name)(*args, **kwargs)
        return _delegate


# ------------------------------- the global hook -------------------------------
def _kwargs_ok(kwargs: dict, text: str) -> bool:
    for key, value in kwargs.items():
        if key == "parse_mode":
            if value is not None:
                mode = str(getattr(value, "name", value)).lower()
                if "html" not in mode and "default" not in mode:
                    return False
                if "default" in mode and _MD_RE.search(text):
                    return False
            elif _MD_RE.search(text):     # default parser also reads markdown
                return False
        elif key in _ALLOWED_KW:
            continue
        elif value not in (None, False, 0):   # reply_to_message_id, protect_content, entities, schedule_date ...
            return False
    if "parse_mode" not in kwargs and _MD_RE.search(text):
        return False
    return True


async def _try_send(client, chat_id, text, kwargs):
    if _BYPASS.get() or not await _scope_allows(chat_id) or not _kwargs_ok(kwargs, text):
        return None
    rich = build_message(text, kwargs.get("reply_markup"), None, None, guess=False)
    if rich is None:
        return None
    res = await _api("sendRichMessage", {"chat_id": chat_id, "rich_message": {"html": rich}})
    if res.get("ok"):
        _ok()
        mid = (res.get("result") or {}).get("message_id")
        return SentRef(client, chat_id, mid)
    await _failed("send", res.get("description"), client)
    return None


async def _try_edit(client, chat_id, message_id, text, kwargs):
    if _BYPASS.get() or not await _scope_allows(chat_id) or not _kwargs_ok(kwargs, text):
        return None
    rich = build_message(text, kwargs.get("reply_markup"), None, None, guess=False)
    if rich is None:
        return None
    res = await _api("editMessageText", {"chat_id": chat_id, "message_id": message_id, "rich_message": {"html": rich}})
    if res.get("ok") or _is_not_modified(res.get("description")):
        _ok()
        return SentRef(client, chat_id, message_id)
    await _failed("edit", res.get("description"), client)
    return None


def install():
    """Wraps Client.send_message and Client.edit_message_text once. Safe to call more than once."""
    from pyrogram import Client

    if getattr(Client, "_richui_installed", False):
        return
    orig_send = Client.send_message
    orig_edit = Client.edit_message_text

    async def send_message(self, chat_id, text, *args, **kwargs):
        if not args:
            try:
                ref = await _try_send(self, chat_id, text, kwargs)
                if ref is not None:
                    return ref
            except Exception as e:   # the rich path must never break a normal message
                print(f"[richui] send hook error: {type(e).__name__}: {e}")
        return await orig_send(self, chat_id, text, *args, **kwargs)

    async def edit_message_text(self, chat_id, message_id, text, *args, **kwargs):
        if not args:
            try:
                ref = await _try_edit(self, chat_id, message_id, text, kwargs)
                if ref is not None:
                    return ref
            except Exception as e:
                print(f"[richui] edit hook error: {type(e).__name__}: {e}")
        return await orig_edit(self, chat_id, message_id, text, *args, **kwargs)

    Client.send_message = send_message
    Client.edit_message_text = edit_message_text
    Client._richui_installed = True
    Client._richui_originals = (orig_send, orig_edit)


# ------------------------------- explicit panels (admin) -------------------------------
async def edit_panel(callback, text: str, markup, notice: str = None, headers=("Setting", "Status")):
    """Edits the panel message the button belongs to. Replies only if it cannot be edited at all."""
    msg = callback.message
    client = getattr(msg, "_client", None)

    if await rich_enabled():
        rich = build_message(text, markup, notice, headers, guess=True)
        if rich is not None:
            res = await _api("editMessageText", {
                "chat_id": msg.chat.id, "message_id": msg.id, "rich_message": {"html": rich},
            })
            if res.get("ok") or _is_not_modified(res.get("description")):
                _ok()
                return
            await _failed("edit", res.get("description"), client)

    plain = _plain_text(text, notice)
    token = _BYPASS.set(True)
    try:
        await msg.edit_text(plain, reply_markup=markup)
        return
    except MessageNotModified:
        return
    except Exception as e:
        print(f"[richui] normal edit failed: {type(e).__name__}: {e}")
        try:
            await msg.reply_text(plain, reply_markup=markup)
        except Exception as e2:
            print(f"[richui] reply failed too: {type(e2).__name__}: {e2}")
    finally:
        _BYPASS.reset(token)


async def send_panel_to(client, chat_id, text: str, markup, notice: str = None, headers=("Setting", "Status")):
    """Sends a panel to a chat (command replies and the panel shown after a value is saved)."""
    if await rich_enabled():
        rich = build_message(text, markup, notice, headers, guess=True)
        if rich is not None:
            res = await _api("sendRichMessage", {"chat_id": chat_id, "rich_message": {"html": rich}})
            if res.get("ok"):
                _ok()
                return
            await _failed("send", res.get("description"), client)
    token = _BYPASS.set(True)
    try:
        await client.send_message(chat_id, _plain_text(text, notice), reply_markup=markup)
    finally:
        _BYPASS.reset(token)


async def send_panel(message, text: str, markup, notice: str = None, headers=("Setting", "Status")):
    """Replies to a command message with a panel."""
    client = getattr(message, "_client", None)
    if client is None:
        token = _BYPASS.set(True)
        try:
            return await message.reply_text(_plain_text(text, notice), reply_markup=markup)
        finally:
            _BYPASS.reset(token)
    await send_panel_to(client, message.chat.id, text, markup, notice, headers)
