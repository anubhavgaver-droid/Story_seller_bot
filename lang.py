"""
LANGUAGE system (Hindi / English) for the whole bot.

How it works
  * Each user chooses a language once (the first /start shows "Choose your language"). He can change it any time with
    /language or the 🌐 Language button of the menu. It is saved in the database (collection user_langs).
  * Every message, caption, pop-up and button the bot sends to a user who chose Hindi is translated on its way out
    (translate / translate_markup below), using the phrase list of lang_hi.py plus phrases the admin added with /addtr.
    The code of the bot does not need to know about languages. A text that is not in the list stays in English.
  * Reply-keyboard buttons (the ones whose text the handlers match) are translated from an exact table and turned back
    into the original text when the user taps them (plugins/language.py), so no handler breaks.
  * Only English and Hindi are supported for now. English users see exactly what the code wrote.

install() must be called once, AFTER richui's install(): the wrappers around Client.send_message etc. translate the text
first and then hand it to richui.
"""
import copy
import re
import time

from database.db import get_user_lang, set_user_lang, get_setting, set_setting
from style import unsc
import lang_hi

LANGS = {"en": "English", "hi": "हिंदी"}
DEFAULT = "en"
_CACHE = {}                 # user_id -> (language or None, loaded at)
_CACHE_TTL = 600
PENDING = {}                # user_id -> the /start message waiting for the user's language choice
_TAG = re.compile(r"(<[^>]*>)")
_TABLES = {"key": None, "built": 0.0, "exact": {}, "rx": None, "phrases": {}}
_EXTRA = {"t": 0.0, "v": {}}
_EXTRA_TTL = 20


# ------------------------------- the user's language -------------------------------
async def get_lang(user_id):
    """'hi' | 'en' | None (never chose)."""
    try:
        uid = int(user_id)
    except Exception:
        return None
    hit = _CACHE.get(uid)
    if hit and time.time() - hit[1] < _CACHE_TTL:
        return hit[0]
    try:
        value = await get_user_lang(uid)
    except Exception:
        value = None
    value = value if value in LANGS else None
    _CACHE[uid] = (value, time.time())
    return value


async def set_lang(user_id, code: str):
    if code not in LANGS:
        return False
    await set_user_lang(int(user_id), code)
    _CACHE[int(user_id)] = (code, time.time())
    return True


async def needs_choice(user_id) -> bool:
    return (await get_lang(user_id)) is None


async def lang_of_chat(chat_id):
    """Language for a chat: only private chats of users who chose Hindi are translated."""
    if isinstance(chat_id, int) and chat_id > 0:
        return await get_lang(chat_id)
    return None


# ------------------------------- phrase tables -------------------------------
async def _extra() -> dict:
    if time.time() - _EXTRA["t"] < _EXTRA_TTL:
        return _EXTRA["v"]
    try:
        value = await get_setting("translations_hi", {}) or {}
    except Exception:
        value = {}
    if value != _EXTRA["v"]:
        _TABLES["key"] = None                      # force a rebuild
    _EXTRA.update(t=time.time(), v=value if isinstance(value, dict) else {})
    return _EXTRA["v"]


def invalidate():
    _EXTRA["t"] = 0.0
    _TABLES["key"] = None


def _norm(text: str) -> str:
    """Small caps -> plain letters, lower case, same length as the original (so positions still match)."""
    plain = unsc(text)
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in plain)


def _build(extra: dict):
    """Single words are matched only when they are the whole text piece (so a story title is never touched);
    longer phrases are matched anywhere."""
    merged = {_norm(k).strip(): v for k, v in lang_hi.HI.items()}
    merged.update({_norm(k).strip(): v for k, v in (extra or {}).items() if k and v})
    exact, phrases, anywhere = {}, {}, set()
    for k, v in merged.items():
        if not k:
            continue
        if k.endswith("*"):                       # "hello*": this single word is translated anywhere in a text
            k = k[:-1].strip()
            anywhere.add(k)
            phrases[k] = v
        elif " " not in k and len(k) <= 14:
            exact[k] = v
        else:
            phrases[k] = v
    keys = sorted(phrases, key=len, reverse=True)
    parts = []
    for k in keys:
        pre = r"(?<![a-z0-9])" if k[0].isalnum() else ""
        post = r"(?![a-z0-9])" if (k[-1].isalnum() and k not in anywhere) else ""
        parts.append(pre + re.escape(k) + post)
    _TABLES.update(key=len(merged), built=time.time(), exact=exact, phrases=phrases,
                   rx=re.compile("|".join(parts)) if parts else None)


