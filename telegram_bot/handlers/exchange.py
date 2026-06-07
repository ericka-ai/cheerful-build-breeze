"""
Exchange conversation flow handler.

This is the core handler that guides the user through the entire exchange
process step by step using a ConversationHandler.

Flow:
  1. User selects exchange type (from main menu callback)
  2. User selects crypto currency (if applicable)
  3. User enters amount in EUR
  4. User provides payout details (PayPal email, IBAN, or crypto address)
  5. Bot shows summary + fee breakdown
  6. User confirms
  7. Bot shows payment instructions + starts monitoring
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from telegram_bot.config import (
    EXCHANGE_TYPES,
    SUPPORTED_CRYPTO,
    WALLET_ADDRESSES,
)
from telegram_bot.models.order import Order, OrderStatus, save_order
from telegram_bot.services.crypto import eur_to_crypto, get_crypto_price_eur
from telegram_bot.services.fees import calculate_fee
from telegram_bot.services.payments import (
    get_bank_transfer_instructions,
    get_paypal_payment_instructions,
)

logger = logging.getLogger(__name__)

# Conversation states
SELECT_CRYPTO, ENTER_AMOUNT, ENTER_PAYOUT_DETAILS, CONFIRM_ORDER = range(4)


def _needs_crypto_selection(exchange_type: str) -> bool:
    """Whether this exchange type involves a crypto currency selection."""
    return exchange_type in (
        "crypto_to_paypal",
        "paypal_to_crypto",
        "crypto_to_bank",
        "bank_to_crypto",
    )


def _crypto_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for symbol, info in SUPPORTED_CRYPTO.items():
        buttons.append(
            [InlineKeyboardButton(f"{info['name']} ({symbol})", callback_data=f"crypto:{symbol}")]
        )
    buttons.append([InlineKeyboardButton("Abbrechen", callback_data="cancel_exchange")])
    return InlineKeyboardMarkup(buttons)


async def exchange_type_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 1: User selected an exchange type from the main menu."""
    query = update.callback_query
    await query.answer()

    exchange_type = query.data.replace("exchange:", "")
    if exchange_type not in EXCHANGE_TYPES:
        await query.edit_message_text("Ungueltiger Tauschtyp.")
        return ConversationHandler.END

    context.user_data["exchange_type"] = exchange_type
    info = EXCHANGE_TYPES[exchange_type]

    if _needs_crypto_selection(exchange_type):
        await query.edit_message_text(
            f"{info['emoji']}  {info['from']} -> {info['to']}\n\n"
            "Waehle die Kryptowaehrung:",
            reply_markup=_crypto_keyboard(),
        )
        return SELECT_CRYPTO
    else:
        context.user_data["crypto_currency"] = ""
        await query.edit_message_text(
            f"{info['emoji']}  {info['from']} -> {info['to']}\n\n"
            "Wie viel EUR moechtest du tauschen?\n"
            "(Gib den Betrag als Zahl ein, z.B. 50)"
        )
        return ENTER_AMOUNT


async def crypto_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 2: User selected a crypto currency."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_exchange":
        await query.edit_message_text("Bestellung abgebrochen.")
        return ConversationHandler.END

    symbol = query.data.replace("crypto:", "")
    if symbol not in SUPPORTED_CRYPTO:
        await query.edit_message_text("Unbekannte Kryptowaehrung.")
        return ConversationHandler.END

    context.user_data["crypto_currency"] = symbol

    price = await get_crypto_price_eur(symbol)
    price_text = f"(Aktueller Kurs: 1 {symbol} = {price:,.2f} EUR)\n\n" if price else "\n"

    await query.edit_message_text(
        f"Kryptowaehrung: {SUPPORTED_CRYPTO[symbol]['name']}\n"
        f"{price_text}"
        "Wie viel EUR moechtest du tauschen?\n"
        "(Gib den Betrag als Zahl ein, z.B. 50)"
    )
    return ENTER_AMOUNT


