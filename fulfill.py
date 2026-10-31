"""
Paid order ko ek hi jagah se poora karna (Verify button aur webhook dono yahi use karte hain).
claim_payment_order() atomic hai, isliye chahe user 5 baar Verify dabaye ya webhook bhi aa jaye,
wallet / story sirf ek baar milti hai.
"""
from pyrogram import enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import LOG_CHANNEL
from database.db import (
    claim_payment_order,
    release_payment_order,
    add_wallet_balance,
    add_user_purchase,
    get_story_by_key,
    delivery_link,
)


async def _log(client, text: str):
    if LOG_CHANNEL and LOG_CHANNEL != 0:
        try:
            await client.send_message(chat_id=LOG_CHANNEL, text=text, disable_web_page_preview=True)
        except Exception as e:
            print(f"❌ LOG_CHANNEL Error: {e}")


async def fulfill_order(client, order: dict, paid_amount: float, source: str = "AUTO VERIFY") -> str:
    """
    Returns "done" | "already" | "error".
    """
    order_id = order["order_id"]
    user_id = order["user_id"]

    try:
        paid = float(paid_amount or 0)
    except (TypeError, ValueError):
        paid = 0.0
    if paid <= 0:
        paid = float(order.get("amount", 0))

    claimed = await claim_payment_order(order_id, paid)
    if not claimed:
        return "already"

    user_mention = f"<a href='tg://user?id={user_id}'>User</a>"
    notice = None          # user ko bhejne wala message
    notice_markup = None
    log_msg = None

    try:
        # ---------------- WALLET TOP-UP ----------------
        if order.get("kind") == "WALLET":
            new_bal = await add_wallet_balance(user_id, paid)
            notice = (
                f"🎉 <b>ᴀᴜᴛᴏ-ᴠᴇʀɪғɪᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
                f"💰 Added ₹{paid} to Wallet.\n"
                f"👛 New Balance: ₹{new_bal}"
            )
            log_msg = (
                f"💳 <b>[{source}] WALLET TOP-UP</b>\n\n"
                f"👤 <b>User:</b> {user_mention} (<code>{user_id}</code>)\n"
                f"💰 <b>Amount Added:</b> ₹{paid}\n"
                f"👛 <b>New Balance:</b> ₹{new_bal}\n"
                f"🆔 <b>Order ID:</b> <code>{order_id}</code>"
            )

        # ---------------- STORY PURCHASE ----------------
        else:
            story = await get_story_by_key(order.get("story_id") or order.get("title"))

            if story is None:
                # Story delete ho chuki -> paisa wallet me daal do, kuch gaya nahi
                new_bal = await add_wallet_balance(user_id, paid)
                notice = (
                    f"⚠️ <b>Story ab available nahi hai.</b>\n\n"
                    f"Aapke ₹{paid} wallet me jod diye gaye hain.\n👛 Balance: ₹{new_bal}"
                )
                log_msg = (
                    f"⚠️ <b>[{source}] STORY MISSING -> WALLET CREDIT</b>\n\n"
                    f"👤 <b>User:</b> {user_mention} (<code>{user_id}</code>)\n"
                    f"💰 <b>Amount:</b> ₹{paid}\n🆔 <b>Order ID:</b> <code>{order_id}</code>"
                )
            else:
                price = float(story.get("price", 0) or 0)
                clean_title = story["title"].strip().split("\n")[0]
                story_id = story.get("story_id")

                if paid + 0.01 < price:
                    # Kam paisa mila: story unlock nahi, jitna aaya wallet me
                    new_bal = await add_wallet_balance(user_id, paid)
                    notice = (
                        f"⚠️ <b>Payment amount kam mila.</b>\n\n"
                        f"Story ka price ₹{price} hai, aapne ₹{paid} diye.\n"
                        f"₹{paid} aapke wallet me jod diye gaye hain (Balance: ₹{new_bal}). "
                        f"Wallet se story kharid sakte hain."
                    )
                    log_msg = (
                        f"⚠️ <b>[{source}] UNDERPAID -> WALLET CREDIT</b>\n\n"
                        f"👤 <b>User:</b> {user_mention} (<code>{user_id}</code>)\n"
                        f"📖 <b>Story:</b> {clean_title} (₹{price})\n"
                        f"💰 <b>Paid:</b> ₹{paid}\n🆔 <b>Order ID:</b> <code>{order_id}</code>"
                    )
                else:
                    await add_user_purchase(user_id, clean_title, story_id=story_id)
                    link = delivery_link(story_id) if story_id else None
                    notice = (
                        f"🎉 <b>ᴀᴜᴛᴏ-ᴠᴇʀɪғɪᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
                        f"📖 <b>Story:</b> {clean_title}\n"
                        f"💰 <b>Paid:</b> ₹{paid}\n\n"
                        f"Click below to access your files:"
                    )
                    if link:
                        notice_markup = InlineKeyboardMarkup([[
                            InlineKeyboardButton("📂 ɢᴇᴛ ғɪʟᴇs (Unlocked)", style=enums.ButtonStyle.PRIMARY, url=link)
                        ]])
                    log_msg = (
                        f"⚡ <b>[{source}] STORY BOUGHT</b>\n\n"
                        f"👤 <b>User:</b> {user_mention} (<code>{user_id}</code>)\n"
                        f"📖 <b>Story:</b> {clean_title}\n"
                        f"💰 <b>Amount Paid:</b> ₹{paid}\n"
                        f"🆔 <b>Order ID:</b> <code>{order_id}</code>"
                    )
    except Exception as e:
        # DB kaam fail hua -> order wapas open, taaki user dobara Verify dabaye
        print(f"❌ fulfill_order DB error for {order_id}: {e}")
        try:
            await release_payment_order(order_id)
        except Exception:
            pass
        return "error"

    # Messages (fail bhi ho jaye to paisa / story ho chuki hai, rollback nahi)
    try:
        await client.send_message(
            chat_id=user_id, text=notice, reply_markup=notice_markup, protect_content=False
        )
    except Exception as e:
        print(f"⚠ fulfill_order: user {user_id} ko message nahi gaya: {e}")

    if log_msg:
        await _log(client, log_msg)
    return "done"
