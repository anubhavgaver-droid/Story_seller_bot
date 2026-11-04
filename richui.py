"""
Panel rendering for /admin and /setup.

1. EDIT IN PLACE. A button press edits the SAME message (Next / Back / Delete list / sub-menus).
   A new message is sent only if the message cannot be edited at all.

2. BIG HEADINGS (Telegram Rich Messages, Bot API 10.1+). The first line of a panel (for example
   "⚙️ <b>ᴘᴀʏᴍᴇɴᴛ & ᴀᴅs sᴇᴛᴜᴘ</b>") becomes a real <h1> heading: big, dark, normal letters.
   The rest of the text stays as it is. Needs Kurigram 2.2.26+ (it provides InputRichMessage).

Everything is defensive, because Rich Messages are new:
  - If the library has no InputRichMessage, or the Rich Message call fails, the panel falls back to a normal
    HTML message with the same text and buttons. Nothing breaks.
  - After 3 failures in a row, Rich Messages are switched off until the bot restarts (no slow retries).
  - The admin can switch it any time:  /richui on | off | status   (also a button in /admin).
"""
import re

from pyrogram.errors import MessageNotModified

try:  # Kurigram 2.2.26+
    from pyrogram.types import InputRichMessage
except Exception:  # pragma: no cover - older library
    InputRichMessage = None

from database.db import get_setting
from style import pretty_title

_STATE = {"fails": 0}
MAX_FAILS = 3

_HEADING_RE = re.compile(r"^\s*([^<]*?)\s*<b>(.+?)</b>(.*)$")


# ------------------------------- switches -------------------------------
async def rich_enabled() -> bool:
    if InputRichMessage is None or _STATE["fails"] >= MAX_FAILS:
        return False
    return bool(await get_setting("rich_ui", True))


def _ok():
    _STATE["fails"] = 0


def _failed(where: str, err: Exception):
    _STATE["fails"] += 1
    print(f"[richui] {where} failed ({_STATE['fails']}/{MAX_FAILS}): {type(err).__name__}: {err}")
    if _STATE["fails"] >= MAX_FAILS:
        print("[richui] Rich Messages disabled until restart. Panels use normal messages now.")


def reset_failures():
    _STATE["fails"] = 0


# ------------------------------- conversion -------------------------------
def to_rich_html(text: str, notice: str = None) -> str:
    """
    Panel text (Telegram HTML with \\n line breaks) -> Rich HTML.
      first line  "<emoji> <b>Title</b>rest"  ->  <h1>Emoji Title rest</h1>
      blank line  ->  new paragraph          single newline  ->  <br>
    `notice` (for example "✅ saved") is shown as the first paragraph under the heading.
    """
    lines = (text or "").split("\n")
    heading = ""
    body_lines = lines
    m = _HEADING_RE.match(lines[0]) if lines else None
    if m:
        emoji, title, rest = m.group(1).strip(), m.group(2), m.group(3)
        inner = f"{emoji} {pretty_title(title)}{rest}".strip()
        heading = f"<h1>{inner}</h1>"
        body_lines = lines[1:]

    body = "\n".join(body_lines).strip("\n")
    chunks = [notice] if notice else []
    if body:
        chunks.extend(re.split(r"\n\s*\n", body))
    paragraphs = [f"<p>{c.strip(chr(10)).replace(chr(10), '<br>')}</p>" for c in chunks if c and c.strip()]
    html_out = heading + "".join(paragraphs)
    # A bare "&" must be written as &amp; (existing entities such as &lt; or &#39; are left alone)
    return re.sub(r"&(?!#?\w+;)", "&amp;", html_out)


def _plain_text(text: str, notice: str = None) -> str:
    return f"{notice}\n\n{text}" if notice else text


# ------------------------------- edit in place -------------------------------
async def edit_panel(callback, text: str, markup, notice: str = None):
    """Edits the panel message the button belongs to. Replies only if it cannot be edited at all."""
    msg = callback.message

    if await rich_enabled():
        rm = InputRichMessage(html=to_rich_html(text, notice))
        for call in (
            lambda: msg.edit_text(rich_message=rm, reply_markup=markup),
            lambda: msg.edit_text("", rich_message=rm, reply_markup=markup),
        ):
            try:
                await call()
                _ok()
                return
            except MessageNotModified:
                return
            except TypeError:
                continue            # this library version uses another call form: try the next one
            except Exception as e:  # Telegram rejected it: use the normal message below
                _failed("edit", e)
                break

    plain = _plain_text(text, notice)
    try:
        await msg.edit_text(plain, reply_markup=markup)
        return
    except MessageNotModified:
        return
    except Exception as e:
        print(f"[richui] normal edit failed: {type(e).__name__}: {e}")

    try:
        await msg.reply_text(plain, reply_markup=markup)
    except Exception as e:
        print(f"[richui] reply failed too: {type(e).__name__}: {e}")


# ------------------------------- first send (command replies) -------------------------------
async def _send_rich(client, chat_id, rm, markup, reply_msg=None):
    """Tries the Rich Message send forms. Returns True when one worked."""
    forms = []
    if reply_msg is not None and hasattr(reply_msg, "reply_rich"):
        forms.append(lambda: reply_msg.reply_rich(rich_message=rm, reply_markup=markup))
        forms.append(lambda: reply_msg.reply_rich(rm, reply_markup=markup))
    if client is not None and hasattr(client, "send_rich_message"):
        forms.append(lambda: client.send_rich_message(chat_id, rich_message=rm, reply_markup=markup))
        forms.append(lambda: client.send_rich_message(chat_id, rm, reply_markup=markup))

    for call in forms:
        try:
            await call()
            _ok()
            return True
        except TypeError:
            continue
        except Exception as e:
            _failed("send", e)
            return False
    return False


async def send_panel(message, text: str, markup, notice: str = None):
    """Replies to a command message with a panel."""
    if await rich_enabled():
        rm = InputRichMessage(html=to_rich_html(text, notice))
        if await _send_rich(getattr(message, "_client", None), message.chat.id, rm, markup, reply_msg=message):
            return
    await message.reply_text(_plain_text(text, notice), reply_markup=markup)


async def send_panel_to(client, chat_id, text: str, markup, notice: str = None):
    """Sends a panel to a chat (used after a value was saved)."""
    if await rich_enabled():
        rm = InputRichMessage(html=to_rich_html(text, notice))
        if await _send_rich(client, chat_id, rm, markup):
            return
    await client.send_message(chat_id, _plain_text(text, notice), reply_markup=markup)
