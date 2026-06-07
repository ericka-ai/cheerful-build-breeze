"""
Payment processing service.

Handles PayPal payouts and bank transfer instructions.
PayPal uses the Payouts API (requires business account with Payouts enabled).
Bank transfers are currently manual with notification to admin.
"""

import logging
from typing import Optional

import httpx

from telegram_bot.config import (
    BANK_BIC,
    BANK_HOLDER,
    BANK_IBAN,
    BANK_NAME,
    PAYPAL_CLIENT_ID,
    PAYPAL_CLIENT_SECRET,
    PAYPAL_EMAIL,
    PAYPAL_MODE,
)

logger = logging.getLogger(__name__)


# ── PayPal ───────────────────────────────────────────────────────────────────

_paypal_token_cache: dict[str, tuple[str, float]] = {}


def _paypal_base_url() -> str:
    if PAYPAL_MODE == "live":
        return "https://api-m.paypal.com"
    return "https://api-m.sandbox.paypal.com"


async def _get_paypal_access_token() -> Optional[str]:
    """Get an OAuth2 access token from PayPal."""
    if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
        logger.warning("PayPal credentials not configured")
        return None

    import time

    cached = _paypal_token_cache.get("token")
    if cached and time.time() < cached[1]:
        return cached[0]

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_paypal_base_url()}/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            token = data["access_token"]
            expires_in = data.get("expires_in", 3600)
            _paypal_token_cache["token"] = (token, time.time() + expires_in - 60)
            return token
    except Exception as exc:
        logger.error("PayPal auth failed: %s", exc)
        return None


async def send_paypal_payout(
    recipient_email: str, amount_eur: float, order_id: str
) -> dict:
    """
    Send a PayPal payout to the recipient.

    Returns:
        {"success": bool, "payout_id": str, "error": str}
    """
    token = await _get_paypal_access_token()
    if not token:
        return {
            "success": False,
            "payout_id": "",
            "error": "PayPal nicht konfiguriert. Bitte Admin kontaktieren.",
        }

    try:
        payload = {
            "sender_batch_header": {
                "sender_batch_id": f"exchange_{order_id}",
                "email_subject": "Exchange Auszahlung",
                "email_message": f"Ihre Auszahlung fuer Bestellung {order_id}",
            },
            "items": [
                {
                    "recipient_type": "EMAIL",
                    "amount": {"value": f"{amount_eur:.2f}", "currency": "EUR"},
                    "receiver": recipient_email,
                    "note": f"Exchange Bestellung #{order_id}",
                    "sender_item_id": order_id,
                }
            ],
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_paypal_base_url()}/v1/payments/payouts",
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        payout_id = data.get("batch_header", {}).get("payout_batch_id", "")
        return {"success": True, "payout_id": payout_id, "error": ""}

    except httpx.HTTPStatusError as exc:
        error_msg = f"PayPal Fehler: {exc.response.status_code}"
        try:
            error_data = exc.response.json()
            error_msg = error_data.get("message", error_msg)
        except Exception:
            pass
        logger.error("PayPal payout failed: %s", error_msg)
        return {"success": False, "payout_id": "", "error": error_msg}
    except Exception as exc:
        logger.error("PayPal payout exception: %s", exc)
        return {"success": False, "payout_id": "", "error": str(exc)}


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
    if not PAYPAL_EMAIL:
        return (
            "PayPal-Empfaenger ist noch nicht konfiguriert.\n"
            "Bitte kontaktiere den Support."
        )

    return (
        f"Bitte sende {amount_eur:.2f} EUR per PayPal an:\n\n"
        f"PayPal: {PAYPAL_EMAIL}\n"
        f"Verwendungszweck: {order_id}\n\n"
        f"Nutze 'Geld an Freunde senden', um Gebuehren zu vermeiden."
    )
