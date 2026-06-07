"""User accounts + server-side chat storage for the /ai assistant.

Goals:
  - Free registration with email + password and a 6-digit email verification code.
  - Login via a server-side session token stored in an httpOnly cookie.
  - Chats and messages are persisted per user so they are available from any
    device (not just the browser's localStorage).

Storage is portable: it uses PostgreSQL when DATABASE_URL is set (same DB the
ticket app already uses, so data survives Render deploys), and falls back to a
local SQLite file otherwise. All ids are random hex strings and timestamps are
ISO-8601 text, so the exact same SQL works on both backends.

Email sending uses SMTP_* env vars. If SMTP is not configured the verification
code is returned by the API in a "dev" field so registration still works while
you set up a mail provider — see send_verification_email().
"""

import hashlib
import json
import os
import secrets
import smtplib
import sqlite3
import time
from datetime import datetime, timezone
from email.message import EmailMessage

try:
    import psycopg2
    import psycopg2.extras
    _HAS_PG = True
except Exception:  # pragma: no cover - psycopg2 always present in prod
    _HAS_PG = False

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_default_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_accounts.db")
if not os.access(os.path.dirname(_default_db), os.W_OK):
    _default_db = "/tmp/ai_accounts.db"
SQLITE_PATH = os.environ.get("AI_DB_PATH", _default_db)

_PBKDF2_ITERS = 200_000
_SESSION_TTL = 60 * 60 * 24 * 30          # 30 days
_VERIFY_TTL = 60 * 30                      # 30 minutes


def _use_pg():
    return bool(DATABASE_URL) and _HAS_PG


def _connect():
    if _use_pg():
        return psycopg2.connect(DATABASE_URL), "pg"
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn, "sqlite"


def _q(sql, kind):
    """SQL is written with '?' placeholders; Postgres needs '%s'."""
    return sql.replace("?", "%s") if kind == "pg" else sql


def _now():
    return datetime.now(timezone.utc).isoformat()


def _rows(cur, kind):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _execute(write, sql, params=()):
    """Run one statement. Returns list[dict] for reads, None for writes."""
    conn, kind = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_q(sql, kind), params)
        out = None
        if not write:
            out = _rows(cur, kind)
        else:
            conn.commit()
        cur.close()
        return out
    finally:
        conn.close()


