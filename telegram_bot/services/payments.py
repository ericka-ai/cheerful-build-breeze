"""
Payment processing service.

PayPal: Manual mode — customers send to a PayPal username with a
generated Verwendungszweck (reference). Admin verifies manually.
Bank transfers: Manual with notification to admin.
"""

import logging

from telegram_bot.config import (
    BANK_BIC,
    BANK_HOLDER,
    BANK_IBAN,
    BANK_NAME,
    PAYPAL_USERNAME,
)

logger = logging.getLogger(__name__)


# ── Bank transfer helpers ────────────────────────────────────────────────────

def get_bank_transfer_instructions(amount_eur: float, order_id: str) -> str:
    """Get bank transfer instructions for the customer."""
    if not BANK_IBAN:
        return (
            "Bankdaten sind noch nicht konfiguriert.\n"
            "Bitte kontaktiere den Support."
        )

    return (
        f"Bitte ueberweise {amount_eur:.2f} EUR an:\n\n"
        f"Empfaenger: {BANK_HOLDER}\n"
        f"IBAN: {BANK_IBAN}\n"
        f"BIC: {BANK_BIC}\n"
        f"Bank: {BANK_NAME}\n"
        f"Verwendungszweck: {order_id}\n\n"
        f"Wichtig: Gib als Verwendungszweck NUR die Bestellnummer an!"
    )


def get_paypal_payment_instructions(amount_eur: float, order_id: str) -> str:
    """Get PayPal payment instructions for the customer."""
    if not PAYPAL_USERNAME:
        return (
            "PayPal-Empfaenger ist noch nicht konfiguriert.\n"
            "Bitte kontaktiere den Support."
        )

    return (
        f"Bitte sende {amount_eur:.2f} EUR per PayPal an:\n\n"
        f"PayPal: @{PAYPAL_USERNAME}\n"
        f"Verwendungszweck: {order_id}\n\n"
        f"WICHTIG:\n"
        f"1. Nutze 'Geld an Freunde senden'\n"
        f"2. Gib als Nachricht/Verwendungszweck NUR ein: {order_id}\n"
        f"3. Ohne korrekten Verwendungszweck kann die Zahlung nicht zugeordnet werden!"
    )
