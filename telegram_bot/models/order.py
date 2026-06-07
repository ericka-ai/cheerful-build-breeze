"""
Order data model and database layer using SQLite.
"""

import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from telegram_bot.config import DATABASE_PATH


class OrderStatus(Enum):
    PENDING = "pending"
    AWAITING_PAYMENT = "awaiting_payment"
    PAYMENT_RECEIVED = "payment_received"
    PROCESSING = "processing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    DISPUTED = "disputed"


@dataclass
class Order:
    order_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12].upper())
    user_id: int = 0
    username: str = ""
    exchange_type: str = ""
    from_currency: str = ""
    to_currency: str = ""
    amount_eur: float = 0.0
    fee_percent: float = 0.0
    fee_eur: float = 0.0
    payout_eur: float = 0.0
    crypto_amount: float = 0.0
    crypto_currency: str = ""
    crypto_address: str = ""
    paypal_email: str = ""
    iban: str = ""
    bank_holder: str = ""
    status: OrderStatus = OrderStatus.PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    tx_hash: str = ""
    notes: str = ""


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id       TEXT PRIMARY KEY,
            user_id        INTEGER NOT NULL,
            username       TEXT DEFAULT '',
            exchange_type  TEXT NOT NULL,
            from_currency  TEXT DEFAULT '',
            to_currency    TEXT DEFAULT '',
            amount_eur     REAL DEFAULT 0,
            fee_percent    REAL DEFAULT 0,
            fee_eur        REAL DEFAULT 0,
            payout_eur     REAL DEFAULT 0,
            crypto_amount  REAL DEFAULT 0,
            crypto_currency TEXT DEFAULT '',
            crypto_address TEXT DEFAULT '',
            paypal_email   TEXT DEFAULT '',
            iban           TEXT DEFAULT '',
            bank_holder    TEXT DEFAULT '',
            status         TEXT DEFAULT 'pending',
            created_at     REAL DEFAULT 0,
            updated_at     REAL DEFAULT 0,
            tx_hash        TEXT DEFAULT '',
            notes          TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id      INTEGER PRIMARY KEY,
            username     TEXT DEFAULT '',
            first_name   TEXT DEFAULT '',
            language     TEXT DEFAULT 'de',
            total_orders INTEGER DEFAULT 0,
            total_volume REAL DEFAULT 0,
            created_at   REAL DEFAULT 0,
            blocked      INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def save_order(order: Order) -> None:
    conn = _get_db()
    order.updated_at = time.time()
    conn.execute(
        """INSERT OR REPLACE INTO orders
           (order_id, user_id, username, exchange_type, from_currency,
            to_currency, amount_eur, fee_percent, fee_eur, payout_eur,
            crypto_amount, crypto_currency, crypto_address, paypal_email,
            iban, bank_holder, status, created_at, updated_at, tx_hash, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            order.order_id,
            order.user_id,
            order.username,
            order.exchange_type,
            order.from_currency,
            order.to_currency,
            order.amount_eur,
            order.fee_percent,
            order.fee_eur,
            order.payout_eur,
            order.crypto_amount,
            order.crypto_currency,
            order.crypto_address,
            order.paypal_email,
            order.iban,
            order.bank_holder,
            order.status.value,
            order.created_at,
            order.updated_at,
            order.tx_hash,
            order.notes,
        ),
    )
    conn.commit()
    conn.close()


def get_order(order_id: str) -> Optional[Order]:
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM orders WHERE order_id = ?", (order_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_order(row)


def get_user_orders(user_id: int, limit: int = 10) -> list[Order]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [_row_to_order(r) for r in rows]


def get_orders_by_status(status: OrderStatus) -> list[Order]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC",
        (status.value,),
    ).fetchall()
    conn.close()
    return [_row_to_order(r) for r in rows]


def get_all_orders(limit: int = 50) -> list[Order]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [_row_to_order(r) for r in rows]


def update_order_status(order_id: str, status: OrderStatus) -> None:
    conn = _get_db()
    conn.execute(
        "UPDATE orders SET status = ?, updated_at = ? WHERE order_id = ?",
        (status.value, time.time(), order_id),
    )
    conn.commit()
    conn.close()


def _row_to_order(row: sqlite3.Row) -> Order:
    return Order(
        order_id=row["order_id"],
        user_id=row["user_id"],
        username=row["username"],
        exchange_type=row["exchange_type"],
        from_currency=row["from_currency"],
        to_currency=row["to_currency"],
        amount_eur=row["amount_eur"],
        fee_percent=row["fee_percent"],
        fee_eur=row["fee_eur"],
        payout_eur=row["payout_eur"],
        crypto_amount=row["crypto_amount"],
        crypto_currency=row["crypto_currency"],
        crypto_address=row["crypto_address"],
        paypal_email=row["paypal_email"],
        iban=row["iban"],
        bank_holder=row["bank_holder"],
        status=OrderStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        tx_hash=row["tx_hash"],
        notes=row["notes"],
    )


# ── User helpers ─────────────────────────────────────────────────────────────

def upsert_user(user_id: int, username: str, first_name: str) -> None:
    conn = _get_db()
    conn.execute(
        """INSERT INTO users (user_id, username, first_name, created_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET username=?, first_name=?""",
        (user_id, username, first_name, time.time(), username, first_name),
    )
    conn.commit()
    conn.close()


def is_user_blocked(user_id: int) -> bool:
    conn = _get_db()
    row = conn.execute(
        "SELECT blocked FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return bool(row and row["blocked"])


def set_user_blocked(user_id: int, blocked: bool) -> None:
    conn = _get_db()
    conn.execute(
        "UPDATE users SET blocked = ? WHERE user_id = ?",
        (1 if blocked else 0, user_id),
    )
    conn.commit()
    conn.close()


def get_stats() -> dict:
    conn = _get_db()
    total = conn.execute("SELECT COUNT(*) as c FROM orders").fetchone()["c"]
    completed = conn.execute(
        "SELECT COUNT(*) as c FROM orders WHERE status = 'completed'"
    ).fetchone()["c"]
    volume = conn.execute(
        "SELECT COALESCE(SUM(amount_eur), 0) as v FROM orders WHERE status = 'completed'"
    ).fetchone()["v"]
    pending = conn.execute(
        "SELECT COUNT(*) as c FROM orders WHERE status IN ('pending', 'awaiting_payment', 'payment_received', 'processing')"
    ).fetchone()["c"]
    users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    conn.close()
    return {
        "total_orders": total,
        "completed_orders": completed,
        "total_volume_eur": volume,
        "pending_orders": pending,
        "total_users": users,
    }
