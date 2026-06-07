"""
Exchange Telegram Bot - Main entry point.

A Telegram bot for peer-to-peer currency exchange:
  Crypto <-> PayPal
  Crypto <-> Bankkonto
  PayPal <-> Bankkonto

Usage:
    TELEGRAM_BOT_TOKEN=... python -m telegram_bot.bot
"""

import asyncio
import logging
import sys

from telegram.ext import Application

from telegram_bot.config import TELEGRAM_BOT_TOKEN
from telegram_bot.handlers.admin import get_admin_handlers
from telegram_bot.handlers.exchange import get_exchange_conversation
from telegram_bot.handlers.start import get_start_handlers
from telegram_bot.models.order import init_db
from telegram_bot.services.scanner import run_payment_scanner

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(app: Application) -> None:
    """Called after the bot has been initialized."""
    init_db()
    logger.info("Database initialized")

    asyncio.create_task(run_payment_scanner(app))
    logger.info("Payment scanner started")


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN not set. "
            "Set it as an environment variable and restart."
        )
        sys.exit(1)

    logger.info("Starting Exchange Bot...")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Register the exchange conversation handler first (highest priority)
    app.add_handler(get_exchange_conversation())

    # Register start / menu / utility handlers
    for handler in get_start_handlers():
        app.add_handler(handler)

    # Register admin handlers
    for handler in get_admin_handlers():
        app.add_handler(handler)

    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
