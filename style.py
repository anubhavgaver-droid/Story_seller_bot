"""
Small-caps text helper for headings, labels and buttons.

    sc("Payment Setup")            -> "ᴘᴀʏᴍᴇɴᴛ sᴇᴛᴜᴘ"
    sc("<b>Active</b> Gateway")    -> "<b>ᴀᴄᴛɪᴠᴇ</b> ɢᴀᴛᴇᴡᴀʏ"   (HTML tags stay intact)

Only A-Z / a-z are converted. Digits, emojis, punctuation, HTML tags (<...>) and
entities (&amp; ...) are left exactly as they are, so it is safe inside Telegram HTML messages.
Use it for headings and button labels, not for values the admin has to copy (keys, URLs, commands).
"""
import re

_SMALL_CAPS = {
    "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ", "f": "ғ", "g": "ɢ", "h": "ʜ", "i": "ɪ",
    "j": "ᴊ", "k": "ᴋ", "l": "ʟ", "m": "ᴍ", "n": "ɴ", "o": "ᴏ", "p": "ᴘ", "q": "ǫ", "r": "ʀ",
    "s": "s", "t": "ᴛ", "u": "ᴜ", "v": "ᴠ", "w": "ᴡ", "x": "x", "y": "ʏ", "z": "ᴢ",
}
_TABLE = {}
for _k, _v in _SMALL_CAPS.items():
    _TABLE[ord(_k)] = _v
    _TABLE[ord(_k.upper())] = _v

# HTML tags and entities are protected from conversion
_PROTECT = re.compile(r"(<[^>]*>|&[A-Za-z]+;|&#\d+;)")


def sc(text: str) -> str:
    if not text:
        return text
    parts = _PROTECT.split(text)
    out = []
    for i, part in enumerate(parts):
        # odd indexes are the protected tags / entities
        out.append(part if i % 2 else part.translate(_TABLE))
    return "".join(out)