_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS ai_users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        pw_hash TEXT NOT NULL,
        verified INTEGER NOT NULL DEFAULT 0,
        verify_code TEXT,
        verify_expires TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS ai_auth_sessions (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS ai_chats (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS ai_messages (
        id TEXT PRIMARY KEY,
        chat_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        meta TEXT,
        created_at TEXT NOT NULL
    )""",
]


def init_db():
    try:
        for stmt in _SCHEMA:
            _execute(True, stmt)
        print(f"[INFO] ai_accounts storage ready ({'postgres' if _use_pg() else 'sqlite:' + SQLITE_PATH})")
    except Exception as e:  # pragma: no cover
        print(f"[WARN] ai_accounts init failed: {e}")


# ── password hashing ────────────────────────────────────────────────────────

def _hash_pw(password, salt=None):
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt),
                             _PBKDF2_ITERS)
    return f"pbkdf2${_PBKDF2_ITERS}${salt}${dk.hex()}"


def _verify_pw(password, stored):
    try:
        _, iters, salt, _hexhash = stored.split("$", 3)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 bytes.fromhex(salt), int(iters))
        return secrets.compare_digest(f"pbkdf2${iters}${salt}${dk.hex()}", stored)
    except Exception:
        return False


# ── email ───────────────────────────────────────────────────────────────────

def smtp_configured():
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))


def send_verification_email(email, code):
    """Send the verification code. Returns True if an email was actually sent."""
    if not smtp_configured():
        print(f"[INFO] (no SMTP) verification code for {email}: {code}")
        return False
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    pw = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ["SMTP_FROM"]
    msg = EmailMessage()
    msg["Subject"] = "Dein Bestätigungscode"
    msg["From"] = sender
    msg["To"] = email
    msg.set_content(
        f"Willkommen!\n\nDein Bestätigungscode lautet: {code}\n\n"
        f"Der Code ist 30 Minuten gültig. Wenn du dich nicht registriert hast, "
        f"ignoriere diese E-Mail."
    )
    with smtplib.SMTP(host, port, timeout=20) as s:
        s.starttls()
        if user:
            s.login(user, pw)
        s.send_message(msg)
    return True


# ── users ───────────────────────────────────────────────────────────────────

def _normalize_email(email):
    return (email or "").strip().lower()


def get_user_by_email(email):
    rows = _execute(False, "SELECT * FROM ai_users WHERE email = ?",
                    (_normalize_email(email),))
    return rows[0] if rows else None


def get_user_by_id(user_id):
    rows = _execute(False, "SELECT * FROM ai_users WHERE id = ?", (user_id,))
    return rows[0] if rows else None


def register_user(email, password):
    """Create (or refresh an unverified) account and return (user_id, code).

    Raises ValueError on bad input or if a *verified* account already exists.
    """
    email = _normalize_email(email)
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ValueError("Bitte eine gültige E-Mail-Adresse angeben.")
    if not password or len(password) < 6:
        raise ValueError("Passwort muss mindestens 6 Zeichen haben.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = _iso_in(_VERIFY_TTL)
    existing = get_user_by_email(email)
    if existing:
        if int(existing.get("verified") or 0) == 1:
            raise ValueError("Diese E-Mail ist bereits registriert. Bitte einloggen.")
        # Unverified: let them retry registration (update password + new code).
        _execute(True,
                 "UPDATE ai_users SET pw_hash = ?, verify_code = ?, "
                 "verify_expires = ? WHERE id = ?",
                 (_hash_pw(password), code, expires, existing["id"]))
        return existing["id"], code
    uid = secrets.token_hex(16)
    _execute(True,
             "INSERT INTO ai_users (id, email, pw_hash, verified, verify_code, "
             "verify_expires, created_at) VALUES (?, ?, ?, 0, ?, ?, ?)",
             (uid, email, _hash_pw(password), code, expires, _now()))
    return uid, code


def verify_email(email, code):
    """Mark the account verified if the code matches and is unexpired."""
    user = get_user_by_email(email)
    if not user:
        raise ValueError("Kein Konto mit dieser E-Mail gefunden.")
    if int(user.get("verified") or 0) == 1:
        return user["id"]
    if not user.get("verify_code") or str(code).strip() != str(user["verify_code"]):
        raise ValueError("Falscher Bestätigungscode.")
    if _expired(user.get("verify_expires")):
        raise ValueError("Code abgelaufen. Bitte neu registrieren.")
    _execute(True,
             "UPDATE ai_users SET verified = 1, verify_code = NULL, "
             "verify_expires = NULL WHERE id = ?", (user["id"],))
    return user["id"]


def authenticate(email, password):
    """Return user dict on success, else None. Unverified accounts return None."""
    user = get_user_by_email(email)
    if not user or int(user.get("verified") or 0) != 1:
        return None
    if not _verify_pw(password, user["pw_hash"]):
        return None
    return user


# ── auth sessions (login cookie) ─────────────────────────────────────────────

def create_session(user_id):
    token = secrets.token_urlsafe(32)
    _execute(True,
             "INSERT INTO ai_auth_sessions (token, user_id, created_at, "
             "expires_at) VALUES (?, ?, ?, ?)",
             (token, user_id, _now(), _iso_in(_SESSION_TTL)))
    return token


def user_for_token(token):
    if not token:
        return None
    rows = _execute(False,
                    "SELECT * FROM ai_auth_sessions WHERE token = ?", (token,))
    if not rows:
        return None
    sess = rows[0]
    if _expired(sess.get("expires_at")):
        delete_session(token)
        return None
    return get_user_by_id(sess["user_id"])


def delete_session(token):
    if token:
        _execute(True, "DELETE FROM ai_auth_sessions WHERE token = ?", (token,))


# ── chats + messages ─────────────────────────────────────────────────────────

def list_chats(user_id):
    return _execute(False,
                    "SELECT id, title, created_at, updated_at FROM ai_chats "
                    "WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))


def create_chat(user_id, title="Neuer Chat"):
    cid = secrets.token_hex(12)
    now = _now()
    _execute(True,
             "INSERT INTO ai_chats (id, user_id, title, created_at, updated_at) "
             "VALUES (?, ?, ?, ?, ?)", (cid, user_id, title[:200], now, now))
    return {"id": cid, "title": title[:200], "created_at": now, "updated_at": now}


def _owns_chat(user_id, chat_id):
    rows = _execute(False,
                    "SELECT id FROM ai_chats WHERE id = ? AND user_id = ?",
                    (chat_id, user_id))
    return bool(rows)


def rename_chat(user_id, chat_id, title):
    if not _owns_chat(user_id, chat_id):
        return False
    _execute(True, "UPDATE ai_chats SET title = ?, updated_at = ? WHERE id = ?",
             (title[:200], _now(), chat_id))
    return True


def delete_chat(user_id, chat_id):
    if not _owns_chat(user_id, chat_id):
        return False
    _execute(True, "DELETE FROM ai_messages WHERE chat_id = ?", (chat_id,))
    _execute(True, "DELETE FROM ai_chats WHERE id = ?", (chat_id,))
    return True


def get_messages(user_id, chat_id):
    if not _owns_chat(user_id, chat_id):
        return None
    rows = _execute(False,
                    "SELECT id, role, content, meta, created_at FROM ai_messages "
                    "WHERE chat_id = ? ORDER BY created_at ASC", (chat_id,))
    for r in rows:
        if r.get("meta"):
            try:
                r["meta"] = json.loads(r["meta"])
            except Exception:
                r["meta"] = None
    return rows


def add_message(user_id, chat_id, role, content, meta=None):
    if not _owns_chat(user_id, chat_id):
        return None
    mid = secrets.token_hex(12)
    now = _now()
    _execute(True,
             "INSERT INTO ai_messages (id, chat_id, role, content, meta, "
             "created_at) VALUES (?, ?, ?, ?, ?, ?)",
             (mid, chat_id, role, content,
              json.dumps(meta) if meta is not None else None, now))
    _execute(True, "UPDATE ai_chats SET updated_at = ? WHERE id = ?", (now, chat_id))
    return mid


def update_message(user_id, chat_id, message_id, content, meta=None):
    if not _owns_chat(user_id, chat_id):
        return False
    _execute(True,
             "UPDATE ai_messages SET content = ?, meta = ? "
             "WHERE id = ? AND chat_id = ?",
             (content, json.dumps(meta) if meta is not None else None,
              message_id, chat_id))
    _execute(True, "UPDATE ai_chats SET updated_at = ? WHERE id = ?",
             (_now(), chat_id))
    return True


# ── small helpers ────────────────────────────────────────────────────────────

def _iso_in(seconds):
    return datetime.fromtimestamp(time.time() + seconds, timezone.utc).isoformat()


def _expired(iso_ts):
    if not iso_ts:
        return True
    try:
        return datetime.now(timezone.utc) > datetime.fromisoformat(iso_ts)
    except Exception:
        return True
