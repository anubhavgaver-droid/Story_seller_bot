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


# ---------------------------------------------------------------------------------------------
# Reverse conversion: small caps -> normal letters (used for big "real" headings, where the
# heading font renders normal letters much darker and clearer than small-caps glyphs).
# ---------------------------------------------------------------------------------------------
_REVERSE = {v: k for k, v in _SMALL_CAPS.items() if v != k}
_REVERSE_TABLE = {ord(v): k for v, k in _REVERSE.items()}
_ACRONYMS = {"upi": "UPI", "db": "DB", "id": "ID", "utr": "UTR", "ads": "Ads", "otp": "OTP", "qr": "QR"}


def unsc(text: str) -> str:
    """Small-caps letters back to lowercase Latin letters. Everything else is unchanged."""
    return (text or "").translate(_REVERSE_TABLE)


def pretty_title(text: str) -> str:
    """
    'ᴘᴀʏᴍᴇɴᴛ & ᴀᴅs sᴇᴛᴜᴘ' -> 'Payment & Ads Setup'.
    Text that has no small-caps letters is returned untouched (it is already normal text).
    """
    plain = unsc(text)
    if plain == text:
        return text
    words = []
    for word in plain.split(" "):
        core = re.sub(r"[^A-Za-z]", "", word)
        if core.lower() in _ACRONYMS:
            word = word.replace(core, _ACRONYMS[core.lower()], 1)
        elif word[:1].isalpha():
            word = word[:1].upper() + word[1:]
        elif len(word) > 1 and word[0] in "([" and word[1].isalpha():
            word = word[0] + word[1].upper() + word[2:]
        words.append(word)
    return " ".join(words)