def _ensure():
    if _TABLES["key"] is None:
        _build(_EXTRA["v"])


_EDGE = re.compile(r"^([^a-z0-9]*)(.*?)([\s\.\!\?…]*)$", re.S)


def _segment(piece: str) -> str:
    norm = _norm(piece)
    if not re.search(r"[a-z]", norm):
        return piece
    # 1) a whole short label such as "Support", "Cancel", "Story:"
    m = _EDGE.match(norm)
    if m and m.group(2):
        core = m.group(2)
        spaced = re.sub(r"\s+:", ":", core)                    # "Story :" is the same label as "Story:"
        for cand, extra_colon in ((core, ""), (spaced, ""),
                                  (spaced.rstrip(":").rstrip(), ":" if spaced.endswith(":") else "")):
            if cand and cand in _TABLES["exact"]:
                a, b = len(m.group(1)), len(m.group(1)) + len(core)
                hindi = _TABLES["exact"][cand]
                tail = piece[b:]
                if hindi.endswith("।") and tail.lstrip().startswith("."):     # no Latin full stop after a Hindi one
                    tail = tail.replace(".", "", 1)
                return piece[:a] + hindi + extra_colon + tail
    # 2) phrases anywhere in the text
    rx = _TABLES["rx"]
    if rx is None:
        return piece
    out, last = [], 0
    for mm in rx.finditer(norm):
        out.append(piece[last:mm.start()])
        out.append(_TABLES["phrases"][mm.group(0)])
        last = mm.end()
    if not out:
        return piece
    out.append(piece[last:])
    return "".join(out)


def translate(text, lang):
    """Hindi version of a message (HTML tags are never touched). Anything else is returned unchanged."""
    if lang != "hi" or not text or not isinstance(text, str):
        return text
    _ensure()
    parts = _TAG.split(text)
    return "".join(p if i % 2 else _segment(p) for i, p in enumerate(parts))


def translate_markup(markup, lang):
    """Copy of a keyboard with Hindi button texts (the original is never changed: some keyboards are shared constants)."""
    if lang != "hi" or markup is None:
        return markup
    try:
        rows = getattr(markup, "inline_keyboard", None)
        is_reply = False
        if rows is None:
            rows = getattr(markup, "keyboard", None)
            is_reply = True
        if rows is None:
            return markup
        new_rows = []
        for row in rows:
            new_row = []
            for button in row:
                b = copy.copy(button)
                text = getattr(b, "text", None) if not isinstance(button, str) else button
                if isinstance(button, str):
                    b = lang_hi.REPLY_BUTTONS.get(button, button)
                elif isinstance(text, str):
                    if is_reply:               # reply keyboards: ONLY the exact table, handlers match the text
                        b.text = lang_hi.REPLY_BUTTONS.get(text, text)
                    else:
                        b.text = translate(text, lang)
                new_row.append(b)
            new_rows.append(new_row)
        m = copy.copy(markup)
        if is_reply:
            m.keyboard = new_rows
        else:
            m.inline_keyboard = new_rows
        return m
    except Exception as e:                      # a translation problem must never stop a message
        print(f"[lang] keyboard not translated: {type(e).__name__}: {e}")
        return markup


def translate_buttons_json(reply_markup: dict, lang):
    """For the raw Bot API keyboards of the rich cards."""
    if lang != "hi" or not reply_markup:
        return reply_markup
    try:
        rows = [[{**b, "text": translate(b.get("text", ""), lang)} for b in row] for row in reply_markup.get("inline_keyboard", [])]
        return {**reply_markup, "inline_keyboard": rows}
    except Exception:
        return reply_markup


