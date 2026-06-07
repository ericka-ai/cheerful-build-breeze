"""
Configuration for the Exchange Telegram Bot.

All sensitive values are loaded from environment variables.
"""

import os

# ── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_IDS: list[int] = [
    int(x) for x in os.getenv("ADMIN_CHAT_IDS", "").split(",") if x.strip()
]

# ── Database ─────────────────────────────────────────────────────────────────
DATABASE_PATH = os.getenv("DATABASE_PATH", "exchange_bot.db")

# ── Supported cryptocurrencies ───────────────────────────────────────────────
SUPPORTED_CRYPTO = {
    "BTC": {
        "name": "Bitcoin",
        "symbol": "BTC",
        "coingecko_id": "bitcoin",
        "decimals": 8,
        "min_amount_eur": 10.0,
        "network": "bitcoin",
    },
    "ETH": {
        "name": "Ethereum",
        "symbol": "ETH",
        "coingecko_id": "ethereum",
        "decimals": 18,
        "min_amount_eur": 10.0,
        "network": "ethereum",
    },
    "USDT": {
        "name": "Tether (TRC-20)",
        "symbol": "USDT",
        "coingecko_id": "tether",
        "decimals": 6,
        "min_amount_eur": 10.0,
        "network": "tron",
    },
    "LTC": {
        "name": "Litecoin",
        "symbol": "LTC",
        "coingecko_id": "litecoin",
        "decimals": 8,
        "min_amount_eur": 10.0,
        "network": "litecoin",
    },
    "SOL": {
        "name": "Solana",
        "symbol": "SOL",
        "coingecko_id": "solana",
        "decimals": 9,
        "min_amount_eur": 10.0,
        "network": "solana",
    },
}

# ── Wallet addresses (loaded from env) ──────────────────────────────────────
WALLET_ADDRESSES: dict[str, str] = {
    "BTC": os.getenv("WALLET_BTC", ""),
    "ETH": os.getenv("WALLET_ETH", ""),
    "USDT": os.getenv("WALLET_USDT", ""),
    "LTC": os.getenv("WALLET_LTC", ""),
    "SOL": os.getenv("WALLET_SOL", ""),
}

# ── Fee configuration (percentages) ─────────────────────────────────────────
FEES = {
    "crypto_to_paypal": float(os.getenv("FEE_CRYPTO_TO_PAYPAL", "5.0")),
    "paypal_to_crypto": float(os.getenv("FEE_PAYPAL_TO_CRYPTO", "5.0")),
    "crypto_to_bank": float(os.getenv("FEE_CRYPTO_TO_BANK", "3.0")),
    "bank_to_crypto": float(os.getenv("FEE_BANK_TO_CRYPTO", "3.0")),
    "paypal_to_bank": float(os.getenv("FEE_PAYPAL_TO_BANK", "2.0")),
    "bank_to_paypal": float(os.getenv("FEE_BANK_TO_PAYPAL", "2.0")),
}

# ── Payment limits (EUR) ────────────────────────────────────────────────────
MIN_AMOUNT_EUR = float(os.getenv("MIN_AMOUNT_EUR", "10.0"))
MAX_AMOUNT_EUR = float(os.getenv("MAX_AMOUNT_EUR", "5000.0"))

# ── PayPal ───────────────────────────────────────────────────────────────────
PAYPAL_USERNAME = os.getenv("PAYPAL_USERNAME", "")
PAYPAL_MODE = os.getenv("PAYPAL_MODE", "manual")  # "manual" (default)

# ── Bank details (for display to customers) ──────────────────────────────────
BANK_IBAN = os.getenv("BANK_IBAN", "")
BANK_BIC = os.getenv("BANK_BIC", "")
BANK_HOLDER = os.getenv("BANK_HOLDER", "")
BANK_NAME = os.getenv("BANK_NAME", "")

# ── Blockchain API keys (optional, for auto-scanning) ───────────────────────
BLOCKCYPHER_API_TOKEN = os.getenv("BLOCKCYPHER_API_TOKEN", "")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")

# ── Order expiry ─────────────────────────────────────────────────────────────
ORDER_EXPIRY_MINUTES = int(os.getenv("ORDER_EXPIRY_MINUTES", "30"))

# ── Polling interval for payment scanning (seconds) ─────────────────────────
PAYMENT_SCAN_INTERVAL = int(os.getenv("PAYMENT_SCAN_INTERVAL", "30"))

# ── Exchange types ───────────────────────────────────────────────────────────
EXCHANGE_TYPES = {
    "crypto_to_paypal": {"from": "Krypto", "to": "PayPal", "emoji": "🪙➡️💳"},
    "paypal_to_crypto": {"from": "PayPal", "to": "Krypto", "emoji": "💳➡️🪙"},
    "crypto_to_bank": {"from": "Krypto", "to": "Bankkonto", "emoji": "🪙➡️🏦"},
    "bank_to_crypto": {"from": "Bankkonto", "to": "Krypto", "emoji": "🏦➡️🪙"},
    "paypal_to_bank": {"from": "PayPal", "to": "Bankkonto", "emoji": "💳➡️🏦"},
    "bank_to_paypal": {"from": "Bankkonto", "to": "PayPal", "emoji": "🏦➡️💳"},
}
