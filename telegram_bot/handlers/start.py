"""
/start and main menu handlers.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from telegram_bot.config import EXCHANGE_TYPES
from telegram_bot.models.order import get_user_orders, is_user_blocked, upsert_user

WELCOME_TEXT = (
    "Willkommen beim Exchange Bot!\n\n"
    "Hier kannst du schnell und sicher tauschen:\n"
    "  Krypto <-> PayPal\n"
    "  Krypto <-> Bankkonto\n"
    "  PayPal <-> Bankkonto\n\n"
    "Waehle eine Option:"
)


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for key, info in EXCHANGE_TYPES.items():
        label = f"{info['emoji']}  {info['from']} -> {info['to']}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"exchange:{key}")])

    buttons.append(
        [InlineKeyboardButton("Meine Bestellungen", callback_data="my_orders")]
    )
    buttons.append([InlineKeyboardButton("Hilfe / Support", callback_data="help")])
    return InlineKeyboardMarkup(buttons)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user = update.effective_user
    if not user:
        return

    upsert_user(user.id, user.username or "", user.first_name or "")

    if is_user_blocked(user.id):
        await update.message.reply_text(
            "Dein Konto wurde gesperrt. Bitte kontaktiere den Support."
        )
        return

    await update.message.reply_text(
        WELCOME_TEXT, reply_markup=_main_menu_keyboard()
    )


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle main menu button taps that aren't exchange selections."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    if query.data == "main_menu":
        await query.edit_message_text(
            WELCOME_TEXT, reply_markup=_main_menu_keyboard()
        )

    elif query.data == "my_orders":
        user_id = update.effective_user.id
        orders = get_user_orders(user_id, limit=5)
        if not orders:
            text = "Du hast noch keine Bestellungen."
        else:
            lines = ["Deine letzten Bestellungen:\n"]
            for o in orders:
                status_emoji = {
                    "pending": "...",
                    "awaiting_payment": "...",
                    "payment_received": "...",
                    "processing": "...",
                    "completed": "[OK]",
                    "cancelled": "[X]",
                    "expired": "[X]",
                    "disputed": "[!]",
                }.get(o.status.value, "?")
                lines.append(
                    f"{status_emoji} #{o.order_id} | "
                    f"{o.amount_eur:.2f} EUR | "
                    f"{o.exchange_type} | "
                    f"{o.status.value}"
                )
            text = "\n".join(lines)

        back_btn = InlineKeyboardMarkup(
            [[InlineKeyboardButton("<< Zurueck", callback_data="main_menu")]]
        )
        await query.edit_message_text(text, reply_markup=back_btn)

    elif query.data == "help":
        help_text = (
            "Hilfe & Support\n\n"
            "So funktioniert's:\n"
            "1. Waehle einen Tausch-Typ\n"
            "2. Gib den Betrag ein (in EUR)\n"
            "3. Gib deine Zahlungsdaten an\n"
            "4. Sende die Zahlung\n"
            "5. Wir pruefen & zahlen aus\n\n"
            "Befehle:\n"
            "/start - Hauptmenue\n"
            "/status <ID> - Bestellstatus pruefen\n"
            "/cancel <ID> - Bestellung stornieren\n\n"
            "Bei Problemen: Schreibe uns direkt hier."
        )
        back_btn = InlineKeyboardMarkup(
            [[InlineKeyboardButton("<< Zurueck", callback_data="main_menu")]]
        )
        await query.edit_message_text(help_text, reply_markup=back_btn)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status <order_id> command."""
    if not context.args:
        await update.message.reply_text("Nutzung: /status <Bestellnummer>")
        return

    from telegram_bot.models.order import get_order

    order_id = context.args[0].upper()
    order = get_order(order_id)

    if not order or order.user_id != update.effective_user.id:
        await update.message.reply_text("Bestellung nicht gefunden.")
        return

    text = (
        f"Bestellung #{order.order_id}\n"
        f"Typ: {order.exchange_type}\n"
        f"Betrag: {order.amount_eur:.2f} EUR\n"
        f"Gebuehr: {order.fee_eur:.2f} EUR ({order.fee_percent:.1f}%)\n"
        f"Auszahlung: {order.payout_eur:.2f} EUR\n"
        f"Status: {order.status.value}\n"
    )
    if order.tx_hash:
        text += f"TX: {order.tx_hash[:32]}...\n"

    await update.message.reply_text(text)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cancel <order_id> command."""
    if not context.args:
        await update.message.reply_text("Nutzung: /cancel <Bestellnummer>")
        return

    from telegram_bot.models.order import get_order, update_order_status, OrderStatus

    order_id = context.args[0].upper()
    order = get_order(order_id)

    if not order or order.user_id != update.effective_user.id:
        await update.message.reply_text("Bestellung nicht gefunden.")
        return

    if order.status in (OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.EXPIRED):
        await update.message.reply_text(
            f"Bestellung #{order_id} kann nicht storniert werden (Status: {order.status.value})."
        )
        return

    if order.status == OrderStatus.PAYMENT_RECEIVED:
        await update.message.reply_text(
            "Zahlung wurde bereits empfangen. "
            "Bitte kontaktiere den Support fuer eine Rueckerstattung."
        )
        return

    update_order_status(order_id, OrderStatus.CANCELLED)
    await update.message.reply_text(f"Bestellung #{order_id} wurde storniert.")


def get_start_handlers() -> list:
    return [
        CommandHandler("start", start_command),
        CommandHandler("status", status_command),
        CommandHandler("cancel", cancel_command),
        CallbackQueryHandler(menu_callback, pattern="^(main_menu|my_orders|help)$"),
    ]
