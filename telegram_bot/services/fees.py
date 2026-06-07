"""
Fee calculation engine.

Fees are a percentage of the exchange amount. The customer always receives
the amount AFTER fees are deducted.
"""

from telegram_bot.config import FEES, MIN_AMOUNT_EUR, MAX_AMOUNT_EUR


def calculate_fee(exchange_type: str, amount_eur: float) -> dict:
    """
    Calculate fees for an exchange.

    Returns:
        {
            "amount_eur": original amount,
            "fee_percent": fee percentage,
            "fee_eur": fee in EUR,
            "payout_eur": amount after fee deduction,
            "valid": whether amount is within limits,
            "error": error message if invalid,
        }
    """
    fee_percent = FEES.get(exchange_type, 5.0)

    if amount_eur < MIN_AMOUNT_EUR:
        return {
            "amount_eur": amount_eur,
            "fee_percent": fee_percent,
            "fee_eur": 0,
            "payout_eur": 0,
            "valid": False,
            "error": f"Mindestbetrag: {MIN_AMOUNT_EUR:.2f} EUR",
        }

    if amount_eur > MAX_AMOUNT_EUR:
        return {
            "amount_eur": amount_eur,
            "fee_percent": fee_percent,
            "fee_eur": 0,
            "payout_eur": 0,
            "valid": False,
            "error": f"Maximalbetrag: {MAX_AMOUNT_EUR:.2f} EUR",
        }

    fee_eur = round(amount_eur * (fee_percent / 100), 2)
    payout_eur = round(amount_eur - fee_eur, 2)

    return {
        "amount_eur": amount_eur,
        "fee_percent": fee_percent,
        "fee_eur": fee_eur,
        "payout_eur": payout_eur,
        "valid": True,
        "error": "",
    }


def format_fee_summary(exchange_type: str, amount_eur: float) -> str:
    """Format a human-readable fee summary in German."""
    result = calculate_fee(exchange_type, amount_eur)
    if not result["valid"]:
        return f"Fehler: {result['error']}"

    return (
        f"Betrag: {result['amount_eur']:.2f} EUR\n"
        f"Gebuehr ({result['fee_percent']:.1f}%): -{result['fee_eur']:.2f} EUR\n"
        f"Auszahlung: {result['payout_eur']:.2f} EUR"
    )