async def amount_entered(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 3: User entered an amount."""
    text = update.message.text.strip().replace(",", ".").replace("€", "").strip()

    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text(
            "Bitte gib eine gueltige Zahl ein (z.B. 50 oder 50.00):"
        )
        return ENTER_AMOUNT

    exchange_type = context.user_data["exchange_type"]
    fee_result = calculate_fee(exchange_type, amount)

    if not fee_result["valid"]:
        await update.message.reply_text(f"Fehler: {fee_result['error']}\nBitte nochmal:")
        return ENTER_AMOUNT

    context.user_data["amount_eur"] = amount
    context.user_data["fee_result"] = fee_result

    exchange_type = context.user_data["exchange_type"]

    if exchange_type in ("crypto_to_paypal", "bank_to_paypal"):
        await update.message.reply_text(
            "Bitte gib deine PayPal E-Mail-Adresse ein\n"
            "(dorthin wird die Auszahlung gesendet):"
        )
    elif exchange_type in ("crypto_to_bank", "paypal_to_bank"):
        await update.message.reply_text(
            "Bitte gib deine Bankdaten ein im Format:\n"
            "IBAN, Kontoinhaber\n\n"
            "Beispiel: DE89370400440532013000, Max Mustermann"
        )
    elif exchange_type in ("paypal_to_crypto", "bank_to_crypto"):
        crypto = context.user_data.get("crypto_currency", "BTC")
        await update.message.reply_text(
            f"Bitte gib deine {crypto}-Wallet-Adresse ein\n"
            "(dorthin werden deine Coins gesendet):"
        )
    else:
        await update.message.reply_text("Bitte gib deine Zahlungsdaten ein:")

    return ENTER_PAYOUT_DETAILS


async def payout_details_entered(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 4: User entered payout details. Show summary for confirmation."""
    text = update.message.text.strip()
    exchange_type = context.user_data["exchange_type"]

    if exchange_type in ("crypto_to_paypal", "bank_to_paypal"):
        if "@" not in text or "." not in text:
            await update.message.reply_text(
                "Das sieht nicht wie eine gueltige E-Mail aus. Bitte nochmal:"
            )
            return ENTER_PAYOUT_DETAILS
        context.user_data["paypal_email"] = text

    elif exchange_type in ("crypto_to_bank", "paypal_to_bank"):
        parts = [p.strip() for p in text.split(",")]
        if len(parts) < 2:
            await update.message.reply_text(
                "Bitte gib IBAN und Kontoinhaber getrennt durch Komma ein.\n"
                "Beispiel: DE89370400440532013000, Max Mustermann"
            )
            return ENTER_PAYOUT_DETAILS
        context.user_data["iban"] = parts[0]
        context.user_data["bank_holder"] = parts[1]

    elif exchange_type in ("paypal_to_crypto", "bank_to_crypto"):
        if len(text) < 20:
            await update.message.reply_text(
                "Die Adresse scheint zu kurz. Bitte pruefe und nochmal eingeben:"
            )
            return ENTER_PAYOUT_DETAILS
        context.user_data["crypto_address_out"] = text

    fee = context.user_data["fee_result"]
    amount = context.user_data["amount_eur"]
    info = EXCHANGE_TYPES[exchange_type]

    crypto_line = ""
    crypto = context.user_data.get("crypto_currency", "")
    if crypto:
        crypto_amount = await eur_to_crypto(amount, crypto)
        if crypto_amount:
            context.user_data["crypto_amount"] = crypto_amount
            crypto_line = f"Krypto-Betrag: ~{crypto_amount} {crypto}\n"

    payout_line = ""
    if context.user_data.get("paypal_email"):
        payout_line = f"PayPal: {context.user_data['paypal_email']}\n"
    elif context.user_data.get("iban"):
        payout_line = (
            f"IBAN: {context.user_data['iban']}\n"
            f"Inhaber: {context.user_data['bank_holder']}\n"
        )
    elif context.user_data.get("crypto_address_out"):
        payout_line = f"Wallet: {context.user_data['crypto_address_out']}\n"

    summary = (
        f"Bestellzusammenfassung\n"
        f"{'=' * 30}\n"
        f"Tausch: {info['from']} -> {info['to']}\n"
        f"{crypto_line}"
        f"Betrag: {amount:.2f} EUR\n"
        f"Gebuehr ({fee['fee_percent']:.1f}%): -{fee['fee_eur']:.2f} EUR\n"
        f"Auszahlung: {fee['payout_eur']:.2f} EUR\n"
        f"{payout_line}\n"
        f"Moechtest du die Bestellung aufgeben?"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Bestaetigen", callback_data="confirm_order"),
            InlineKeyboardButton("Abbrechen", callback_data="cancel_exchange"),
        ]
    ])

    await update.message.reply_text(summary, reply_markup=keyboard)
    return CONFIRM_ORDER


