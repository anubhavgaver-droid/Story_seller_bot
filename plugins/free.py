from pyrogram import Client, filters

from database.db import get_story_by_key
from freeflow import start_free_claim
from style import sc


@Client.on_callback_query(filters.regex(r"^claim:"))
async def claim_free_callback(client, callback):
    """The Claim Free button: ad gate (when ON) or direct unlock."""
    story = await get_story_by_key(callback.data[len("claim:"):])
    if not story:
        return await callback.answer("Story not found.", show_alert=True)

    await callback.answer("Please wait...")
    try:
        await start_free_claim(client, callback.from_user.id, story)
    except Exception as e:
        print(f"Free claim error: {e}")
        await callback.message.reply_text(f"❌ <b>{sc('Something went wrong')}</b>\nPlease try again in a moment.")
