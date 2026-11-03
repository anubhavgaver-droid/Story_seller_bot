"""
Completes a paid order in ONE place (the Verify button, the webhook and the admin support tools all use it).

claim_payment_order() is atomic, so even if the user presses Verify five times or the webhook arrives at the
same moment, the wallet credit / story unlock happens exactly once.
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
from bonus import bonus_amount
from style import sc


async def _log(client, text: str):
    if LOG_CHANNEL and LOG_CHANNEL != 0:
        try:
            await client.send_message(chat_id=LOG_CHANNEL, text=text, disable_web_page_preview=True)
        except Exception as e:
            print(f"LOG_CHANNEL error: {e}")


async def fulfill_order(client, order: dict, paid_amount: float, source: str = "AUTO VERIFY") -> str:
    """
    Returns "done" | "already" | "error".
    `source` is only used in the admin log (AUTO VERIFY, WEBHOOK, ADMIN FORCE ...).
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
    notice = None           # message for the user
    notice_markup = None
    log_msg = None

    try:
        # ---------------- WALLET TOP-UP ----------------
        if order.get("kind") == "WALLET":
            bonus = await bonus_amount(paid)
            new_bal = await add_wallet_balance(user_id, paid + bonus)
            bonus_line = f"🎁 <b>{sc('Bonus')}:</b> +₹{bonus:g}\n" if bonus else ""
            notice = (
                f"🎉 <b>{sc('Payment verified')}</b>\n\n"
                f"💰 <b>{sc('Added')}:</b> ₹{paid:g}\n"
                f"{bonus_line}"
                f"👛 <b>{sc('New balance')}:</b> ₹{new_bal}"
            )
            log_msg = (
                f"💳 <b>[{source}] {sc('Wallet top-up')}</b>\n\n"
                f"👤 <b>User:</b> {user_mention} (<code>{user_id}</code>)\n"
                f"💰 <b>Amount:</b> ₹{paid:g}" + (f" (+₹{bonus:g} bonus)" if bonus else "") + "\n"
                f"👛 <b>New balance:</b> ₹{new_bal}\n"
                f"🆔 <b>Order ID:</b> <code>{order_id}</code>"
            )

        # ---------------- STORY PURCHASE ----------------
        else:
            story = await get_story_by_key(order.get("story_id") or order.get("title"))

            if story is None:
                # The story was deleted: put the money in the wallet so nothing is lost.
                new_bal = await add_wallet_balance(user_id, paid)
                notice = (
                    f"⚠️ <b>{sc('Story unavailable')}</b>\n\n"
                    f"This story is no longer available, so ₹{paid:g} was added to your wallet.\n"
                    f"👛 Balance: ₹{new_bal}"
                )
                log_msg = (
                    f"⚠️ <b>[{source}] {sc('Story missing, wallet credit')}</b>\n\n"
                    f"👤 <b>User:</b> {user_mention} (<code>{user_id}</code>)\n"
                    f"💰 <b>Amount:</b> ₹{paid:g}\n🆔 <b>Order ID:</b> <code>{order_id}</code>"
                )
            else:
                price = float(story.get("price", 0) or 0)
                clean_title = story["title"].strip().split("\n")[0]
                story_id = story.get("story_id")

                if paid + 0.01 < price:
                    # Underpaid: do not unlock, credit what was paid to the wallet.
                    new_bal = await add_wallet_balance(user_id, paid)
                    notice = (
                        f"⚠️ <b>{sc('Amount too low')}</b>\n\n"
                        f"The story costs ₹{price:g}, but you paid ₹{paid:g}.\n"
                        f"₹{paid:g} was added to your wallet (balance ₹{new_bal}). "
                        f"You can now buy the story using your wallet."
                    )
                    log_msg = (
                        f"⚠️ <b>[{source}] {sc('Underpaid, wallet credit')}</b>\n\n"
                        f"👤 <b>User:</b> {user_mention} (<code>{user_id}</code>)\n"
                        f"📖 <b>Story:</b> {clean_title} (₹{price:g})\n"
                        f"💰 <b>Paid:</b> ₹{paid:g}\n🆔 <b>Order ID:</b> <code>{order_id}</code>"
                    )
                else:
                    await add_user_purchase(user_id, clean_title, story_id=story_id)
                    link = delivery_link(story_id) if story_id else None
                    notice = (
                        f"🎉 <b>{sc('Payment verified')}</b>\n\n"
                        f"📖 <b>{sc('Story')}:</b> {clean_title}\n"
                        f"💰 <b>{sc('Paid')}:</b> ₹{paid:g}\n\n"
                        f"Tap the button below to get your files."
                    )
                    if link:
                        notice_markup = InlineKeyboardMarkup([[
                            InlineKeyboardButton(f"📂 {sc('Get files')}", style=enums.ButtonStyle.PRIMARY, url=link)
                        ]])
                    log_msg = (
                        f"⚡ <b>[{source}] {sc('Story bought')}</b>\n\n"
                        f"👤 <b>User:</b> {user_mention} (<code>{user_id}</code>)\n"
                        f"📖 <b>Story:</b> {clean_title}\n"
                        f"💰 <b>Amount paid:</b> ₹{paid:g}\n"
                        f"🆔 <b>Order ID:</b> <code>{order_id}</code>"
                    )
    except Exception as e:
        # A database step failed: reopen the order so the user can press Verify again.
        print(f"fulfill_order database error for {order_id}: {e}")
        try:
            await release_payment_order(order_id)
        except Exception:
            pass
        return "error"

    # Messages: even if they fail, the money / story is already handled, so there is no rollback.
    try:
        await client.send_message(chat_id=user_id, text=notice, reply_markup=notice_markup, protect_content=False)
    except Exception as e:
        print(f"fulfill_order: could not message user {user_id}: {e}")

    if log_msg:
        await _log(client, log_msg)
    return "done"
