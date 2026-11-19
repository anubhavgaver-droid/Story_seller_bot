"""
RANDOM EMOJI REACTIONS

The bot puts a random emoji reaction (👍 🔥 🎉 ...) on the user's message at the moments the admin chose:

    start    the user sends /start
    search   the user types a keyword to search a story
    story    the user picks a story (checkout card) or orders from the mini app
    range    the user selects a file range / full delivery
    payment  a payment is verified and the story is unlocked (any way: gateway, UTR, wallet, admin approval, free claim)

Rules (Telegram): a bot can set ONE reaction per message and only from Telegram's standard reaction set (ALLOWED below).
Reactions are only used in private chats and never stop or slow down anything: they are sent in the background and every
error is ignored. Admin control: /reactions (plugins/reactions.py).
"""
import asyncio
import random
import time

from database.db import get_setting, set_setting

# Telegram's standard reaction emoji (the only ones a bot may use).
ALLOWED = [
    "👍", "👎", "❤", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱", "🤬", "😢", "🎉", "🤩", "🤮", "💩", "🙏", "👌", "🕊", "🤡",
    "🥱", "🥴", "😍", "🐳", "❤‍🔥", "🌚", "🌭", "💯", "🤣", "⚡", "🍌", "🏆", "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕", "😈",
    "😴", "😭", "🤓", "👻", "👨‍💻", "👀", "🎃", "🙈", "😇", "😨", "🤝", "✍", "🤗", "🫡", "🎅", "🎄", "☃", "💅", "🤪", "🗿",
    "🆒", "💘", "🙉", "🦄", "😘", "💊", "🙊", "😎", "👾", "🤷‍♂", "🤷", "🤷‍♀", "😡",
]
# Happy ones only, by default.
DEFAULT_POOL = ["👍", "🔥", "🥰", "👏", "😁", "🎉", "🤩", "🙏", "👌", "😍", "💯", "⚡", "🏆", "😎", "🤗", "🫡", "🆒", "💘", "😘", "🍓", "🐳", "👀"]

EVENTS = {
    "start": "/start",
    "search": "keyword search",
    "story": "story selected / mini app order",
    "range": "file range selected",
    "payment": "payment verified / story unlocked",
}
COOLDOWN = 1.5            # seconds between two reactions of the same kind in one chat (no spam, no flood limits)
LAST_MESSAGE_TTL = 24 * 3600
OWN_FAILS_LIMIT = 5       # reacting to the bot's own message not allowed? stop trying after this many failures in a row

_CFG = {"t": 0.0, "v": None}
_COOL = {}
_LAST_MSG = {}            # user_id -> (message id, time)  (the user's newest message in the bot chat)
_TASKS = set()
_OWN = {"fails": 0}


def _plain(emoji: str) -> str:
    return (emoji or "").replace("\ufe0f", "").strip()


def clean_pool(items) -> list:
    """Only emoji that Telegram allows as a reaction, without repeats, in the given order."""
    allowed = {_plain(e): e for e in ALLOWED}
    out = []
    for item in items:
        e = _plain(item)
        if e in allowed and allowed[e] not in out:
            out.append(allowed[e])
    return out


async def get_config() -> dict:
    if _CFG["v"] is not None and time.time() - _CFG["t"] < 10:
        return _CFG["v"]
    try:
        raw = await get_setting("reactions", {}) or {}
    except Exception:
        raw = {}
    events = {k: bool((raw.get("events") or {}).get(k, True)) for k in EVENTS}
    pool = clean_pool(raw.get("pool") or []) or list(DEFAULT_POOL)
    cfg = {"enabled": bool(raw.get("enabled", True)), "events": events, "pool": pool, "custom_pool": bool(raw.get("pool"))}
    _CFG.update(t=time.time(), v=cfg)
    return cfg


async def save_config(cfg: dict):
    data = {"enabled": cfg["enabled"], "events": cfg["events"]}
    if cfg.get("custom_pool"):
        data["pool"] = cfg["pool"]
    await set_setting("reactions", data)
    _CFG["v"] = None


def remember_user_message(user_id: int, message_id: int):
    _LAST_MSG[user_id] = (message_id, time.time())
    if len(_LAST_MSG) > 20000:                       # keep memory small
        cutoff = time.time() - LAST_MESSAGE_TTL
        for k in [k for k, v in _LAST_MSG.items() if v[1] < cutoff]:
            _LAST_MSG.pop(k, None)


async def _send(client, chat_id, message_id, emoji, big):
    try:
        await client.send_reaction(chat_id=chat_id, message_id=message_id, emoji=emoji, big=big)
    except TypeError:                                  # a library without the "big" option
        await client.send_reaction(chat_id=chat_id, message_id=message_id, emoji=emoji)


async def react(client, chat_id, message_id, event: str, big: bool = False, own: bool = False) -> bool:
    """Puts one random reaction on a message. Never raises. own=True: the message was sent by the bot itself."""
    try:
        if not isinstance(chat_id, int) or chat_id <= 0 or not message_id:
            return False                                # private chats only
        cfg = await get_config()
        if not cfg["enabled"] or not cfg["events"].get(event, True):
            return False
        if own and _OWN["fails"] >= OWN_FAILS_LIMIT:
            return False
        now = time.time()
        if now - _COOL.get((chat_id, event), 0) < COOLDOWN:
            return False
        _COOL[(chat_id, event)] = now
        if len(_COOL) > 20000:
            _COOL.clear()
        pool = cfg["pool"]
        for emoji in random.sample(pool, k=min(2, len(pool))):      # a second emoji only when the first is refused
            try:
                await _send(client, chat_id, message_id, emoji, big)
                if own:
                    _OWN["fails"] = 0
                return True
            except Exception as e:
                text = f"{type(e).__name__} {e}"
                if "REACTION_INVALID" in text.upper() or "ReactionInvalid" in text:
                    continue
                if own:
                    _OWN["fails"] += 1
                print(f"[reactions] {event}: {type(e).__name__}: {str(e)[:100]}")
                return False
        return False
    except Exception:
        return False


def fire(client, message, event: str, big: bool = False):
    """Reaction on a user's message in the background: the handler does not wait for it."""
    try:
        chat_id = message.chat.id if getattr(message, "chat", None) else message.from_user.id
        _spawn(react(client, chat_id, message.id, event, big))
    except Exception:
        pass


def _spawn(coro):
    try:
        task = asyncio.get_running_loop().create_task(coro)
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)
    except Exception:
        coro.close()


def payment_verified(client, user_id: int, own_message_id=None):
    """
    A payment was verified. The reaction goes (with the big animation) on the user's newest message, which is always a
    message of the user; if the bot does not know one (for example after a restart) it goes on the bot's own message.
    """
    hit = _LAST_MSG.get(user_id)
    if hit and time.time() - hit[1] < LAST_MESSAGE_TTL:
        _spawn(react(client, user_id, hit[0], "payment", big=True))
    elif own_message_id:
        _spawn(react(client, user_id, own_message_id, "payment", big=True, own=True))
