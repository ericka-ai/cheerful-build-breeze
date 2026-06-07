"""
Background payment scanner.

Periodically checks pending orders for incoming crypto payments.
When a payment is detected, the order status is updated and
the admin is notified for manual payout confirmation.
"""

import asyncio
import logging
import time

from telegram.ext import Application

from telegram_bot.config import ADMIN_CHAT_IDS, ORDER_EXPIRY_MINUTES, PAYMENT_SCAN_INTERVAL
from telegram_bot.models.order import (
    Order,
    OrderStatus,
    get_orders_by_status,
    update_order_status,
    save_order,
)
from telegram_bot.services.crypto import check_crypto_payment

logger = logging.getLogger(__name__)


async def run_payment_scanner(app: Application) -> None:
    """Background task: scan for incoming crypto payments."""
    logger.info("Payment scanner started (interval: %ds)", PAYMENT_SCAN_INTERVAL)

    while True:
        try:
            await _scan_once(app)
        except Exception as exc:
            logger.error("Payment scanner error: %s", exc)

        await asyncio.sleep(PAYMENT_SCAN_INTERVAL)


async def _scan_once(app: Application) -> None:
    """Single scan iteration."""
    orders = get_orders_by_status(OrderStatus.AWAITING_PAYMENT)

    for order in orders:
        age_minutes = (time.time() - order.created_at) / 60
        if age_minutes > ORDER_EXPIRY_MINUTES:
            update_order_status(order.order_id, OrderStatus.EXPIRED)
            await _notify_user(
                app,
                order.user_id,
                f"Bestellung #{order.order_id} ist abgelaufen.\n"
                f"Erstelle eine neue Bestellung mit /start.",
            )
            logger.info("Order %s expired", order.order_id)
            continue

        if not order.crypto_currency or not order.crypto_address:
            continue

        result = await check_crypto_payment(
            order.crypto_currency,
            order.crypto_address,
            order.crypto_amount,
        )

        if result and result.get("confirmed"):
            order.status = OrderStatus.PAYMENT_RECEIVED
            order.tx_hash = result.get("tx_hash", "")
            save_order(order)

            await _notify_user(
                app,
                order.user_id,
                f"Zahlung fuer Bestellung #{order.order_id} empfangen!\n"
                f"TX: {order.tx_hash[:16]}...\n"
                f"Deine Auszahlung wird jetzt bearbeitet.",
            )

            await _notify_admins(
                app,
                f"Zahlung empfangen!\n"
                f"Bestellung: #{order.order_id}\n"
                f"Typ: {order.exchange_type}\n"
                f"Betrag: {order.amount_eur:.2f} EUR\n"
                f"Crypto: {order.crypto_amount} {order.crypto_currency}\n"
                f"TX: {order.tx_hash}\n\n"
                f"Bitte Auszahlung bestaetigen:\n"
                f"/confirm {order.order_id}",
            )
            logger.info(
                "Payment received for order %s: %s %s (tx: %s)",
                order.order_id,
                result["received"],
                order.crypto_currency,
                order.tx_hash,
            )


async def _notify_user(app: Application, user_id: int, message: str) -> None:
    try:
        await app.bot.send_message(chat_id=user_id, text=message)
    except Exception as exc:
        logger.warning("Could not notify user %d: %s", user_id, exc)


async def _notify_admins(app: Application, message: str) -> None:
    for admin_id in ADMIN_CHAT_IDS:
        try:
            await app.bot.send_message(chat_id=admin_id, text=message)
        except Exception as exc:
            logger.warning("Could not notify admin %d: %s", admin_id, exc)
