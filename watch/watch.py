
"""
WATCH / STREAM module  (folder: watch/)

What it does
  * Every audio/video file that is delivered to a buyer gets a "🎧 Stream" button under it (see start.py).
  * The button opens a Telegram Mini App (watch/watch.html) with a premium player: speed control from 0.5x to 3x,
    waveform seek bar, +-15s, next/previous, sleep timer, resume position and the full playlist of the story.
  * Files are streamed straight from the DB channel through the bot (HTTP Range supported, so seeking works).

Security
  * The user is identified ONLY by the signed Telegram "initData" (same check as /api/user_purchases).
  * Only buyers of the story (and the admin) get a playlist. Every file gets a signed, expiring token;
    a token cannot be changed or used for another file.
  * Files stay in the DB channel. Nothing is stored on the server.

Routes (registered by setup_watch_routes)
  GET  /watch                  the player page
  POST /api/watch/playlist     {init_data, story_id}  ->  playlist with signed stream URLs
  GET  /watch/stream/{token}   the media bytes (Range supported)
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import parse_qsl

from aiohttp import web

from config import BOT_TOKEN, ADMIN_ID, WEB_APP_URL
from database.db import get_story_by_id, is_story_unlocked, story_channel

try:
    from pyrogram.errors import FloodWait
except Exception:                                  # pragma: no cover
    class FloodWait(Exception):
        value = 1

WATCH_DIR = os.path.dirname(os.path.abspath(__file__))
CHUNK = 1024 * 1024               # Telegram download chunk (stream_media offset counts in these)
TOKEN_TTL = 6 * 3600              # a stream link works for 6 hours
PLAYLIST_TTL = 10 * 60            # story file list is cached for 10 minutes
INFO_TTL = 30 * 60                # file info (file_id, size) is cached for 30 minutes
MAX_FILES = 1500                  # most files listed for one story
MAX_STREAMS = 8                   # parallel streams (protects a small server)

_KEY = hashlib.sha256(("watch-v1|" + str(BOT_TOKEN)).encode()).digest()
_PLAYLISTS = {}                   # story_id -> (time, chat_id, [items])
_INFO = {}                        # (chat_id, msg_id) -> {file_id, size, mime, kind, t}
_SLOTS = None
_PAGE = {"html": None}

_AUDIO_EXT = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".wav": "audio/wav",
              ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg", ".flac": "audio/flac"}
_VIDEO_EXT = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".m4v": "video/mp4"}


def _slots():
    global _SLOTS
    if _SLOTS is None:
        _SLOTS = asyncio.Semaphore(MAX_STREAMS)
    return _SLOTS


# ------------------------------- auth + tokens -------------------------------
def verify_init_data(init_data: str, bot_token: str = None, max_age: int = 86400):
    """Telegram Mini App initData check (HMAC-SHA256 with the bot token). Returns the user dict or None."""
    bot_token = bot_token or BOT_TOKEN
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received = pairs.pop("hash", None)
        if not received:
            return None
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, received):
            return None
        if time.time() - int(pairs.get("auth_date", "0")) > max_age:
            return None
        user = json.loads(pairs.get("user", "{}"))
        return user if user.get("id") else None
    except Exception:
        return None


def make_token(user_id: int, story_id: str, chat_id: int, msg_id: int, ttl: int = TOKEN_TTL) -> str:
    payload = {"u": int(user_id), "s": str(story_id), "c": int(chat_id), "m": int(msg_id), "e": int(time.time() + ttl)}
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=")
    sig = hmac.new(_KEY, raw, hashlib.sha256).hexdigest()[:32]
    return raw.decode() + "." + sig


def read_token(token: str):
    """The payload when the token is genuine and not expired, otherwise None."""
    try:
        raw, sig = (token or "").rsplit(".", 1)
        good = hmac.new(_KEY, raw.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(good, sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        if int(payload["e"]) < time.time():
            return None
        return payload
    except Exception:
        return None


# ------------------------------- media helpers -------------------------------
def media_of(msg):
    """(kind, media_object, mime) for a playable audio/video message, otherwise None."""
    try:
        if getattr(msg, "audio", None):
            return "audio", msg.audio, msg.audio.mime_type or "audio/mpeg"
        if getattr(msg, "voice", None):
            return "audio", msg.voice, msg.voice.mime_type or "audio/ogg"
        if getattr(msg, "video", None):
            return "video", msg.video, msg.video.mime_type or "video/mp4"
        doc = getattr(msg, "document", None)
        if doc:
            mime = (doc.mime_type or "").lower()
            ext = os.path.splitext((doc.file_name or "").lower())[1]
            if mime.startswith("audio/"):
                return "audio", doc, mime
            if mime.startswith("video/") and mime != "video/x-matroska":
                return "video", doc, mime
            if ext in _AUDIO_EXT:
                return "audio", doc, _AUDIO_EXT[ext]
            if ext in _VIDEO_EXT:
                return "video", doc, _VIDEO_EXT[ext]
    except Exception:
        pass
    return None


def _title_for(msg, media, index: int) -> str:
    title = (getattr(media, "title", None) or "").strip()
    if title:
        return title[:120]
    caption = (getattr(msg, "caption", None) or getattr(msg, "text", None) or "").strip()
    if caption:
        first = re.sub(r"\s+", " ", caption.splitlines()[0]).strip()
        if first:
            return first[:120]
    name = (getattr(media, "file_name", None) or "").strip()
    if name:
        return os.path.splitext(name)[0][:120]
    return f"Part {index}"


def parse_range(header, size: int):
    """
    HTTP Range header -> (start, end) inclusive | None (no / unsupported header: send everything) | False (not satisfiable).
    """
    if not header:
        return None
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if not m or (m.group(1) == "" and m.group(2) == ""):
        return None
    if m.group(1) == "":                                  # last N bytes
        n = int(m.group(2))
        if n == 0:
            return False
        start, end = max(size - n, 0), size - 1
    else:
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else size - 1
        end = min(end, size - 1)
    if start >= size or start > end:
        return False
    return start, end


def story_file_ids(story: dict) -> list:
    ids = set()
    first, last = story.get("first_msg_id"), story.get("last_msg_id")
    if first and last and int(last) >= int(first):
        ids.update(range(int(first), int(last) + 1))
    for r in story.get("custom_ranges") or []:
        a, b = r.get("first_id"), r.get("last_id")
        if a and b and int(b) >= int(a):
            ids.update(range(int(a), int(b) + 1))
    return sorted(ids)[:MAX_FILES]


def _remember(chat_id: int, msg_id: int, kind: str, media, mime: str):
    _INFO[(chat_id, msg_id)] = {
        "file_id": media.file_id, "size": int(getattr(media, "file_size", 0) or 0),
        "mime": mime, "kind": kind, "t": time.time(),
    }
    if len(_INFO) > 6000:                                  # keep memory small
        cutoff = time.time() - INFO_TTL
        for k in [k for k, v in _INFO.items() if v["t"] < cutoff]:
            _INFO.pop(k, None)


async def _get_messages(bot, chat_id, ids):
    while True:
        try:
            return await bot.get_messages(chat_id, ids)
        except FloodWait as e:
            await asyncio.sleep(getattr(e, "value", 1) + 1)
        except Exception as e:
            print(f"[watch] get_messages error: {type(e).__name__}: {e}")
            return [] if isinstance(ids, list) else None


async def _build_playlist(bot, story: dict):
    chat_id = story_channel(story)
    ids = story_file_ids(story)
    items = []
    for i in range(0, len(ids), 200):
        batch = ids[i:i + 200]
        msgs = await _get_messages(bot, chat_id, batch) or []
        for msg in msgs:
            if not msg or getattr(msg, "empty", False):
                continue
            found = media_of(msg)
            if not found:
                continue
            kind, media, mime = found
            _remember(chat_id, msg.id, kind, media, mime)
            items.append({
                "id": msg.id, "title": _title_for(msg, media, len(items) + 1), "kind": kind,
                "mime": mime, "size": int(getattr(media, "file_size", 0) or 0),
                "duration": int(getattr(media, "duration", 0) or 0),
            })
    items.sort(key=lambda x: x["id"])
    return chat_id, items


async def _playlist(bot, story: dict):
    sid = str(story.get("story_id") or story.get("_id"))
    cached = _PLAYLISTS.get(sid)
    if cached and time.time() - cached[0] < PLAYLIST_TTL:
        return cached[1], cached[2]
    chat_id, items = await _build_playlist(bot, story)
    if items:
        _PLAYLISTS[sid] = (time.time(), chat_id, items)
    return chat_id, items


async def _get_info(bot, chat_id: int, msg_id: int, force: bool = False):
    info = _INFO.get((chat_id, msg_id))
    if info and not force and time.time() - info["t"] < INFO_TTL:
        return info
    msg = await _get_messages(bot, chat_id, msg_id)
    found = media_of(msg) if msg and not getattr(msg, "empty", False) else None
    if not found:
        return None
    _remember(chat_id, msg_id, *found)
    return _INFO.get((chat_id, msg_id))


# ------------------------------- the button under each file -------------------------------
def stream_markup(story: dict, msg):
    """Inline keyboard with the 🎧 Stream button for one delivered file (None for non-audio/video files)."""
    try:
        found = media_of(msg)
        if not found:
            return None
        from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
        sid = str(story.get("story_id") or story.get("_id"))
        url = f"{WEB_APP_URL.rstrip('/')}/watch?s={sid}&m={msg.id}"
        label = "🎧 Stream" if found[0] == "audio" else "🎬 Watch"
        try:
            from style import sc
            label = ("🎧 " + sc("Stream")) if found[0] == "audio" else ("🎬 " + sc("Watch"))
        except Exception:
            pass
        kwargs = {}
        try:
            from pyrogram import enums
            kwargs["style"] = enums.ButtonStyle.PRIMARY
        except Exception:
            pass
        try:
            button = InlineKeyboardButton(label, web_app=WebAppInfo(url=url), **kwargs)
        except TypeError:
            button = InlineKeyboardButton(label, web_app=WebAppInfo(url=url))
        return InlineKeyboardMarkup([[button]])
    except Exception as e:
        print(f"[watch] stream button error: {type(e).__name__}: {e}")
        return None


# ------------------------------- HTTP handlers -------------------------------
def _json(data, status=200):
    return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})


async def handle_page(request):
    if _PAGE["html"] is None:
        path = os.path.join(WATCH_DIR, "watch.html")
        if not os.path.exists(path):
            return web.Response(text="watch/watch.html not found", status=404)
        with open(path, "r", encoding="utf-8") as f:
            _PAGE["html"] = f.read()
    return web.Response(text=_PAGE["html"], content_type="text/html", headers={"Cache-Control": "no-cache"})


async def handle_playlist(request):
    try:
        body = await request.json()
    except Exception:
        return _json({"error": "bad_request"}, 400)

    user = verify_init_data(str(body.get("init_data") or ""))
    if not user:
        return _json({"error": "unauthorized"}, 401)
    uid = int(user["id"])

    story_id = str(body.get("story_id") or "").strip()
    story = await get_story_by_id(story_id) if story_id else None
    if not story:
        return _json({"error": "not_found"}, 404)

    title = (story.get("title") or "Story").strip().splitlines()[0]
    sid = str(story.get("story_id") or story.get("_id"))
    if uid != int(ADMIN_ID) and not await is_story_unlocked(uid, title, sid):
        return _json({"error": "not_purchased"}, 403)

    bot = request.app.get("watch_bot_getter", lambda: None)()
    if bot is None:
        return _json({"error": "starting"}, 503)

    chat_id, items = await _playlist(bot, story)
    out = []
    for it in items:
        row = dict(it)
        row["url"] = "/watch/stream/" + make_token(uid, sid, chat_id, it["id"])
        out.append(row)
    photo = story.get("photo")
    return _json({
        "story_id": sid, "title": title,
        "photo": photo if isinstance(photo, str) and photo.startswith("http") else "",
        "items": out,
    })


async def _open_stream(bot, chat_id: int, msg_id: int, info: dict, start: int, need):
    """Opens the Telegram download. Returns (async_generator, first_chunk, info). Refreshes an expired file reference once."""
    first_chunk_no, skip = start // CHUNK, start % CHUNK
    limit = 0 if need is None else (skip + need + CHUNK - 1) // CHUNK
    last_error = None
    for attempt in (0, 1):
        agen = bot.stream_media(info["file_id"], limit=limit, offset=first_chunk_no)
        try:
            first = await agen.__anext__()
            return agen, first, info
        except StopAsyncIteration:
            return agen, b"", info
        except Exception as e:
            last_error = e
            try:
                await agen.aclose()
            except Exception:
                pass
            if attempt == 0:
                fresh = await _get_info(bot, chat_id, msg_id, force=True)
                if not fresh:
                    break
                info = fresh
    raise last_error or RuntimeError("stream failed")


async def handle_stream(request):
    tok = read_token(request.match_info.get("token", ""))
    if not tok:
        return web.Response(status=403, text="Link expired. Please reopen the player.")
    bot = request.app.get("watch_bot_getter", lambda: None)()
    if bot is None:
        return web.Response(status=503, text="Starting, try again")

    chat_id, msg_id = int(tok["c"]), int(tok["m"])
    info = await _get_info(bot, chat_id, msg_id)
    if not info:
        return web.Response(status=404, text="File not found")

    size = info["size"]
    headers = {
        "Content-Type": info["mime"],
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-cache",
        "Content-Disposition": "inline",
        "X-Content-Type-Options": "nosniff",
    }

    if size > 0:
        rng = parse_range(request.headers.get("Range"), size)
        if rng is False:
            return web.Response(status=416, headers={"Content-Range": f"bytes */{size}"})
        if rng is None:
            start, end, status = 0, size - 1, 200
        else:
            (start, end), status = rng, 206
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        need = end - start + 1
        headers["Content-Length"] = str(need)
    else:                                                   # size unknown: send everything, no ranges
        start, need, status = 0, None, 200

    if request.method == "HEAD":
        return web.Response(status=status, headers=headers)

    async with _slots():
        try:
            agen, first, info = await _open_stream(bot, chat_id, msg_id, info, start, need)
        except Exception as e:
            print(f"[watch] open stream error: {type(e).__name__}: {e}")
            return web.Response(status=502, text="Could not open the file")

        resp = web.StreamResponse(status=status, headers=headers)
        await resp.prepare(request)
        skip = start % CHUNK
        sent = 0
        try:
            chunk = first
            while True:
                if chunk:
                    if skip:
                        chunk, skip = chunk[skip:], 0
                    if need is not None and sent + len(chunk) > need:
                        chunk = chunk[:need - sent]
                    await resp.write(chunk)
                    sent += len(chunk)
                    if need is not None and sent >= need:
                        break
                try:
                    chunk = await agen.__anext__()
                except StopAsyncIteration:
                    break
        except (ConnectionResetError, asyncio.CancelledError):
            pass                                            # the player closed the connection (seek / stop)
        except Exception as e:
            print(f"[watch] stream error: {type(e).__name__}: {e}")
        finally:
            try:
                await agen.aclose()
            except Exception:
                pass
        try:
            await resp.write_eof()
        except Exception:
            pass
        return resp


def setup_watch_routes(app, get_bot):
    """Call once from main.py: setup_watch_routes(app_web, lambda: bot_instance)."""
    app["watch_bot_getter"] = get_bot
    app.router.add_get("/watch", handle_page)
    app.router.add_post("/api/watch/playlist", handle_playlist)
    app.router.add_get("/watch/stream/{token}", handle_stream)
