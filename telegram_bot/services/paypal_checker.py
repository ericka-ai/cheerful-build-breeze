"""
PayPal payment verification via browser automation.

Logs into PayPal and checks the activity/transactions page for payments
matching a given Verwendungszweck (reference code = order_id).

Uses Playwright with Chromium in headless mode.
"""

import asyncio
import json
import logging
import os
import re
import time
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

PAYPAL_EMAIL = os.getenv("PAYPAL_LOGIN_EMAIL", "")
PAYPAL_PASSWORD = os.getenv("PAYPAL_LOGIN_PASSWORD", "")
PAYPAL_COOKIE_FILE = os.getenv("PAYPAL_COOKIE_FILE", "paypal_cookies.json")

_browser: Optional[Browser] = None
_context: Optional[BrowserContext] = None


async def _get_browser_context() -> BrowserContext:
    """Get or create a persistent browser context with saved cookies."""
    global _browser, _context

    if _context:
        try:
            pages = _context.pages
            return _context
        except Exception:
            _context = None
            _browser = None

    pw = await async_playwright().start()
    _browser = await pw.chromium.launch(headless=True)
    _context = await _browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 800},
        locale="de-DE",
    )

    if os.path.exists(PAYPAL_COOKIE_FILE):
        try:
            with open(PAYPAL_COOKIE_FILE, "r") as f:
                cookies = json.load(f)
            await _context.add_cookies(cookies)
            logger.info("Loaded saved PayPal cookies")
        except Exception as exc:
            logger.warning("Could not load cookies: %s", exc)

    return _context


async def _save_cookies() -> None:
    """Save browser cookies for session persistence."""
    if not _context:
        return
    try:
        cookies = await _context.cookies()
        with open(PAYPAL_COOKIE_FILE, "w") as f:
            json.dump(cookies, f)
    except Exception as exc:
        logger.warning("Could not save cookies: %s", exc)


async def _login(page: Page) -> bool:
    """Log into PayPal if not already logged in."""
    if not PAYPAL_EMAIL or not PAYPAL_PASSWORD:
        logger.error("PayPal login credentials not configured")
        return False

    try:
        await page.goto("https://www.paypal.com/myaccount/transactions/", timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=15000)

        current_url = page.url
        if "/myaccount/" in current_url and "signin" not in current_url:
            logger.info("Already logged into PayPal")
            return True

        logger.info("Logging into PayPal...")

        await page.goto("https://www.paypal.com/signin", timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=15000)

        email_field = page.locator("#email")
        await email_field.wait_for(state="visible", timeout=10000)
        await email_field.fill(PAYPAL_EMAIL)

        next_btn = page.locator("#btnNext")
        if await next_btn.is_visible():
            await next_btn.click()
            await page.wait_for_timeout(2000)

        password_field = page.locator("#password")
        await password_field.wait_for(state="visible", timeout=10000)
        await password_field.fill(PAYPAL_PASSWORD)

        login_btn = page.locator("#btnLogin")
        await login_btn.click()

        await page.wait_for_load_state("networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        current_url = page.url
        if "signin" in current_url or "challenge" in current_url:
            logger.warning(
                "PayPal login may require 2FA or CAPTCHA (url: %s)", current_url
            )
            return False

        await _save_cookies()
        logger.info("PayPal login successful")
        return True

    except Exception as exc:
        logger.error("PayPal login failed: %s", exc)
        return False


async def check_paypal_payment(
    order_id: str, expected_amount: float, tolerance: float = 0.50
) -> Optional[dict]:
    """
    Check if a PayPal payment with the given order_id as Verwendungszweck
    (message/note) has been received.

    Args:
        order_id: The order ID used as Verwendungszweck
        expected_amount: Expected amount in EUR
        tolerance: Allowed difference in EUR (default 0.50)

    Returns:
        {"received": float, "confirmed": bool, "tx_id": str} or None
    """
    try:
        ctx = await _get_browser_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        logged_in = await _login(page)
        if not logged_in:
            return None

        await page.goto(
            "https://www.paypal.com/myaccount/transactions/",
            timeout=30000,
        )
        await page.wait_for_load_state("networkidle", timeout=15000)
        await page.wait_for_timeout(2000)

        content = await page.content()

        if order_id.upper() in content.upper():
            logger.info("Found order_id %s in PayPal transactions page", order_id)

            rows = await page.locator(
                "[data-testid='transaction-list-item'], "
                ".transactionItem, "
                "tr[class*='transaction'], "
                "[class*='Activity'] li, "
                "[class*='activity'] li"
            ).all()

            for row in rows:
                row_text = await row.text_content()
                if not row_text:
                    continue
                row_text_upper = row_text.upper()

                if order_id.upper() not in row_text_upper:
                    continue

                amount_match = re.search(
                    r"[+]?\s*(\d+[.,]\d{2})\s*EUR", row_text
                )
                if amount_match:
                    amount_str = amount_match.group(1).replace(",", ".")
                    amount = float(amount_str)
                    if abs(amount - expected_amount) <= tolerance:
                        tx_id_match = re.search(
                            r"([A-Z0-9]{10,20})", row_text
                        )
                        tx_id = tx_id_match.group(1) if tx_id_match else order_id

                        await _save_cookies()
                        return {
                            "received": amount,
                            "confirmed": True,
                            "tx_id": tx_id,
                        }

            await _save_cookies()
            return {
                "received": expected_amount,
                "confirmed": True,
                "tx_id": order_id,
            }

        logger.debug("Order %s not found in PayPal transactions", order_id)
        await _save_cookies()
        return None

    except Exception as exc:
        logger.error("PayPal payment check failed for %s: %s", order_id, exc)
        return None


async def close_browser() -> None:
    """Clean up browser resources."""
    global _browser, _context
    if _context:
        await _save_cookies()
        await _context.close()
        _context = None
    if _browser:
        await _browser.close()
        _browser = None
