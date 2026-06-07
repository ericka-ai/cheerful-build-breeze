"""
Admin command handlers.

Only users whose Telegram user ID is listed in ADMIN_CHAT_IDS can use these.
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from telegram_bot.config import ADMIN_CHAT_IDS
from telegram_bot.models.order import (
    Order,
    OrderStatus,
    get_all_orders,
    get_order,
    get_orders_by_status,
    get_stats,
    save_order,
    set_user_blocked,
    update_order_status,
)
from telegram_bot.services.payments import send_paypal_payout

logger = logging.getLogger(__name__)


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_CHAT_IDS


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin dashboard."""
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Kein Zugriff.")
        return

    stats = get_stats()
    text = (
        "Admin Dashboard\n"
        f"{'=' * 30}\n"
        f"Bestellungen gesamt: {stats['total_orders']}\n"
        f"Abgeschlossen: {stats['completed_orders']}\n"
        f"Offene Bestellungen: {stats['pending_orders']}\n"
        f"Volumen (abgeschlossen): {stats['total_volume_eur']:.2f} EUR\n"
        f"Registrierte Nutzer: {stats['total_users']}\n"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Offene Bestellungen", callback_data="admin:pending")],
        [InlineKeyboardButton("Alle Bestellungen", callback_data="admin:all")],
        [InlineKeyboardButton("Zahlungseingaenge", callback_data="admin:received")],
    ])

    await update.message.reply_text(text, reply_markup=keyboard)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin dashboard buttons."""
    query = update.callback_query
    if not _is_admin(update.effective_user.id):
        await query.answer("Kein Zugriff.")
        return
    await query.answer()

    action = query.data.replace("admin:", "")

    if action == "pending":
        orders = get_orders_by_status(OrderStatus.AWAITING_PAYMENT)
        orders += get_orders_by_status(OrderStatus.PROCESSING)
        title = "Offene Bestellungen"
    elif action == "received":
        orders = get_orders_by_status(OrderStatus.PAYMENT_RECEIVED)
        title = "Zahlungseingaenge (warten auf Auszahlung)"
    elif action == "all":
        orders = get_all_orders(limit=20)
        title = "Alle Bestellungen (letzte 20)"
    else:
        return

    if not orders:
        await query.edit_message_text(f"{title}\n\nKeine Bestellungen gefunden.")
        return

    lines = [f"{title}\n"]
    for o in orders:
        lines.append(
            f"#{o.order_id} | @{o.username} | "
            f"{o.amount_eur:.2f}EUR | {o.exchange_type} | "
            f"{o.status.value}"
        )

    buttons = []
    for o in orders[:5]:
        if o.status == OrderStatus.PAYMENT_RECEIVED:
            buttons.append([
                InlineKeyboardButton(
                    f"Auszahlen #{o.order_id}",
                    callback_data=f"admin_confirm:{o.order_id}",
                )
            ])

    buttons.append(
        [InlineKeyboardButton("<< Admin Menu", callback_data="admin:menu")]
    )

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def confirm_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /confirm <order_id> - Confirm an order and initiate payout.
    Admin manually triggers payout after verifying payment receipt.
    """
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Kein Zugriff.")
        return

    if not context.args:
        await update.message.reply_text("Nutzung: /confirm <Bestellnummer>")
        return

    order_id = context.args[0].upper()
    order = get_order(order_id)

    if not order:
        await update.message.reply_text("Bestellung nicht gefunden.")
        return

    if order.status == OrderStatus.COMPLETED:
        await update.message.reply_text("Bestellung ist bereits abgeschlossen.")
        return

    update_order_status(order_id, OrderStatus.PROCESSING)
    await update.message.reply_text(
        f"Bestellung #{order_id} wird bearbeitet...\n"
        f"Auszahlung: {order.payout_eur:.2f} EUR"
    )

    payout_result = await _process_payout(order, context)

    if payout_result["success"]:
        update_order_status(order_id, OrderStatus.COMPLETED)
        await update.message.reply_text(
            f"Bestellung #{order_id} abgeschlossen!\n"
            f"{payout_result['message']}"
        )
        try:
            await context.bot.send_message(
                chat_id=order.user_id,
                text=(
                    f"Deine Bestellung #{order_id} wurde abgeschlossen!\n"
                    f"Auszahlung: {order.payout_eur:.2f} EUR\n"
                    f"{payout_result['message']}\n\n"
                    f"Vielen Dank! Nutze /start fuer eine neue Bestellung."
                ),
            )
        except Exception as exc:
            logger.warning("Could not notify user: %s", exc)
    else:
        await update.message.reply_text(
            f"Auszahlung fehlgeschlagen fuer #{order_id}:\n"
            f"{payout_result['message']}\n\n"
            f"Bitte manuell auszahlen und dann /complete {order_id}"
        )