def original_reply_text(text):
    """Hindi reply-keyboard text -> the exact text the handlers match on (or None)."""
    for original, hindi in lang_hi.REPLY_BUTTONS.items():
        if hindi == text:
            return original
    return None


# ------------------------------- the hooks around Pyrogram -------------------------------
def install():
    from pyrogram import Client
    from pyrogram.types import CallbackQuery
    if getattr(Client, "_lang_installed", False):
        return
    orig_send = Client.send_message
    orig_photo = Client.send_photo
    orig_edit = Client.edit_message_text
    orig_caption = Client.edit_message_caption
    orig_markup = Client.edit_message_reply_markup
    orig_answer = CallbackQuery.answer

    # A translation problem must NEVER stop a message: every hook falls back to the original text.
    async def send_message(self, chat_id, text, *args, **kwargs):
        try:
            if await lang_of_chat(chat_id) == "hi":
                await _extra()
                text = translate(text, "hi")
                if kwargs.get("reply_markup") is not None:
                    kwargs["reply_markup"] = translate_markup(kwargs["reply_markup"], "hi")
        except Exception as e:
            print(f"[lang] send_message not translated: {type(e).__name__}: {e}")
        return await orig_send(self, chat_id, text, *args, **kwargs)

    async def send_photo(self, chat_id, photo, *args, **kwargs):
        try:
            if await lang_of_chat(chat_id) == "hi":
                await _extra()
                if isinstance(kwargs.get("caption"), str):
                    kwargs["caption"] = translate(kwargs["caption"], "hi")
                if kwargs.get("reply_markup") is not None:
                    kwargs["reply_markup"] = translate_markup(kwargs["reply_markup"], "hi")
        except Exception as e:
            print(f"[lang] send_photo not translated: {type(e).__name__}: {e}")
        return await orig_photo(self, chat_id, photo, *args, **kwargs)

    async def edit_message_text(self, chat_id, message_id, text, *args, **kwargs):
        try:
            if await lang_of_chat(chat_id) == "hi":
                await _extra()
                text = translate(text, "hi")
                if kwargs.get("reply_markup") is not None:
                    kwargs["reply_markup"] = translate_markup(kwargs["reply_markup"], "hi")
        except Exception as e:
            print(f"[lang] edit_message_text not translated: {type(e).__name__}: {e}")
        return await orig_edit(self, chat_id, message_id, text, *args, **kwargs)

    async def edit_message_caption(self, chat_id, message_id, caption, *args, **kwargs):
        try:
            if await lang_of_chat(chat_id) == "hi":
                await _extra()
                caption = translate(caption, "hi")
                if kwargs.get("reply_markup") is not None:
                    kwargs["reply_markup"] = translate_markup(kwargs["reply_markup"], "hi")
        except Exception as e:
            print(f"[lang] edit_message_caption not translated: {type(e).__name__}: {e}")
        return await orig_caption(self, chat_id, message_id, caption, *args, **kwargs)

    async def edit_message_reply_markup(self, chat_id, message_id, *args, **kwargs):
        try:
            if await lang_of_chat(chat_id) == "hi" and kwargs.get("reply_markup") is not None:
                await _extra()
                kwargs["reply_markup"] = translate_markup(kwargs["reply_markup"], "hi")
        except Exception as e:
            print(f"[lang] keyboard not translated: {type(e).__name__}: {e}")
        return await orig_markup(self, chat_id, message_id, *args, **kwargs)

    async def answer(self, text=None, *args, **kwargs):
        try:
            if isinstance(text, str) and await get_lang(self.from_user.id) == "hi":
                await _extra()
                text = translate(text, "hi")
        except Exception:
            pass
        return await orig_answer(self, text, *args, **kwargs)

    Client.send_message = send_message
    Client.send_photo = send_photo
    Client.edit_message_text = edit_message_text
    Client.edit_message_caption = edit_message_caption
    Client.edit_message_reply_markup = edit_message_reply_markup
    CallbackQuery.answer = answer
    Client._lang_installed = True
    print("🌐 Language hooks installed (English / Hindi).")
