"""
Cryptocurrency price fetching and blockchain payment monitoring.

Uses free APIs:
- CoinGecko for prices
- BlockCypher / Etherscan / Tronscan for transaction monitoring
"""

import asyncio
import logging
from typing import Optional

import httpx

from telegram_bot.config import (
    BLOCKCYPHER_API_TOKEN,
    ETHERSCAN_API_KEY,
    SUPPORTED_CRYPTO,
)

logger = logging.getLogger(__name__)

_price_cache: dict[str, tuple[float, float]] = {}  # {coin_id: (price, timestamp)}
CACHE_TTL = 60  # seconds


async def get_crypto_price_eur(symbol: str) -> Optional[float]:
    """Fetch current price of a cryptocurrency in EUR via CoinGecko."""
    info = SUPPORTED_CRYPTO.get(symbol)
    if not info:
        return None

    coin_id = info["coingecko_id"]
    import time

    now = time.time()
    cached = _price_cache.get(coin_id)
    if cached and (now - cached[1]) < CACHE_TTL:
        return cached[0]

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": coin_id, "vs_currencies": "eur"},
            )
            resp.raise_for_status()
            data = resp.json()
            price = float(data[coin_id]["eur"])
            _price_cache[coin_id] = (price, now)
            return price
    except Exception as exc:
        logger.warning("CoinGecko price fetch failed for %s: %s", symbol, exc)
        if cached:
            return cached[0]
        return None


async def eur_to_crypto(eur_amount: float, symbol: str) -> Optional[float]:
    """Convert EUR amount to crypto amount."""
    price = await get_crypto_price_eur(symbol)
    if not price or price <= 0:
        return None
    return round(eur_amount / price, SUPPORTED_CRYPTO[symbol]["decimals"])


async def crypto_to_eur(crypto_amount: float, symbol: str) -> Optional[float]:
    """Convert crypto amount to EUR."""
    price = await get_crypto_price_eur(symbol)
    if not price:
        return None
    return round(crypto_amount * price, 2)


async def check_btc_payment(address: str, expected_amount: float) -> Optional[dict]:
    """Check if a BTC payment was received at the given address."""
    try:
        url = f"https://api.blockcypher.com/v1/btc/main/addrs/{address}"
        params = {}
        if BLOCKCYPHER_API_TOKEN:
            params["token"] = BLOCKCYPHER_API_TOKEN

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        total_received_btc = data.get("total_received", 0) / 1e8

        if total_received_btc >= expected_amount * 0.99:
            txs = data.get("txrefs", [])
            tx_hash = txs[0]["tx_hash"] if txs else ""
            return {
                "received": total_received_btc,
                "confirmed": data.get("n_tx", 0) > 0,
                "tx_hash": tx_hash,
            }
    except Exception as exc:
        logger.warning("BTC payment check failed for %s: %s", address, exc)
    return None


async def check_eth_payment(address: str, expected_amount: float) -> Optional[dict]:
    """Check if an ETH payment was received at the given address."""
    if not ETHERSCAN_API_KEY:
        logger.warning("ETHERSCAN_API_KEY not set, cannot check ETH payments")
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.etherscan.io/api",
                params={
                    "module": "account",
                    "action": "txlist",
                    "address": address,
                    "startblock": 0,
                    "endblock": 99999999,
                    "sort": "desc",
                    "apikey": ETHERSCAN_API_KEY,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "1":
            return None

        txs = data.get("result", [])
        for tx in txs[:10]:
            value_eth = int(tx["value"]) / 1e18
            if value_eth >= expected_amount * 0.99 and tx.get("to", "").lower() == address.lower():
                return {
                    "received": value_eth,
                    "confirmed": int(tx.get("confirmations", 0)) > 0,
                    "tx_hash": tx.get("hash", ""),
                }
    except Exception as exc:
        logger.warning("ETH payment check failed for %s: %s", address, exc)
    return None


async def check_crypto_payment(
    symbol: str, address: str, expected_amount: float
) -> Optional[dict]:
    """Check if a crypto payment was received. Dispatches to the right chain."""
    if symbol == "BTC":
        return await check_btc_payment(address, expected_amount)
    elif symbol == "ETH":
        return await check_eth_payment(address, expected_amount)
    elif symbol == "LTC":
        return await _check_ltc_payment(address, expected_amount)
    elif symbol == "USDT":
        logger.info("USDT (TRC-20) auto-scan not yet implemented; manual check needed")
        return None
    return None


async def _check_ltc_payment(address: str, expected_amount: float) -> Optional[dict]:
    """Check LTC payments via BlockCypher."""
    try:
        url = f"https://api.blockcypher.com/v1/ltc/main/addrs/{address}"
        params = {}
        if BLOCKCYPHER_API_TOKEN:
            params["token"] = BLOCKCYPHER_API_TOKEN

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        total_received = data.get("total_received", 0) / 1e8
        if total_received >= expected_amount * 0.99:
            txs = data.get("txrefs", [])
            tx_hash = txs[0]["tx_hash"] if txs else ""
            return {
                "received": total_received,
                "confirmed": data.get("n_tx", 0) > 0,
                "tx_hash": tx_hash,
            }
    except Exception as exc:
        logger.warning("LTC payment check failed for %s: %s", address, exc)
    return None