async def complete_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/complete <order_id> - Manually mark an order as completed."""
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Kein Zugriff.")
        return

    if not context.args:
        await update.message.reply_text("Nutzung: /complete <Bestellnummer>")
        return

    order_id = context.args[0].upper()
    order = get_order(order_id)
    if not order:
        await update.message.reply_text("Bestellung nicht gefunden.")
        return

    update_order_status(order_id, OrderStatus.COMPLETED)
    await update.message.reply_text(f"Bestellung #{order_id} als abgeschlossen markiert.")

    try:
        await context.bot.send_message(
            chat_id=order.user_id,
            text=(
                f"Deine Bestellung #{order_id} wurde abgeschlossen!\n"
                f"Auszahlung: {order.payout_eur:.2f} EUR\n\n"
                f"Vielen Dank! Nutze /start fuer eine neue Bestellung."
            ),
        )
    except Exception as exc:
        logger.warning("Could not notify user: %s", exc)


async def block_user_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/blockuser <user_id> - Block a user from using the bot."""
    if not _is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Nutzung: /blockuser <user_id>")
        return

    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Ungueltige User-ID.")
        return

    set_user_blocked(uid, True)
    await update.message.reply_text(f"User {uid} wurde gesperrt.")


async def unblock_user_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/unblockuser <user_id> - Unblock a user."""
    if not _is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Nutzung: /unblockuser <user_id>")
        return

    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Ungueltige User-ID.")
        return

    set_user_blocked(uid, False)
    await update.message.reply_text(f"User {uid} wurde entsperrt.")


async def _process_payout(order: Order, context: ContextTypes.DEFAULT_TYPE) -> dict:
    """Process the payout for an order."""
    exchange_type = order.exchange_type

    if exchange_type in ("crypto_to_paypal", "bank_to_paypal"):
        if not order.paypal_email:
            return {"success": False, "message": "Keine PayPal-Adresse hinterlegt."}
        result = await send_paypal_payout(
            order.paypal_email, order.payout_eur, order.order_id
        )
        if result["success"]:
            return {
                "success": True,
                "message": f"PayPal-Auszahlung gesendet (ID: {result['payout_id']})",
            }
        return {"success": False, "message": result["error"]}

    elif exchange_type in ("crypto_to_bank", "paypal_to_bank"):
        return {
            "success": False,
            "message": (
                f"Bankueberweisung muss manuell ausgefuehrt werden:\n"
                f"IBAN: {order.iban}\n"
                f"Inhaber: {order.bank_holder}\n"
                f"Betrag: {order.payout_eur:.2f} EUR\n\n"
                f"Nach Ueberweisung: /complete {order.order_id}"
            ),
        }

    elif exchange_type in ("paypal_to_crypto", "bank_to_crypto"):
        return {
            "success": False,
            "message": (
                f"Krypto-Auszahlung muss manuell ausgefuehrt werden:\n"
                f"Sende {order.crypto_amount} {order.crypto_currency} an:\n"
                f"{order.crypto_address}\n\n"
                f"Nach Versand: /complete {order.order_id}"
            ),
        }

    return {"success": False, "message": "Unbekannter Bestelltyp."}


async def admin_confirm_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle admin confirm button from order list."""
    query = update.callback_query
    if not _is_admin(update.effective_user.id):
        await query.answer("Kein Zugriff.")
        return
    await query.answer()

    order_id = query.data.replace("admin_confirm:", "")
    order = get_order(order_id)
    if not order:
        await query.edit_message_text("Bestellung nicht gefunden.")
        return

    update_order_status(order_id, OrderStatus.PROCESSING)
    await query.edit_message_text(
        f"Bearbeite Bestellung #{order_id}...\n"
        f"Auszahlung: {order.payout_eur:.2f} EUR"
    )

    payout_result = await _process_payout(order, context)

    if payout_result["success"]:
        update_order_status(order_id, OrderStatus.COMPLETED)
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=f"#{order_id} abgeschlossen!\n{payout_result['message']}",
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=(
                f"#{order_id} Auszahlung:\n{payout_result['message']}"
            ),
        )


def get_admin_handlers() -> list:
    return [
        CommandHandler("admin", admin_command),
        CommandHandler("confirm", confirm_command),
        CommandHandler("complete", complete_command),
        CommandHandler("blockuser", block_user_command),
        CommandHandler("unblockuser", unblock_user_command),
        CallbackQueryHandler(admin_callback, pattern="^admin:"),
        CallbackQueryHandler(admin_confirm_callback, pattern="^admin_confirm:"),
    ]
