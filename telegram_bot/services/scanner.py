"""
Background payment scanner.

Periodically checks pending orders for incoming payments:
- Crypto payments via blockchain APIs
- PayPal payments via browser automation (checks transaction history)
- Bank transfers: manual (admin confirms via /confirm)

When a payment is detected, the order status is updated and
the admin is notified for payout.
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
from telegram_bot.services.paypal_checker import check_paypal_payment

logger = logging.getLogger(__name__)


async def run_payment_scanner(app: Application) -> None:
    """Background task: scan for incoming payments."""
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

        # Check crypto payments (for crypto_to_* orders)
        if order.exchange_type.startswith("crypto_to_") and order.crypto_currency and order.crypto_address:
            result = await check_crypto_payment(
                order.crypto_currency,
                order.crypto_address,
                order.crypto_amount,
            )
            if result and result.get("confirmed"):
                await _mark_payment_received(app, order, tx_hash=result.get("tx_hash", ""))
                continue

        # Check PayPal payments (for paypal_to_* orders)
        if order.exchange_type.startswith("paypal_to_"):
            result = await check_paypal_payment(
                order.order_id,
                order.amount_eur,
            )
            if result and result.get("confirmed"):
                await _mark_payment_received(
                    app, order, tx_hash=result.get("tx_id", "PayPal")
                )
                continue

        # Bank transfers (bank_to_*) remain manual — admin uses /confirm


async def _mark_payment_received(
    app: Application, order: Order, tx_hash: str = ""
) -> None:
    """Mark an order as payment received and notify user + admins."""
    order.status = OrderStatus.PAYMENT_RECEIVED
    order.tx_hash = tx_hash
    save_order(order)

    source = "Krypto" if order.exchange_type.startswith("crypto_to_") else "PayPal"
    tx_display = f"\nTX: {tx_hash[:24]}..." if tx_hash and tx_hash != "PayPal" else ""

    await _notify_user(
        app,
        order.user_id,
        f"{source}-Zahlung fuer Bestellung #{order.order_id} empfangen!{tx_display}\n"
        f"Deine Auszahlung wird jetzt bearbeitet.",
    )

    await _notify_admins(
        app,
        f"Zahlung empfangen!\n"
        f"Bestellung: #{order.order_id}\n"
        f"Typ: {order.exchange_type}\n"
        f"Betrag: {order.amount_eur:.2f} EUR\n"
        f"Quelle: {source}\n"
        f"{'Crypto: ' + str(order.crypto_amount) + ' ' + order.crypto_currency if order.crypto_currency else ''}\n"
        f"TX: {tx_hash}\n\n"
        f"Bitte Auszahlung durchfuehren:\n"
        f"/confirm {order.order_id}",
    )

    logger.info(
        "Payment received for order %s (%s, tx: %s)",
        order.order_id,
        source,
        tx_hash,
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