async def order_confirmed(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 5: User confirmed. Create order and show payment instructions."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_exchange":
        await query.edit_message_text("Bestellung abgebrochen.")
        context.user_data.clear()
        return ConversationHandler.END

    exchange_type = context.user_data["exchange_type"]
    fee = context.user_data["fee_result"]
    user = update.effective_user
    crypto = context.user_data.get("crypto_currency", "")

    order = Order(
        user_id=user.id,
        username=user.username or "",
        exchange_type=exchange_type,
        amount_eur=fee["amount_eur"],
        fee_percent=fee["fee_percent"],
        fee_eur=fee["fee_eur"],
        payout_eur=fee["payout_eur"],
        crypto_currency=crypto,
        crypto_amount=context.user_data.get("crypto_amount", 0),
        paypal_email=context.user_data.get("paypal_email", ""),
        iban=context.user_data.get("iban", ""),
        bank_holder=context.user_data.get("bank_holder", ""),
        status=OrderStatus.AWAITING_PAYMENT,
    )

    if exchange_type.startswith("crypto_to_"):
        order.from_currency = crypto
        order.crypto_address = WALLET_ADDRESSES.get(crypto, "")
        if exchange_type == "crypto_to_paypal":
            order.to_currency = "PayPal"
        else:
            order.to_currency = "Bank"
    elif exchange_type.startswith("paypal_to_"):
        order.from_currency = "PayPal"
        if exchange_type == "paypal_to_crypto":
            order.to_currency = crypto
            order.crypto_address = context.user_data.get("crypto_address_out", "")
        else:
            order.to_currency = "Bank"
    elif exchange_type.startswith("bank_to_"):
        order.from_currency = "Bank"
        if exchange_type == "bank_to_crypto":
            order.to_currency = crypto
            order.crypto_address = context.user_data.get("crypto_address_out", "")
        else:
            order.to_currency = "PayPal"

    save_order(order)

    payment_text = _build_payment_instructions(order)

    await query.edit_message_text(
        f"Bestellung #{order.order_id} erstellt!\n\n"
        f"{payment_text}\n\n"
        f"Status pruefen: /status {order.order_id}\n"
        f"Stornieren: /cancel {order.order_id}"
    )

    await _notify_admins_new_order(context, order)

    context.user_data.clear()
    return ConversationHandler.END


def _build_payment_instructions(order: Order) -> str:
    """Build payment instructions based on order type."""
    exchange_type = order.exchange_type

    if exchange_type.startswith("crypto_to_"):
        if not order.crypto_address:
            return (
                "Wallet-Adresse nicht konfiguriert.\n"
                "Bitte kontaktiere den Support."
            )
        return (
            f"Bitte sende genau {order.crypto_amount} {order.crypto_currency} an:\n\n"
            f"Adresse: {order.crypto_address}\n\n"
            f"Wichtig: Sende genau diesen Betrag!\n"
            f"Die Zahlung wird automatisch erkannt."
        )

    elif exchange_type.startswith("paypal_to_"):
        return get_paypal_payment_instructions(order.amount_eur, order.order_id)

    elif exchange_type.startswith("bank_to_"):
        return get_bank_transfer_instructions(order.amount_eur, order.order_id)

    return "Zahlungsanweisungen nicht verfuegbar. Bitte kontaktiere den Support."


async def _notify_admins_new_order(
    context: ContextTypes.DEFAULT_TYPE, order: Order
) -> None:
    """Notify admins about a new order."""
    from telegram_bot.config import ADMIN_CHAT_IDS

    text = (
        f"Neue Bestellung!\n"
        f"ID: #{order.order_id}\n"
        f"User: @{order.username} ({order.user_id})\n"
        f"Typ: {order.exchange_type}\n"
        f"Betrag: {order.amount_eur:.2f} EUR\n"
        f"Gebuehr: {order.fee_eur:.2f} EUR\n"
        f"Auszahlung: {order.payout_eur:.2f} EUR\n"
    )
    if order.crypto_currency:
        text += f"Crypto: {order.crypto_amount} {order.crypto_currency}\n"
    if order.paypal_email:
        text += f"PayPal: {order.paypal_email}\n"
    if order.iban:
        text += f"IBAN: {order.iban}\n"

    for admin_id in ADMIN_CHAT_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text)
        except Exception as exc:
            logger.warning("Could not notify admin %d: %s", admin_id, exc)


async def cancel_exchange(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle cancel during the conversation."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Bestellung abgebrochen.")
    elif update.message:
        await update.message.reply_text("Bestellung abgebrochen.")
    context.user_data.clear()
    return ConversationHandler.END


def get_exchange_conversation() -> ConversationHandler:
    """Build the exchange ConversationHandler."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                exchange_type_selected, pattern="^exchange:"
            ),
        ],
        states={
            SELECT_CRYPTO: [
                CallbackQueryHandler(crypto_selected, pattern="^crypto:"),
                CallbackQueryHandler(cancel_exchange, pattern="^cancel_exchange$"),
            ],
            ENTER_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, amount_entered),
            ],
            ENTER_PAYOUT_DETAILS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, payout_details_entered),
            ],
            CONFIRM_ORDER: [
                CallbackQueryHandler(
                    order_confirmed, pattern="^(confirm_order|cancel_exchange)$"
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_exchange),
            CommandHandler("start", cancel_exchange),
            CallbackQueryHandler(cancel_exchange, pattern="^cancel_exchange$"),
        ],
        per_user=True,
        per_chat=True,
    )
