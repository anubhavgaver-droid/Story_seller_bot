from pyrogram import Client, filters

from database.db import get_story_by_key
from freeflow import start_free_claim


@Client.on_callback_query(filters.regex(r"^claim:"))
async def claim_free_callback(client, callback):
    """🎁 Claim Free button: ad-gate (agar ON ho) ya seedha unlock."""
    story = await get_story_by_key(callback.data[len("claim:"):])
    if not story:
        return await callback.answer("❌ Story not found!", show_alert=True)

    await callback.answer("🎁 Processing...")
    try:
        await start_free_claim(client, callback.from_user.id, story)
    except Exception as e:
        print(f"Free claim error: {e}")
        await callback.message.reply_text("❌ <b>Kuch gadbad hui.</b> Thodi der baad dobara try karein.")
