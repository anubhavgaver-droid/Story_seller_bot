"""
"I paid but got nothing" support flow.

User side : the button under the invoice (sos:<order_id>).
            The bot first re-checks the payment with the gateway. If it is paid, the order is completed at once.
            Otherwise one request (never more than one per order) is sent to the admin.
Admin side: three buttons on that request
            - Check with gateway  : re-check and complete the order if it is paid
            - Force deliver       : the admin confirms the payment manually (asks for a second confirmation)
            - Decline             : tells the user the payment could not be found
"""
import time
import html

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_ID
from gateway import check_order_status
from fulfill import fulfill_order
from database.db import get_payment_order, mark_order_sos
from style import sc


def _btn(text, data):
    return InlineKeyboardButton(text, callback_data=data)


def _ago(ts: float) -> str:
    secs = max(0, int(time.time() - (ts or 0)))
    if secs < 120:
        return f"{secs} seconds ago"
    if secs < 7200:
        return f"{secs // 60} minutes ago"
    return f"{secs // 3600} hours ago"


# ------------------------------- USER -------------------------------
@Client.on_callback_query(filters.regex(r"^sos:"))
async def sos_user(client, callback):
    user = callback.from_user
    order = await get_payment_order(callback.data[len("sos:"):])

    if not order or order["user_id"] != user.id:
        return await callback.answer("This order was not found.", show_alert=True)

    if order.get("status") == "PAID":
        return await callback.answer("This payment is already verified. Please check your chat or My Account.", show_alert=True)

    if not await mark_order_sos(order["order_id"]):
        return await callback.answer("Your request was already sent. The admin will check it soon.", show_alert=True)

    await callback.answer("Checking your payment...")

    # 1) Maybe it is simply paid and the user did not press Verify: complete it right away.
    paid, amount, _msg = await check_order_status(order["order_id"])
    if paid:
        result = await fulfill_order(client, order, amount, "SUPPORT AUTO")
        if result in ("done", "already"):
            return

    # 2) Not confirmed by the gateway: send the request to the admin.
    text = (
        f"🆘 <b>{sc('Payment support request')}</b>\n\n"
        f"👤 <b>User:</b> <a href='tg://user?id={user.id}'>{html.escape(user.first_name or 'User')}</a> "
        f"(<code>{user.id}</code>)\n"
        f"📌 <b>Item:</b> {html.escape(str(order.get('title') or order.get('kind')))} ({order.get('kind')})\n"
        f"💰 <b>Amount:</b> ₹{order.get('amount'):g}\n"
        f"🏷 <b>Gateway:</b> {order.get('provider', 'demotry')}\n"
        f"🆔 <b>Order ID:</b> <code>{order['order_id']}</code>\n"
        f"🕒 <b>Created:</b> {_ago(order.get('created_at'))}\n\n"
        "The gateway does <b>not</b> show this order as paid yet."
    )
    kb = InlineKeyboardMarkup([
        [_btn(f"🔍 {sc('Check with gateway')}", f"sosa:chk:{order['order_id']}")],
        [_btn(f"✅ {sc('Force deliver')}", f"sosa:ok:{order['order_id']}"), _btn(f"❌ {sc('Decline')}", f"sosa:no:{order['order_id']}")],
    ])
    try:
        await client.send_message(ADMIN_ID, text, reply_markup=kb)
    except Exception as e:
        print(f"SOS: could not message the admin: {e}")

    await callback.message.reply_text(
        f"📨 <b>{sc('Request sent')}</b>\nThe admin has been notified and will check your payment shortly."
    )


# ------------------------------- ADMIN -------------------------------
@Client.on_callback_query(filters.regex(r"^sosa:") & filters.user(ADMIN_ID))
async def sos_admin(client, callback):
    _, action, order_id = callback.data.split(":", 2)
    order = await get_payment_order(order_id)
    if not order:
        return await callback.answer("Order not found.", show_alert=True)

    if order.get("status") == "PAID" and action != "no":
        return await callback.answer("This order is already completed.", show_alert=True)

    base = callback.message.text.html if callback.message.text else ""

    async def mark(note: str):
        try:
            await callback.message.edit_text(f"{base}\n\n{note}")
        except Exception:
            pass

    if action == "chk":
        await callback.answer("Checking with the gateway...")
        paid, amount, msg = await check_order_status(order_id)
        if not paid:
            return await callback.message.reply_text(f"ℹ️ The gateway does not show this order as paid yet.\n<code>{html.escape(str(msg))[:150]}</code>")
        result = await fulfill_order(client, order, amount, "SUPPORT ADMIN")
        return await mark(f"✅ <b>DELIVERED</b> (verified by the gateway, result: {result})")

    if action == "ok":
        # Second confirmation: forcing delivery without gateway proof is the admin's own decision.
        kb = InlineKeyboardMarkup([[
            _btn(f"✅ {sc('Yes, deliver')}", f"sosa:okc:{order_id}"), _btn(f"⬅️ {sc('No')}", f"sosa:back:{order_id}")
        ]])
        await callback.answer()
        return await callback.message.edit_reply_markup(kb)

    if action == "back":
        await callback.answer()
        kb = InlineKeyboardMarkup([
            [_btn(f"🔍 {sc('Check with gateway')}", f"sosa:chk:{order_id}")],
            [_btn(f"✅ {sc('Force deliver')}", f"sosa:ok:{order_id}"), _btn(f"❌ {sc('Decline')}", f"sosa:no:{order_id}")],
        ])
        return await callback.message.edit_reply_markup(kb)

    if action == "okc":
        result = await fulfill_order(client, order, float(order.get("amount", 0)), "ADMIN FORCE")
        await callback.answer("Delivered.", show_alert=True)
        return await mark(f"✅ <b>DELIVERED BY ADMIN</b> (forced, result: {result})")

    if action == "no":
        try:
            await client.send_message(
                order["user_id"],
                f"❌ <b>{sc('Payment not found')}</b>\nWe could not find a payment for order <code>{order_id}</code>. "
                "If you were charged, please contact the owner with your payment screenshot."
            )
        except Exception as e:
            print(f"SOS decline: could not message the user: {e}")
        await callback.answer("Declined.")
        return await mark("❌ <b>DECLINED</b>")

    await callback.answer()
