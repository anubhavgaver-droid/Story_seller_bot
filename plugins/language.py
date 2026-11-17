"""
Language choice for users + translation tools for the admin.

  first /start        "Choose your language" (the /start then continues, deep links included)
  /language           change the language any time (the 🌐 Language button of the menu does the same)
  /addtr  English phrase | हिंदी   (admin) add or fix a Hindi translation without touching the code
  /deltr  English phrase           (admin) remove an added translation
  /trlist                          (admin) show the added translations
"""
import html as _html
import importlib

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import lang
from config import ADMIN_ID
from database.db import get_setting, set_setting

E = lambda s: _html.escape(str(s), quote=False)


def picker_markup(current=None):
    def label(code, text):
        return ("✅ " if current == code else "") + text
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label("hi", "🇮🇳 हिंदी"), callback_data="lang_set:hi", style=enums.ButtonStyle.PRIMARY),
        InlineKeyboardButton(label("en", "🇬🇧 English"), callback_data="lang_set:en", style=enums.ButtonStyle.PRIMARY),
    ]])


PICKER_TEXT = (
    "🌐 <b>Choose your language</b>\n"
    "<b>अपनी भाषा चुनें</b>\n\n"
    "<i>You can change it any time with /language\n"
    "आप इसे कभी भी /language से बदल सकते हैं</i>"
)


async def ask_language(client, message):
    """Shows the picker (used by /start for a new user and by /language)."""
    current = await lang.get_lang(message.from_user.id)
    return await message.reply_text(PICKER_TEXT, reply_markup=picker_markup(current))


@Client.on_message(filters.command("language") & filters.private)
async def language_command(client, message):
    await ask_language(client, message)


@Client.on_callback_query(filters.regex(r"^(lang_set:(hi|en)|open_language_cb)$"))
async def language_callback(client, callback):
    user = callback.from_user
    if callback.data == "open_language_cb":
        await callback.answer()
        current = await lang.get_lang(user.id)
        return await callback.message.reply_text(PICKER_TEXT, reply_markup=picker_markup(current))

    code = callback.data.split(":")[1]
    first_time = await lang.needs_choice(user.id)
    await lang.set_lang(user.id, code)
    await callback.answer("✅ भाषा: हिंदी" if code == "hi" else "✅ Language: English")
    try:
        await callback.message.delete()
    except Exception:
        pass

    pending = lang.PENDING.pop(user.id, None)
    if pending is not None:
        # The user came from /start: continue exactly where /start stopped (registration, referral, deep link, menu).
        try:
            start_module = importlib.import_module("plugins.start")
            return await start_module.start_handler(client, pending)
        except Exception as e:
            print(f"[lang] could not continue /start after the language choice: {type(e).__name__}: {e}")
    text = ("✅ भाषा हिंदी सेट हो गई।\nमेन्यू देखने के लिए /start भेजें।" if code == "hi"
            else "✅ Language set to English.\nSend /start to see the menu.")
    await client.send_message(user.id, text)


# Hindi reply-keyboard buttons -> the original text the existing handlers match on. group=-100 runs before every handler.
@Client.on_message(filters.private & filters.text, group=-100)
async def reply_button_mapper(client, message):
    original = lang.original_reply_text(message.text)
    if original:
        try:
            message.text = original
        except Exception:
            pass


# ------------------------------- admin tools -------------------------------
_admin = filters.user(ADMIN_ID) & filters.private


@Client.on_message(filters.command("addtr") & _admin)
async def add_translation(client, message):
    raw = message.text.split(None, 1)[1] if len(message.command) > 1 else ""
    if "|" not in raw:
        return await message.reply_text(
            "❌ Example:\n<code>/addtr Payment not found yet. | पेमेंट अभी नहीं मिला।</code>\n\n"
            "Write the English text exactly as the user sees it (capital letters do not matter). "
            "A single word is translated only when it stands alone (a button or a label)."
        )
    english, hindi = [x.strip() for x in raw.split("|", 1)]
    if not english or not hindi or len(english) > 300 or len(hindi) > 600:
        return await message.reply_text("❌ Both parts are needed (English up to 300, Hindi up to 600 characters).")
    data = dict(await get_setting("translations_hi", {}) or {})
    data[lang._norm(english).strip()] = hindi
    await set_setting("translations_hi", data)
    lang.invalidate()
    await message.reply_text(f"✅ Saved.\n<b>{E(english)}</b>\n→ {E(hindi)}\n\nTotal added: {len(data)}")


@Client.on_message(filters.command("deltr") & _admin)
async def delete_translation(client, message):
    english = message.text.split(None, 1)[1].strip() if len(message.command) > 1 else ""
    data = dict(await get_setting("translations_hi", {}) or {})
    key = lang._norm(english).strip()
    if not english or key not in data:
        return await message.reply_text("❌ Not found. Use <code>/trlist</code> to see the added translations.")
    data.pop(key)
    await set_setting("translations_hi", data)
    lang.invalidate()
    await message.reply_text(f"✅ Removed: <b>{E(english)}</b>")


@Client.on_message(filters.command("trlist") & _admin)
async def list_translations(client, message):
    data = await get_setting("translations_hi", {}) or {}
    lines = [f"🌐 <b>Added translations: {len(data)}</b>  (built in: {len(lang_hi_table())})\n"]
    for k, v in list(data.items())[-30:]:
        lines.append(f"• {E(k)} → {E(v)}")
    if not data:
        lines.append("None yet. Add one: <code>/addtr English | हिंदी</code>")
    await message.reply_text("\n".join(lines))


def lang_hi_table():
    import lang_hi
    return lang_hi.HI
