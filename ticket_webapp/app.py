"""
Web app for generating Deutsche Bahn Online-Tickets.
Supports: German Rail Pass, Eurail Global Pass, DB Sparpreis & Deutschlandticket.
FastAPI backend with HTML frontend form.
"""

import fitz  # PyMuPDF
import csv
import json
import math
import os
import random
import tempfile
import io
import time
import zipfile
import zlib
from collections import defaultdict
from datetime import datetime, timedelta

import base64
import hashlib
import uuid as _uuid
import asn1tools
import cv2
import numpy as np
import aztec_code_generator as aztec
from PIL import Image, ImageDraw, ImageFont
from fastapi import FastAPI, Form, UploadFile, File, Request, Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

try:
    import psycopg2
    import psycopg2.extras
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(APP_DIR, "assets")

# ─── PRICE TABLES ────────────────────────────────────────────────────────────
# Structure: PRODUCT_PRICES[product][days][(class, passenger_type)] = price_string
PRICES_GRP_CONSECUTIVE = {
    3: {("2", "ERWACHSENER"): "191,00\u20ac", ("2", "JUGENDLICHER"): "153,00\u20ac",
        ("1", "ERWACHSENER"): "255,00\u20ac", ("1", "JUGENDLICHER"): "204,00\u20ac"},
    4: {("2", "ERWACHSENER"): "218,00\u20ac", ("2", "JUGENDLICHER"): "174,00\u20ac",
        ("1", "ERWACHSENER"): "290,00\u20ac", ("1", "JUGENDLICHER"): "232,00\u20ac"},
    5: {("2", "ERWACHSENER"): "240,00\u20ac", ("2", "JUGENDLICHER"): "192,00\u20ac",
        ("1", "ERWACHSENER"): "320,00\u20ac", ("1", "JUGENDLICHER"): "256,00\u20ac"},
    7: {("2", "ERWACHSENER"): "279,00\u20ac", ("2", "JUGENDLICHER"): "223,00\u20ac",
        ("1", "ERWACHSENER"): "372,00\u20ac", ("1", "JUGENDLICHER"): "298,00\u20ac"},
    10: {("2", "ERWACHSENER"): "367,00\u20ac", ("2", "JUGENDLICHER"): "294,00\u20ac",
         ("1", "ERWACHSENER"): "490,00\u20ac", ("1", "JUGENDLICHER"): "392,00\u20ac"},
    15: {("2", "ERWACHSENER"): "452,00\u20ac", ("2", "JUGENDLICHER"): "362,00\u20ac",
         ("1", "ERWACHSENER"): "603,00\u20ac", ("1", "JUGENDLICHER"): "482,00\u20ac"},
}

PRICES_GRP_FLEXI = {
    3: {("2", "ERWACHSENER"): "192,00\u20ac", ("2", "JUGENDLICHER"): "154,00\u20ac",
        ("1", "ERWACHSENER"): "256,00\u20ac", ("1", "JUGENDLICHER"): "205,00\u20ac"},
    4: {("2", "ERWACHSENER"): "222,00\u20ac", ("2", "JUGENDLICHER"): "178,00\u20ac",
        ("1", "ERWACHSENER"): "296,00\u20ac", ("1", "JUGENDLICHER"): "237,00\u20ac"},
    5: {("2", "ERWACHSENER"): "246,00\u20ac", ("2", "JUGENDLICHER"): "197,00\u20ac",
        ("1", "ERWACHSENER"): "328,00\u20ac", ("1", "JUGENDLICHER"): "262,00\u20ac"},
    7: {("2", "ERWACHSENER"): "292,00\u20ac", ("2", "JUGENDLICHER"): "234,00\u20ac",
        ("1", "ERWACHSENER"): "389,00\u20ac", ("1", "JUGENDLICHER"): "311,00\u20ac"},
    10: {("2", "ERWACHSENER"): "392,00\u20ac", ("2", "JUGENDLICHER"): "314,00\u20ac",
         ("1", "ERWACHSENER"): "523,00\u20ac", ("1", "JUGENDLICHER"): "418,00\u20ac"},
    15: {("2", "ERWACHSENER"): "486,00\u20ac", ("2", "JUGENDLICHER"): "389,00\u20ac",
         ("1", "ERWACHSENER"): "648,00\u20ac", ("1", "JUGENDLICHER"): "518,00\u20ac"},
}

PRICES_EURAIL_GLOBAL = {
    4: {("2", "ERWACHSENER"): "261,00\u20ac", ("2", "JUGENDLICHER"): "209,00\u20ac",
        ("1", "ERWACHSENER"): "348,00\u20ac", ("1", "JUGENDLICHER"): "278,00\u20ac"},
    5: {("2", "ERWACHSENER"): "296,00\u20ac", ("2", "JUGENDLICHER"): "237,00\u20ac",
        ("1", "ERWACHSENER"): "395,00\u20ac", ("1", "JUGENDLICHER"): "316,00\u20ac"},
    7: {("2", "ERWACHSENER"): "349,00\u20ac", ("2", "JUGENDLICHER"): "279,00\u20ac",
        ("1", "ERWACHSENER"): "465,00\u20ac", ("1", "JUGENDLICHER"): "372,00\u20ac"},
    10: {("2", "ERWACHSENER"): "415,00\u20ac", ("2", "JUGENDLICHER"): "332,00\u20ac",
         ("1", "ERWACHSENER"): "553,00\u20ac", ("1", "JUGENDLICHER"): "442,00\u20ac"},
    15: {("2", "ERWACHSENER"): "489,00\u20ac", ("2", "JUGENDLICHER"): "391,00\u20ac",
         ("1", "ERWACHSENER"): "652,00\u20ac", ("1", "JUGENDLICHER"): "522,00\u20ac"},
    22: {("2", "ERWACHSENER"): "448,00\u20ac", ("2", "JUGENDLICHER"): "358,00\u20ac",
         ("1", "ERWACHSENER"): "597,00\u20ac", ("1", "JUGENDLICHER"): "478,00\u20ac"},
    31: {("2", "ERWACHSENER"): "560,00\u20ac", ("2", "JUGENDLICHER"): "448,00\u20ac",
         ("1", "ERWACHSENER"): "747,00\u20ac", ("1", "JUGENDLICHER"): "597,00\u20ac"},
}

ALL_PRICES = {
    "grp_consecutive": PRICES_GRP_CONSECUTIVE,
    "grp_flexi": PRICES_GRP_FLEXI,
    "eurail_global": PRICES_EURAIL_GLOBAL,
    "deutschlandticket": {1: {("2", "ERWACHSENER"): "63,00\u20ac"}},
}

# DB station codes for Sparpreis (common stations)
DB_STATIONS = {
    "Berlin Hbf": 8011160, "Hamburg Hbf": 8002549, "München Hbf": 8000261,
    "Köln Hbf": 8000207, "Frankfurt(Main)Hbf": 8000105, "Stuttgart Hbf": 8000096,
    "Düsseldorf Hbf": 8000085, "Hannover Hbf": 8000152, "Leipzig Hbf": 8010205,
    "Dresden Hbf": 8010085, "Nürnberg Hbf": 8000284, "Bremen Hbf": 8000050,
    "Dortmund Hbf": 8000080, "Essen Hbf": 8000098, "Mannheim Hbf": 8000244,
    "Karlsruhe Hbf": 8000191, "Augsburg Hbf": 8000013, "Freiburg(Brsg)Hbf": 8000107,
    "Erfurt Hbf": 8010101, "Rostock Hbf": 8010304,
}

# ─── FCB (UIC 918.9) SCHEMA ───────────────────────────────────────────────────
FCB_SCHEMA = asn1tools.compile_files(
    os.path.join(ASSETS_DIR, 'uicRailTicketData_v1.3.5.asn'), 'uper')

EURAIL_COUNTRIES = [
    65, 70, 71, 72, 73, 74, 10, 75, 76, 78, 79, 80, 81, 82, 83, 84,
    85, 86, 87, 88, 24, 25, 26, 94, 44, 51, 52, 53, 54, 55, 56, 60, 62,
]

_EURAIL_HEADER = bytes.fromhex(
    "2355543031393930313230323330302c"
    "021459a6505160b7fa0386d9c982f6d9"
    "0547a31fb62b021448fa19099165d2e3"
    "a27fb1a6818a024a4d735744"
    "00000000"
)

DB_STATIONS = {
    'Berlin Hbf': 8065969, 'Hamburg Hbf': 8001071,
    'M\u00fcnchen Hbf': 8020347, 'K\u00f6ln Hbf': 8015458,
    'K\u00f6ln Messe/Deutz': 8015561, 'Frankfurt(Main)Hbf': 8011068,
    'Stuttgart Hbf': 8029034, 'D\u00fcsseldorf Hbf': 8008094,
    'Hannover Hbf': 8013552, 'Leipzig Hbf': 8023179,
    'Dresden Hbf': 8006050, 'N\u00fcrnberg Hbf': 8022193,
    'Bremen Hbf': 8013751, 'Dortmund Hbf': 8010053,
    'Essen Hbf': 8010184, 'Mannheim Hbf': 8014008,
    'Karlsruhe Hbf': 8014228, 'Augsburg Hbf': 8002140,
    'Freiburg(Brsg)Hbf': 8014350, 'Erfurt Hbf': 8016043,
    'Rostock Hbf': 8027089,
}

# DS100 Betriebsstellenkürzel for via route generation
DB_VIA_ROUTES = {
    ('Köln Messe/Deutz', 'Stuttgart Hbf'): 'TROI*SIGB*LM*(FH*F*DA*MA/MZ*KA)*VAI',
    ('Köln Hbf', 'Stuttgart Hbf'): 'TROI*SIGB*LM*(FH*F*DA*MA/MZ*KA)*VAI',
    ('Köln Messe/Deutz', 'München Hbf'): 'TROI*SIGB*LM*(FH*F*DA*MA/MZ*KA)*TS*ULM',
    ('Köln Hbf', 'München Hbf'): 'TROI*SIGB*LM*(FH*F*DA*MA/MZ*KA)*TS*ULM',
    ('Köln Messe/Deutz', 'Frankfurt(Main)Hbf'): 'TROI*SIGB*LM*FH',
    ('Köln Hbf', 'Frankfurt(Main)Hbf'): 'TROI*SIGB*LM*FH',
    ('Köln Messe/Deutz', 'Berlin Hbf'): 'EDG*EE*EDO*HM*H*BS*WOB*BSPD',
    ('Köln Hbf', 'Berlin Hbf'): 'EDG*EE*EDO*HM*H*BS*WOB*BSPD',
    ('Frankfurt(Main)Hbf', 'Berlin Hbf'): 'FD*KS*G*H*BS*WOB*BSPD',
    ('Frankfurt(Main)Hbf', 'München Hbf'): 'DA*MA*TS*(ULM/AA)',
    ('Frankfurt(Main)Hbf', 'Stuttgart Hbf'): 'DA*MA*KA*VAI',
    ('Frankfurt(Main)Hbf', 'Hamburg Hbf'): 'FD*KS*G*H*UEZ',
    ('Frankfurt(Main)Hbf', 'Köln Hbf'): 'FH*LM*SIGB*TROI',
    ('Frankfurt(Main)Hbf', 'Köln Messe/Deutz'): 'FH*LM*SIGB*TROI',
    ('Berlin Hbf', 'Hamburg Hbf'): 'BSPD*WOB*UEZ',
    ('Berlin Hbf', 'München Hbf'): 'LH*ERF*NBG',
    ('Berlin Hbf', 'Frankfurt(Main)Hbf'): 'BSPD*WOB*BS*H*G*KS*FD',
    ('Berlin Hbf', 'Köln Hbf'): 'BSPD*WOB*BS*H*HM*EDO*EE*EDG',
    ('Berlin Hbf', 'Köln Messe/Deutz'): 'BSPD*WOB*BS*H*HM*EDO*EE*EDG',
    ('Berlin Hbf', 'Stuttgart Hbf'): 'LH*ERF*NBG*TS',
    ('Berlin Hbf', 'Leipzig Hbf'): 'JW*BT',
    ('Berlin Hbf', 'Dresden Hbf'): 'JW*BT*RIE',
    ('Hamburg Hbf', 'Berlin Hbf'): 'UEZ*WOB*BSPD',
    ('Hamburg Hbf', 'München Hbf'): 'H*G*FD*FF*MA*TS*ULM',
    ('Hamburg Hbf', 'Frankfurt(Main)Hbf'): 'UEZ*H*G*KS*FD',
    ('Hamburg Hbf', 'Köln Hbf'): 'BHB*OS*EDO*EE*EDG',
    ('Hamburg Hbf', 'Stuttgart Hbf'): 'H*G*KS*FD*FF*MA*KA*VAI',
    ('München Hbf', 'Berlin Hbf'): 'NBG*ERF*LH',
    ('München Hbf', 'Hamburg Hbf'): 'ULM*TS*MA*FF*FD*G*H*UEZ',
    ('München Hbf', 'Frankfurt(Main)Hbf'): '(AA/ULM)*TS*MA*DA',
    ('München Hbf', 'Stuttgart Hbf'): 'ULM',
    ('München Hbf', 'Köln Hbf'): 'ULM*TS*(KA*MZ/MA)*DA*F*FH*LM*SIGB*TROI',
    ('München Hbf', 'Nürnberg Hbf'): 'ING',
    ('Stuttgart Hbf', 'München Hbf'): 'ULM',
    ('Stuttgart Hbf', 'Frankfurt(Main)Hbf'): 'VAI*KA*MA*DA',
    ('Stuttgart Hbf', 'Berlin Hbf'): 'TS*NBG*ERF*LH',
    ('Stuttgart Hbf', 'Köln Hbf'): 'VAI*(KA*MA/MZ*DA*F*FH)*LM*SIGB*TROI',
    ('Stuttgart Hbf', 'Köln Messe/Deutz'): 'VAI*(KA*MA/MZ*DA*F*FH)*LM*SIGB*TROI',
    ('Stuttgart Hbf', 'Hamburg Hbf'): 'VAI*KA*MA*FF*FD*KS*G*H*UEZ',
    ('Mannheim Hbf', 'Stuttgart Hbf'): 'KA*VAI',
    ('Mannheim Hbf', 'Frankfurt(Main)Hbf'): 'DA',
    ('Mannheim Hbf', 'Berlin Hbf'): 'DA*F*FD*KS*G*H*BS*WOB*BSPD',
    ('Hannover Hbf', 'Berlin Hbf'): 'BS*WOB*BSPD',
    ('Hannover Hbf', 'Hamburg Hbf'): 'UEZ',
    ('Hannover Hbf', 'München Hbf'): 'G*FD*FF*MA*TS*ULM',
    ('Hannover Hbf', 'Frankfurt(Main)Hbf'): 'G*KS*FD',
    ('Dortmund Hbf', 'Berlin Hbf'): 'HM*H*BS*WOB*BSPD',
    ('Dortmund Hbf', 'München Hbf'): 'HM*H*G*FD*FF*MA*TS*ULM',
    ('Nürnberg Hbf', 'München Hbf'): 'ING',
    ('Nürnberg Hbf', 'Berlin Hbf'): 'ERF*LH',
    ('Leipzig Hbf', 'Berlin Hbf'): 'BT*JW',
    ('Dresden Hbf', 'Berlin Hbf'): 'RIE*BT*JW',
    ('Düsseldorf Hbf', 'Berlin Hbf'): 'EDG*EE*EDO*HM*H*BS*WOB*BSPD',
    ('Düsseldorf Hbf', 'München Hbf'): 'KD*TROI*SIGB*LM*FH*F*DA*MA*TS*ULM',
    ('Essen Hbf', 'Berlin Hbf'): 'EDO*HM*H*BS*WOB*BSPD',
    ('Karlsruhe Hbf', 'Stuttgart Hbf'): 'VAI',
    ('Karlsruhe Hbf', 'Frankfurt(Main)Hbf'): 'MA*DA',
    ('Augsburg Hbf', 'München Hbf'): '',
    ('Erfurt Hbf', 'Berlin Hbf'): 'LH',
    ('Erfurt Hbf', 'München Hbf'): 'NBG',
    ('Bremen Hbf', 'Hamburg Hbf'): '',
    ('Freiburg(Brsg)Hbf', 'Stuttgart Hbf'): 'KA*VAI',
    ('Freiburg(Brsg)Hbf', 'Frankfurt(Main)Hbf'): 'KA*MA*DA',
}


def _get_via_route(von, nach):
    """Generate automatic via route text for DB Sparpreis tickets."""
    key = (von, nach)
    if key in DB_VIA_ROUTES:
        route = DB_VIA_ROUTES[key]
        if route:
            return f"Via: <1080>{route}"
    return ""


# ─── FONTS ───────────────────────────────────────────────────────────────────
FONT_REGULAR = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_ITALIC = "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"
FONT_BOLD_ITALIC = "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf"
FONT_DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_DEJAVU_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Watermark rendering parameters
WM_TEXT_ANGLE = -6.9
WM_FONT_SIZE = 18
WM_LINE_SPACING = 30
WM_TEXT_GREY = 188

W = 595.28
H = 841.89

API_SECRET_KEY = os.environ.get(
    "API_SECRET_KEY",
    "9f098376d138c85c13cb64fb2d006ebe34a91ca6b868cd38c62d0ab9e4abb28e"
)

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "Adela987")
DASHBOARD_SESSION_SECRET = os.environ.get("DASHBOARD_SESSION_SECRET", "db-tickets-session-2024")

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_default_store_path = os.path.join(APP_DIR, "ticket_store.json")
if not os.access(os.path.dirname(_default_store_path), os.W_OK):
    _default_store_path = "/tmp/ticket_store.json"
TICKET_STORE_FILE = os.environ.get("TICKET_STORE_PATH", _default_store_path)

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 30
_rate_limit_store: dict[str, list[float]] = defaultdict(list)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_REQUEST_LOG: list[dict] = []


@app.middleware("http")
async def log_mob_requests(request, call_next):
    """Log all /mob/ requests for debugging the DB Navigator integration."""
    path = request.url.path
    if path.startswith("/mob/"):
        import logging
        body_bytes = await request.body()
        log_entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "method": request.method,
            "path": path,
            "query": str(request.url.query),
            "content_type": request.headers.get("content-type", ""),
            "accept": request.headers.get("accept", ""),
            "user_agent": request.headers.get("user-agent", ""),
            "body": body_bytes.decode("utf-8", errors="replace")[:500],
        }
        _REQUEST_LOG.append(log_entry)
        if len(_REQUEST_LOG) > 50:
            _REQUEST_LOG.pop(0)
        logging.info(f"MOB REQUEST: {log_entry['method']} {log_entry['path']} body={log_entry['body']}")
    response = await call_next(request)
    return response


@app.get("/debug/mob-requests")
async def debug_mob_requests():
    """View recent /mob/ requests for debugging."""
    return JSONResponse(_REQUEST_LOG)


@app.middleware("http")
async def check_api_key(request, call_next):
    path = request.url.path
    if path.startswith("/api/") or path == "/batch":
        api_key = request.headers.get("X-API-Key", "")
        if api_key != API_SECRET_KEY:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await call_next(request)


@app.middleware("http")
async def rate_limit(request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    _rate_limit_store[client_ip] = [
        t for t in _rate_limit_store[client_ip] if now - t < RATE_LIMIT_WINDOW
    ]
    if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_MAX:
        return JSONResponse(
            {"error": "Too many requests"},
            status_code=429,
        )
    _rate_limit_store[client_ip].append(now)
    return await call_next(request)


# Persistent ticket storage keyed by auftragsnummer
TICKET_STORE: dict[str, dict] = {}


def _init_postgres():
    if not DATABASE_URL or not HAS_POSTGRES:
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                auftragsnummer TEXT PRIMARY KEY,
                data JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[INFO] PostgreSQL table initialized")
    except Exception as e:
        print(f"[WARN] PostgreSQL init failed: {e}")


def _load_ticket_store():
    global TICKET_STORE
    if DATABASE_URL and HAS_POSTGRES:
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor(psycopg2.extras.RealDictCursor)
            cur.execute("SELECT auftragsnummer, data FROM tickets")
            for row in cur.fetchall():
                TICKET_STORE[row["auftragsnummer"]] = row["data"]
            cur.close()
            conn.close()
            print(f"[INFO] Loaded {len(TICKET_STORE)} tickets from PostgreSQL")
            return
        except Exception as e:
            print(f"[WARN] PostgreSQL load failed: {e}")
    if os.path.exists(TICKET_STORE_FILE):
        try:
            with open(TICKET_STORE_FILE, "r") as f:
                data = json.load(f)
                TICKET_STORE.update(data)
        except Exception as e:
            print(f"[WARN] Could not load ticket store: {e}")


def _save_ticket_store():
    if DATABASE_URL and HAS_POSTGRES:
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            for nr, data in TICKET_STORE.items():
                cur.execute(
                    "INSERT INTO tickets (auftragsnummer, data) VALUES (%s, %s) "
                    "ON CONFLICT (auftragsnummer) DO UPDATE SET data = %s",
                    (nr, json.dumps(data), json.dumps(data))
                )
            conn.commit()
            cur.close()
            conn.close()
            return
        except Exception as e:
            print(f"[WARN] PostgreSQL save failed: {e}")
    try:
        with open(TICKET_STORE_FILE, "w") as f:
            json.dump(TICKET_STORE, f)
    except Exception as e:
        print(f"[WARN] Could not save ticket store: {e}")


def _delete_ticket_from_store(auftragsnummer: str):
    if auftragsnummer in TICKET_STORE:
        del TICKET_STORE[auftragsnummer]
    if DATABASE_URL and HAS_POSTGRES:
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            cur.execute("DELETE FROM tickets WHERE auftragsnummer = %s", (auftragsnummer,))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"[WARN] PostgreSQL delete failed: {e}")
    _save_ticket_store()


def _make_session_token(password: str) -> str:
    return hashlib.sha256(f"{password}:{DASHBOARD_SESSION_SECRET}".encode()).hexdigest()


_init_postgres()
_load_ticket_store()


def asset(name):
    return os.path.join(ASSETS_DIR, name)


# ─── IMAGE GENERATION ────────────────────────────────────────────────────────

def generate_ticket_number_image(ticket_id, output_path):
    width, height = 1024, 291
    display_num = ticket_id[1:] if len(ticket_id) > 6 else ticket_id

    digit_styles = [
        {"size": 130, "color": 200, "font": FONT_DEJAVU, "y": 35},
        {"size": 175, "color": 155, "font": FONT_DEJAVU_BOLD, "y": 5},
        {"size": 130, "color": 200, "font": FONT_DEJAVU, "y": 35},
        {"size": 130, "color": 200, "font": FONT_DEJAVU, "y": 35},
        {"size": 195, "color": 165, "font": FONT_DEJAVU_BOLD, "y": 0},
        {"size": 130, "color": 200, "font": FONT_DEJAVU, "y": 35},
    ]
    x_centers = [136, 290, 437, 568, 720, 874]

    img = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(img)

    for i, ch in enumerate(display_num[:6]):
        style = digit_styles[i]
        font = ImageFont.truetype(style["font"], style["size"])
        bbox = font.getbbox(ch)
        char_w = bbox[2] - bbox[0]
        x = x_centers[i] - char_w // 2
        y = style["y"] - bbox[1]
        draw.text((x, y), ch, fill=style["color"], font=font)

    arr = np.array(img).astype(float)
    mid_y = 145
    main_text = arr[:mid_y, :].copy()
    reflection = np.flip(main_text, axis=0)
    fade_len = min(reflection.shape[0], height - mid_y)
    fade = np.linspace(0.6, 0.0, fade_len).reshape(-1, 1)

    for row_idx in range(fade_len):
        target_y = mid_y + row_idx
        if target_y >= height:
            break
        alpha = fade[row_idx, 0]
        arr[target_y, :] = 255.0 + (reflection[row_idx, :] - 255.0) * alpha

    result = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
    result.save(output_path, "JPEG", quality=95)


def _render_text_layer(width, height, repeat_str, repeats=8):
    font = ImageFont.truetype(FONT_DEJAVU, WM_FONT_SIZE)
    diag = int(math.sqrt(width**2 + height**2))
    layer = Image.new("L", (diag * 2, diag * 2), 255)
    d = ImageDraw.Draw(layer)
    y = -diag
    while y < diag * 2:
        d.text((-diag, y), repeat_str * repeats, fill=WM_TEXT_GREY, font=font)
        y += WM_LINE_SPACING
    layer = layer.rotate(-WM_TEXT_ANGLE, expand=False, center=(diag, diag))
    cx, cy = diag, diag
    return np.array(layer.crop((cx - width // 2, cy - height // 2,
                                cx + width // 2, cy + height // 2)))


def generate_watermark_main(cfg, output_path):
    width, height = 1024, 702
    wm_label = cfg.get('product_label', 'GERMAN RAIL PASS').upper()
    repeat = (f"{cfg['name']} / {cfg['birth']} / "
              f"{wm_label} / {cfg['klasse']} / {cfg['ticket_id']} / ")
    wavy = cv2.imread(asset("wavy_main.png"), cv2.IMREAD_GRAYSCALE)
    text = _render_text_layer(width, height, repeat)
    result = np.minimum(wavy, text)
    cv2.imwrite(output_path, result, [cv2.IMWRITE_JPEG_QUALITY, 95])


def generate_watermark_bottom(cfg, output_path):
    width, height = 1024, 232
    wm_label = cfg.get('product_label', 'GERMAN RAIL PASS').upper()
    repeat = (f"{cfg['name']} / {cfg['birth']} / "
              f"{wm_label} / {cfg['klasse']} / {cfg['ticket_id']} / "
              f"{cfg['name']}[passengers] / ")
    wavy_color = cv2.imread(asset("wavy_bottom.png"))
    wavy_grey = cv2.cvtColor(wavy_color, cv2.COLOR_BGR2GRAY)
    b = wavy_color[:, :, 0].astype(int)
    r = wavy_color[:, :, 2].astype(int)
    blue_mask = (b - r) > 15
    text = _render_text_layer(width, height, repeat, repeats=6)
    result_grey = np.minimum(wavy_grey, text)
    result_color = cv2.cvtColor(result_grey, cv2.COLOR_GRAY2BGR)
    result_color[blue_mask] = wavy_color[blue_mask]
    cv2.imwrite(output_path, result_color, [cv2.IMWRITE_JPEG_QUALITY, 95])


# ─── UIC 918.3 AZTEC BARCODE ─────────────────────────────────────────────────

# Dummy 64-byte raw signature (r[32] || s[32]) for #UT02 format (DB Sparpreis/DT)
_DUMMY_SIG_64 = bytes.fromhex(
    "865bf227a095803c434e70e6b9edf960"
    "e26ceba3b0cdc6b4cc9e56fb54eac0b5"
    "80d386ebc94291b3be27bafa3aefc2ba"
    "1f7da9d46584af65ede881ee64234d4b"
)

# Dummy ECDSA P-160 DER signature (46 bytes) for #UT01 format (Eurail)
_DUMMY_SIG_DER = bytes.fromhex(
    "302c"
    "021411fab59ab570d7f6031fb8fde266"
    "73826cf855610214"
    "17ba43a96b48759cb901bf04a4cbe5d7"
    "08dfcdef"
)


def _build_918_header(rics='1080', key_id='00008', fmt='UT02'):
    """Build UIC 918.3 outer header with signature."""
    if fmt == 'UT01':
        hdr = b'#UT01' + rics.encode('ascii') + key_id.encode('ascii')
        hdr += _DUMMY_SIG_DER
        hdr += b'\x00\x00\x00\x00'
    else:
        hdr = b'#UT02' + rics.encode('ascii') + key_id.encode('ascii')
        hdr += _DUMMY_SIG_64
    return hdr


def _uic_field(line, col, height, width, fmt, text):
    """Build one RCT2 layout field."""
    tb = text.encode('utf-8')
    return f"{line:02d}{col:02d}{height:02d}{width:02d}{fmt}{len(tb):04d}".encode('ascii') + tb


def _build_uic918_payload(cfg):
    """Construct the decompressed UIC 918.3 payload from ticket config."""
    parts = cfg['name'].split(' ', 1)
    first, last = parts[0], (parts[1] if len(parts) == 2 else "")

    vs, ve = cfg['validity_start'], cfg['validity_end']
    creation = vs[0:2] + vs[3:5] + vs[6:10] + "2229"
    validity_text = f"Gültig vom {vs} bis {ve}"
    price_raw = cfg['price'].replace('€', '').strip()

    fields = [
        _uic_field(0, 18, 1, 33, 2, "Fahrkarte"),
        _uic_field(0, 52, 1, 9, 0, last),
        _uic_field(0, 62, 1, 9, 0, first),
        _uic_field(1, 18, 1, 33, 1, cfg.get('product_label', 'German Rail Pass')),
        _uic_field(1, 52, 1, 2, 0, "1"),
        _uic_field(1, 55, 1, 16, 0, "Person(en)"),
        _uic_field(3, 1, 1, 4, 0, vs[6:10]),
        _uic_field(3, 52, 1, 10, 0, cfg['birth']),
        _uic_field(6, 1, 1, 5, 0, vs[:5]),
        _uic_field(6, 7, 1, 5, 0, "00.00"),
        _uic_field(6, 52, 1, 5, 0, ve[:5]),
        _uic_field(6, 58, 1, 5, 0, "23.59"),
        _uic_field(12, 1, 2, 50, 2, validity_text),
        _uic_field(13, 52, 1, 3, 0, "EUR"),
        _uic_field(13, 56, 1, 15, 0, price_raw),
        _uic_field(14, 52, 1, 19, 0, cfg['payment_method']),
    ]

    fields_blob = b"".join(fields)
    tlay_inner = b"RCT2" + f"{len(fields):04d}".encode('ascii') + fields_blob
    tlay_len = 12 + len(tlay_inner)
    tlay = b"U_TLAY01" + f"{tlay_len:04d}".encode('ascii') + tlay_inner

    head = (b"U_HEAD010053" + b"9994" +
            cfg['ticket_id'].ljust(20).encode('ascii') +
            creation.encode('ascii') + b"0DE  ")

    return head + tlay


def _build_eurail_tlay(cfg):
    """Build U_TLAY block for Eurail Global Pass (matches real Eurail barcode format)."""
    parts = cfg['name'].split(' ', 1)
    first, last = parts[0], (parts[1] if len(parts) == 2 else "")
    vs, ve = cfg['validity_start'], cfg['validity_end']
    birth = cfg['birth']
    klasse_num = "1" if cfg['klasse'] == "1" else "2"
    ptype = "YOUTH" if cfg['passenger_type'] == "JUGENDLICHER" else "ADULT"
    ref = cfg.get('eurail_ref', cfg['ticket_id'])
    passport_masked = "*****" + cfg.get('passport_tail', ref[-3:])

    fields = [
        _uic_field(0, 19, 1, 19, 0, "EURAIL"),
        _uic_field(0, 39, 1, 4, 0, "NAME"),
        _uic_field(0, 53, 1, 19, 0, f"{first[0]}. {last}"),
        _uic_field(1, 19, 1, 19, 0, ""),
        _uic_field(1, 39, 1, 9, 0, "RESIDENCE"),
        _uic_field(1, 53, 1, 19, 0, cfg.get('residence', 'Germany')),
        _uic_field(2, 2, 1, 3, 0, "CIV"),
        _uic_field(2, 6, 1, 4, 0, "9901"),
        _uic_field(2, 39, 1, 12, 0, "PASS-/ID"),
        _uic_field(2, 53, 1, 19, 0, passport_masked),
        _uic_field(3, 2, 1, 5, 0, "VALID"),
        _uic_field(3, 9, 1, 23, 0, f"{vs} - {ve}"),
        _uic_field(3, 39, 1, 13, 0, "DATE OF BIRTH"),
        _uic_field(3, 53, 1, 10, 0, birth),
        _uic_field(6, 14, 1, 26, 0, "EURAIL GLOBAL PASS"),
        _uic_field(6, 67, 1, 1, 0, klasse_num),
        _uic_field(13, 2, 1, 6, 0, ptype),
        _uic_field(13, 15, 1, 37, 0, "ONLY VALID WITH PASS/ID"),
        _uic_field(15, 38, 1, 6, 0, ref[:6]),
    ]

    fields_blob = b"".join(fields)
    tlay_inner = b"RCT2" + f"{len(fields):04d}".encode('ascii') + fields_blob
    tlay_len = 12 + len(tlay_inner)
    return b"U_TLAY01" + f"{tlay_len:04d}".encode('ascii') + tlay_inner


def _build_eurail_flex(cfg):
    """Build U_FLEX block with UIC 918.9 FCB data for Eurail Global Pass.

    Format matches real Eurail barcodes: passType=1, passDescription present,
    validUntilTime=1439, specimen=True, ageCheckRequired=False.
    """
    parts = cfg['name'].split(' ', 1)
    first, last = parts[0], (parts[1] if len(parts) == 2 else "")

    now = datetime.now()
    issuing_day = now.timetuple().tm_yday
    issuing_year = now.year
    issuing_time = now.hour * 60 + now.minute

    vs = cfg['validity_start']
    try:
        vs_dt = datetime.strptime(vs, "%d.%m.%Y")
    except ValueError:
        vs_dt = datetime(2026, 1, 1)

    birth = cfg['birth']
    try:
        birth_dt = datetime.strptime(birth, "%d.%m.%Y")
    except ValueError:
        birth_dt = datetime(2000, 1, 1)
    birth_day = birth_dt.timetuple().tm_yday
    birth_year = birth_dt.year

    days_int = int(cfg['days'])
    class_code = 'first' if cfg['klasse'] == '1' else 'second'
    ptype = 'youth' if cfg['passenger_type'] == 'JUGENDLICHER' else 'adult'

    ref_ia5 = cfg.get('eurail_ref', f"1{cfg['ticket_id']}-0001-{cfg['order_number'][:8]}")
    passport_masked = "*****" + cfg.get('passport_tail', ref_ia5[-3:])

    valid_until = days_int - 1
    activated = list(range(min(days_int, 1)))

    fcb_data = {
        'issuingDetail': {
            'securityProviderNum': 9901,
            'issuingYear': issuing_year,
            'issuingDay': issuing_day,
            'issuingTime': issuing_time,
            'issuerName': 'Eurail B.V.',
            'specimen': True,
            'securePaperTicket': False,
            'activated': True,
            'currency': 'EUR',
            'currencyFract': 2,
        },
        'travelerDetail': {
            'traveler': [{
                'firstName': first,
                'lastName': last,
                'passportId': passport_masked,
                'yearOfBirth': birth_year,
                'dayOfBirth': birth_day,
                'ticketHolder': True,
                'passengerType': ptype,
                'countryOfResidence': cfg.get('residence_code', 840),
            }]
        },
        'transportDocument': [{
            'ticket': ('pass', {
                'referenceIA5': ref_ia5[:20],
                'productOwnerNum': 9901,
                'productIdIA5': '30431000000111',
                'passType': 1,
                'passDescription': 'Eurail Global Pass ',
                'classCode': class_code,
                'validFromDay': 0,
                'validUntilDay': valid_until,
                'validUntilTime': 1439,
                'activatedDay': activated,
                'countries': EURAIL_COUNTRIES,
            })
        }],
        'controlDetail': {
            'identificationByIdCard': False,
            'identificationByPassportId': False,
            'passportValidationRequired': True,
            'onlineValidationRequired': False,
            'ageCheckRequired': False,
            'reductionCardCheckRequired': False,
            'infoText': ('Ticket is valid on a direct night train on the next '
                         'day; the day after the ticket was valid'),
        }
    }

    fcb_bytes = FCB_SCHEMA.encode('UicRailTicketData', fcb_data)
    flex_inner_len = 12 + len(fcb_bytes)
    return (b"U_FLEX13" +
            f"{flex_inner_len:04d}".encode('ascii') +
            fcb_bytes)


def _build_sparpreis_tlay(cfg):
    """Build U_TLAY block for DB Sparpreis/Super Sparpreis (RCT2 format)."""
    parts = cfg['name'].split(' ', 1)
    first, last = parts[0], (parts[1] if len(parts) == 2 else "")
    vs, ve = cfg['validity_start'], cfg['validity_end']
    price_raw = cfg['price'].replace('\u20ac', '').strip()
    von = cfg.get('station_from', 'Berlin Hbf')
    nach = cfg.get('station_to', 'M\u00fcnchen Hbf')
    fare_name = cfg.get('fare_name', 'Super Sparpreis')
    zugtyp = cfg.get('zugtyp', 'ICE')

    fields = [
        _uic_field(0, 18, 1, 33, 2, "Fahrkarte"),
        _uic_field(0, 52, 1, 9, 0, last),
        _uic_field(0, 62, 1, 9, 0, first),
        _uic_field(1, 18, 1, 33, 1, fare_name),
        _uic_field(1, 52, 1, 2, 0, "1"),
        _uic_field(1, 55, 1, 16, 0, "Person(en)"),
        _uic_field(3, 1, 1, 4, 0, vs[6:10]),
        _uic_field(3, 52, 1, 10, 0, cfg['birth']),
        _uic_field(4, 1, 1, 30, 0, f"Hin: {von}"),
        _uic_field(4, 35, 1, 30, 0, f"-> {nach}"),
        _uic_field(5, 1, 1, 30, 0, f"via: {zugtyp}"),
        _uic_field(6, 1, 1, 5, 0, vs[:5]),
        _uic_field(6, 7, 1, 5, 0, "00.00"),
        _uic_field(6, 52, 1, 5, 0, ve[:5]),
        _uic_field(6, 58, 1, 5, 0, "23.59"),
        _uic_field(12, 1, 2, 50, 2, f"G\u00fcltig am {vs}"),
        _uic_field(13, 52, 1, 3, 0, "EUR"),
        _uic_field(13, 56, 1, 15, 0, price_raw),
        _uic_field(14, 52, 1, 19, 0, cfg['payment_method']),
    ]

    fields_blob = b"".join(fields)
    tlay_inner = b"RCT2" + f"{len(fields):04d}".encode('ascii') + fields_blob
    tlay_len = 12 + len(tlay_inner)
    return b"U_TLAY01" + f"{tlay_len:04d}".encode('ascii') + tlay_inner


def _build_sparpreis_flex(cfg):
    """Build U_FLEX block with UIC 918.9 FCB openTicket for DB Sparpreis.

    Format matches real DB Online-Tickets: issuerName='DB AG', fromStationNum/
    toStationNum with UIC codes, trainLink with departure time, tariffs block.
    """
    parts = cfg['name'].split(' ', 1)
    first, last = parts[0], (parts[1] if len(parts) == 2 else "")

    now = datetime.now()
    issuing_day = now.timetuple().tm_yday
    issuing_year = now.year
    issuing_time = now.hour * 60 + now.minute

    birth = cfg['birth']
    try:
        birth_dt = datetime.strptime(birth, "%d.%m.%Y")
    except ValueError:
        birth_dt = datetime(2000, 1, 1)

    vs = cfg['validity_start']
    try:
        vs_dt = datetime.strptime(vs, "%d.%m.%Y")
    except ValueError:
        vs_dt = datetime(2026, 1, 1)

    class_code = 'first' if cfg['klasse'] == '1' else 'second'
    fare_name = cfg.get('fare_name', 'Super Sparpreis')
    ref = cfg.get('sparpreis_ref', cfg['order_number'][:8].upper())
    zugtyp = cfg.get('zugtyp', 'ICE')
    von = cfg.get('station_from', 'Berlin Hbf')
    nach = cfg.get('station_to', 'München Hbf')

    from_code = DB_STATIONS.get(von, 8011160)
    to_code = DB_STATIONS.get(nach, 8000261)

    price_raw = cfg['price'].replace('\u20ac', '').replace('.', '').replace(',', '.').strip()
    try:
        price_cents = int(float(price_raw) * 100)
    except ValueError:
        price_cents = 0

    is_summer = vs_dt.month >= 4 and vs_dt.month <= 10
    utc_offset = -8 if is_summer else -4

    vs_day_of_year = (vs_dt - datetime(issuing_year, 1, 1)).days
    valid_from_day = vs_day_of_year - issuing_day
    if valid_from_day < 0:
        valid_from_day = 0
    valid_until_day = 1

    dep_hour = cfg.get('departure_hour', 13)
    dep_min = cfg.get('departure_minute', 30)
    dep_time = int(dep_hour) * 60 + int(dep_min)

    train_id = f"{zugtyp}{cfg.get('train_number', '919')}"
    travel_day = valid_from_day

    via_text = cfg.get('via_text', '')
    if not via_text:
        via_text = _get_via_route(von, nach)

    ticketcode = cfg.get('sparpreis_ref', cfg['order_number'][:8].upper())

    open_ticket = {
        'referenceIA5': ref,
        'productIdIA5': f"{zugtyp} Fahrkarte",
        'returnIncluded': False,
        'stationCodeTable': 'stationUIC',
        'fromStationNum': from_code,
        'toStationNum': to_code,
        'fromStationNameUTF8': von,
        'toStationNameUTF8': nach,
        'validRegionDesc': via_text if via_text else f"Via: <1080>{von}*{nach}",
        'validRegion': [('trainLink', {
            'trainIA5': train_id,
            'travelDate': travel_day,
            'departureTime': dep_time,
            'departureUTCOffset': utc_offset,
        })],
        'validFromDay': valid_from_day,
        'validFromTime': 0,
        'validFromUTCOffset': utc_offset,
        'validUntilDay': valid_until_day,
        'validUntilTime': 600,
        'classCode': class_code,
        'tariffs': [{
            'numberOfPassengers': 1,
            'passengerType': 'adult',
            'restrictedToCountryOfResidence': False,
            'tariffDesc': fare_name,
        }],
    }

    fcb_data = {
        'issuingDetail': {
            'securityProviderNum': 1080,
            'issuerNum': 1080,
            'issuingYear': issuing_year,
            'issuingDay': issuing_day,
            'issuingTime': issuing_time,
            'issuerName': 'DB AG',
            'specimen': False,
            'securePaperTicket': False,
            'activated': True,
            'currency': 'EUR',
            'currencyFract': 2,
            'issuerPNR': ticketcode,
        },
        'travelerDetail': {
            'traveler': [{
                'firstName': first,
                'lastName': last,
                'ticketHolder': True,
            }]
        },
        'transportDocument': [{
            'ticket': ('openTicket', open_ticket)
        }],
    }

    fcb_bytes = FCB_SCHEMA.encode('UicRailTicketData', fcb_data)
    flex_len = 12 + len(fcb_bytes)
    return (b"U_FLEX13" +
            f"{flex_len:04d}".encode('ascii') +
            fcb_bytes)


def _build_dt_tlay(cfg):
    """Build U_TLAY block for Deutschlandticket (RCT2 format)."""
    parts = cfg['name'].split(' ', 1)
    first, last = parts[0], (parts[1] if len(parts) == 2 else "")
    vs, ve = cfg['validity_start'], cfg['validity_end']
    price_raw = cfg['price'].replace('\u20ac', '').strip()

    fields = [
        _uic_field(0, 18, 1, 33, 2, "Fahrkarte"),
        _uic_field(0, 52, 1, 9, 0, last),
        _uic_field(0, 62, 1, 9, 0, first),
        _uic_field(1, 18, 1, 33, 1, "Deutschlandticket"),
        _uic_field(1, 52, 1, 2, 0, "1"),
        _uic_field(1, 55, 1, 16, 0, "Person(en)"),
        _uic_field(3, 1, 1, 4, 0, vs[6:10]),
        _uic_field(6, 1, 1, 5, 0, vs[:5]),
        _uic_field(6, 7, 1, 5, 0, "00.00"),
        _uic_field(6, 52, 1, 5, 0, ve[:5]),
        _uic_field(6, 58, 1, 5, 0, "03.00"),
        _uic_field(6, 66, 1, 5, 0, "2"),
        _uic_field(12, 1, 2, 50, 2,
                   f"G\u00fcltig vom {vs} bis {ve}"),
        _uic_field(13, 52, 1, 3, 0, "EUR"),
        _uic_field(13, 56, 1, 15, 0, price_raw),
    ]

    fields_blob = b"".join(fields)
    tlay_inner = b"RCT2" + f"{len(fields):04d}".encode('ascii') + fields_blob
    tlay_len = 12 + len(tlay_inner)
    return b"U_TLAY01" + f"{tlay_len:04d}".encode('ascii') + tlay_inner


def _build_dt_flex(cfg):
    """Build U_FLEX block for Deutschlandticket (UIC 918.9 openTicket).

    Validity: month start 0:00 to next month start 3:00.
    """
    parts = cfg['name'].split(' ', 1)
    first, last = parts[0], (parts[1] if len(parts) == 2 else "")

    now = datetime.now()
    issuing_day = now.timetuple().tm_yday
    issuing_year = now.year
    issuing_time = now.hour * 60 + now.minute

    vs = cfg['validity_start']
    try:
        vs_dt = datetime.strptime(vs, "%d.%m.%Y")
    except ValueError:
        vs_dt = datetime(2026, 1, 1)

    birth = cfg['birth']
    try:
        birth_dt = datetime.strptime(birth, "%d.%m.%Y")
    except ValueError:
        birth_dt = datetime(2000, 1, 1)

    ref = cfg.get('dt_ref', cfg['order_number'][:8].upper())

    price_raw = cfg['price'].replace('\u20ac', '').replace('.', '').replace(',', '.').strip()
    try:
        price_cents = int(float(price_raw) * 100)
    except ValueError:
        price_cents = 6300

    is_summer = vs_dt.month >= 4 and vs_dt.month <= 10
    utc_offset = -8 if is_summer else -4

    vs_abs_day = (vs_dt - datetime(issuing_year, 1, 1)).days
    valid_from_day = vs_abs_day - issuing_day
    if valid_from_day < 0:
        valid_from_day = 0
    if vs_dt.month == 12:
        next_month_dt = datetime(vs_dt.year + 1, 1, 1)
    else:
        next_month_dt = datetime(vs_dt.year, vs_dt.month + 1, 1)
    next_month_abs = (next_month_dt - datetime(issuing_year, 1, 1)).days
    valid_until_day = next_month_abs - vs_abs_day

    fcb_data = {
        'issuingDetail': {
            'securityProviderNum': 1080,
            'issuerNum': 1080,
            'issuerName': 'DB AG',
            'issuingYear': issuing_year,
            'issuingDay': issuing_day,
            'issuingTime': issuing_time,
            'specimen': False,
            'securePaperTicket': False,
            'activated': True,
            'currency': 'EUR',
            'currencyFract': 2,
        },
        'travelerDetail': {
            'traveler': [{
                'firstName': first,
                'lastName': last,
                'yearOfBirth': birth_dt.year,
                'dayOfBirth': birth_dt.timetuple().tm_yday,
                'ticketHolder': True,
            }]
        },
        'transportDocument': [{
            'ticket': ('openTicket', {
                'referenceIA5': ref,
                'productOwnerNum': 1080,
                'productIdNum': 9999,
                'productIdIA5': 'Fahrkarte',
                'returnIncluded': False,
                'validFromDay': valid_from_day,
                'validFromTime': 0,
                'validFromUTCOffset': utc_offset,
                'validUntilDay': valid_until_day,
                'validUntilTime': 180,
                'classCode': 'second',
                'price': price_cents,
                'validRegion': [('zones', {'zoneId': [1]})],
                'tariffs': [{
                    'numberOfPassengers': 1,
                    'passengerType': 'adult',
                    'restrictedToCountryOfResidence': False,
                    'tariffDesc': 'Deutschlandticket',
                }],
                'includedAddOns': [{
                    'productOwnerIA5': 'VDV6263',
                    'productIdNum': 9999,
                    'validFromDay': valid_from_day,
                    'validFromTime': 0,
                    'validFromUTCOffset': utc_offset,
                    'validUntilDay': valid_until_day,
                    'validUntilTime': 180,
                    'validRegion': [('zones', {
                        'carrierIA5': 'VDV5000',
                        'zoneId': [1],
                    })],
                }],
            })
        }],
    }

    fcb_bytes = FCB_SCHEMA.encode('UicRailTicketData', fcb_data)
    flex_inner_len = 12 + len(fcb_bytes)
    return (b"U_FLEX13" +
            f"{flex_inner_len:04d}".encode('ascii') +
            fcb_bytes)


def generate_aztec_barcode(cfg, output_path):
    """Generate a UIC 918.3 (+ 918.9 for Eurail/Sparpreis/DT) Aztec barcode image."""
    product = cfg.get('product', 'grp_consecutive')
    now = datetime.now()
    creation = f"{now.day:02d}{now.month:02d}{now.year}{now.hour:02d}{now.minute:02d}"

    if product == 'eurail_global':
        ref = cfg.get('eurail_ref',
                      f"1{cfg['ticket_id']}-0001-{cfg['order_number'][:8]}")
        head = (b"U_HEAD010053" + b"9901" +
                ref[:20].ljust(20).encode('ascii') +
                creation.encode('ascii') + b"5EN  ")
        tlay = _build_eurail_tlay(cfg)
        flex = _build_eurail_flex(cfg)
        payload = head + tlay + flex
    elif product == 'db_sparpreis':
        flex = _build_sparpreis_flex(cfg)
        payload = flex
    elif product == 'deutschlandticket':
        head = (b"U_HEAD010053" + b"1080" +
                cfg['order_number'][:20].ljust(20).encode('ascii') +
                creation.encode('ascii') + b"0DE  ")
        tlay = _build_dt_tlay(cfg)
        flex = _build_dt_flex(cfg)
        payload = head + tlay + flex
    else:
        payload = _build_uic918_payload(cfg)

    compressed = zlib.compress(payload)

    if product == 'eurail_global':
        outer_hdr = _build_918_header(rics='9901', key_id='TTEU1', fmt='UT01')
    elif product in ('db_sparpreis', 'deutschlandticket'):
        outer_hdr = _build_918_header(rics='1080', key_id='00008', fmt='UT02')
    else:
        outer_hdr = _build_918_header(rics='9994', key_id='00001', fmt='UT01')

    barcode_data = (outer_hdr +
                    f"{len(compressed):04d}".encode('ascii') +
                    compressed)

    code = aztec.AztecCode(barcode_data, ec_percent=50)
    img = code.image(module_size=6, border=1)
    img.save(output_path, "PNG")


def generate_barcode_base64(cfg) -> str:
    """Generate barcode and return as base64-encoded PNG string."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        barcode_path = tmp.name
    generate_aztec_barcode(cfg, barcode_path)
    with open(barcode_path, "rb") as f:
        barcode_bytes = f.read()
    os.unlink(barcode_path)
    return base64.b64encode(barcode_bytes).decode("ascii")


def generate_watermark_base64(cfg) -> str:
    """Generate combined watermark (ticket number + bottom) and return as base64-encoded JPEG."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ticket_num_path = os.path.join(tmpdir, "ticket_num.jpeg")
        wm_bottom_path = os.path.join(tmpdir, "wm_bottom.jpeg")
        combined_path = os.path.join(tmpdir, "watermark_combined.jpeg")

        generate_ticket_number_image(cfg['ticket_id'], ticket_num_path)
        generate_watermark_bottom(cfg, wm_bottom_path)

        num_img = cv2.imread(ticket_num_path)
        bottom_img = cv2.imread(wm_bottom_path)

        target_w = 1024
        if num_img.shape[1] != target_w:
            num_img = cv2.resize(num_img, (target_w, int(num_img.shape[0] * target_w / num_img.shape[1])))
        if bottom_img.shape[1] != target_w:
            bottom_img = cv2.resize(bottom_img, (target_w, int(bottom_img.shape[0] * target_w / bottom_img.shape[1])))

        combined = np.vstack([num_img, bottom_img])
        cv2.imwrite(combined_path, combined, [cv2.IMWRITE_JPEG_QUALITY, 92])

        with open(combined_path, "rb") as f:
            img_bytes = f.read()

    return base64.b64encode(img_bytes).decode("ascii")


# ─── PDF BUILDING ────────────────────────────────────────────────────────────

def register_fonts(page):
    page.insert_font(fontname="F0", fontfile=FONT_REGULAR)
    page.insert_font(fontname="F1", fontfile=FONT_BOLD)
    page.insert_font(fontname="F2", fontfile=FONT_ITALIC)
    page.insert_font(fontname="F3", fontfile=FONT_BOLD_ITALIC)
    page.insert_font(fontname="F4", fontfile=FONT_DEJAVU)
    page.insert_font(fontname="F5", fontfile=FONT_DEJAVU_BOLD)


def txt(page, pos, text, font="F0", size=10, color=(0, 0, 0), rotate=0):
    page.insert_text(fitz.Point(pos[0], pos[1]), text,
                     fontname=font, fontsize=size, color=color, rotate=rotate)


def _build_page1_sparpreis(doc, cfg, wm_main, wm_bottom, ticket_num_img, barcode_img):
    """Build page 1 for DB Sparpreis matching real DB Online-Ticket layout 1:1."""
    page = doc.new_page(width=W, height=H)
    register_fonts(page)

    von = cfg.get('station_from', 'Berlin Hbf')
    nach = cfg.get('station_to', 'M\u00fcnchen Hbf')
    zugtyp = cfg.get('zugtyp', 'ICE')
    fare = cfg.get('fare_name', 'Super Sparpreis')
    vs, ve = cfg['validity_start'], cfg['validity_end']
    price = cfg['price']
    dep_hour = cfg.get('departure_hour', 13)
    dep_min = cfg.get('departure_minute', 30)
    train_num = cfg.get('train_number', '919')
    dep_gleis = cfg.get('departure_track', '11')
    arr_gleis = cfg.get('arrival_track', '15')
    arr_hour = int(dep_hour) + 2
    arr_min = int(dep_min) + 3
    if arr_min >= 60:
        arr_min -= 60
        arr_hour += 1

    page.insert_image(fitz.Rect(36.85, 45.36, 82.20, 76.54),
                      filename=asset("img_xref14.jpeg"))
    txt(page, (43.9, 68.7), "CIV 1080", font="F1", size=6.9)
    txt(page, (244.9, 61.2), "Online-Ticket", font="F1", size=17.3)

    page.draw_rect(fitz.Rect(381.0, 35.4, 551.6, 206.0),
                   color=(0, 0, 0), width=0.283)
    page.insert_image(fitz.Rect(395.4, 49.8, 537.2, 191.6),
                      filename=barcode_img)
    txt(page, (366.5, 164.2), "Barcode bitte nicht knicken!",
        font="F2", size=8.3, rotate=90)

    txt(page, (42.5, 86.3), f"{zugtyp} Fahrkarte", font="F1", size=10.0)

    page.draw_rect(fitz.Rect(42.5, 86.7, 354.3, 124.3),
                   color=(0, 0, 0), width=0.283)
    txt(page, (45.6, 101.3), "G\u00fcltigkeit:", font="F0", size=10.0)
    txt(page, (92.9, 101.4),
        f"{vs} 00:00 Uhr bis {ve} 10:00 Uhr",
        font="F1", size=10.0)
    txt(page, (45.6, 112.6),
        "Sie k\u00f6nnen alle Z\u00fcge nutzen, die auf Ihrer Fahrkarte angegeben sind. F\u00fcr Z\u00fcge des Nahverkehrs",
        font="F0", size=6.9)
    txt(page, (45.6, 121.0),
        "(z.B. RE, RB, S) besteht keine Zugbindung.",
        font="F0", size=6.9)

    page.draw_rect(fitz.Rect(42.5, 124.3, 354.3, 228.3),
                   color=(0, 0, 0), width=0.283)
    txt(page, (45.6, 138.9), f"{fare} (Einfache Fahrt)", font="F1", size=10.0)
    txt(page, (45.6, 153.6), "Klasse", font="F0", size=10.0)
    txt(page, (116.5, 153.7), f"{cfg['klasse']}. Klasse", font="F1", size=10.0)
    txt(page, (45.6, 165.6), "Reisender", font="F0", size=10.0)

    birth = cfg['birth']
    try:
        birth_dt = datetime.strptime(birth, "%d.%m.%Y")
        ref_dt = datetime.strptime(vs, "%d.%m.%Y")
        age = ref_dt.year - birth_dt.year - ((ref_dt.month, ref_dt.day) < (birth_dt.month, birth_dt.day))
        if age < 6:
            age_range = "0-5"
        elif age < 15:
            age_range = "6-14"
        elif age < 27:
            age_range = "15-26"
        elif age < 65:
            age_range = "27-64"
        else:
            age_range = "65+"
    except ValueError:
        age_range = "27-64"
    txt(page, (116.5, 165.7), f"1 Person ({age_range} Jahre)", font="F1", size=10.0)

    txt(page, (45.6, 177.6), "Einfache Fahrt", font="F0", size=10.0)
    txt(page, (116.5, 177.7), von, font="F1", size=10.0)
    von_w = fitz.get_text_length(von, fontname="helv", fontsize=10.0)
    arrow_x = 116.5 + von_w + 3
    shape = page.new_shape()
    shape.draw_line(fitz.Point(arrow_x, 172.0), fitz.Point(arrow_x + 8, 172.0))
    shape.draw_line(fitz.Point(arrow_x + 5, 169.5), fitz.Point(arrow_x + 8, 172.0))
    shape.draw_line(fitz.Point(arrow_x + 5, 174.5), fitz.Point(arrow_x + 8, 172.0))
    shape.finish(color=(0, 0, 0), width=0.5)
    shape.commit()
    txt(page, (arrow_x + 11, 177.7), nach, font="F1", size=10.0)

    via_text = cfg.get('via_text', '')
    if not via_text:
        via_text = _get_via_route(von, nach)
    if via_text:
        lines = []
        cur = via_text
        max_w = 354.3 - 116.5 - 5
        while cur:
            w = fitz.get_text_length(cur, fontname="helv", fontsize=10.0)
            if w <= max_w:
                lines.append(cur)
                break
            split = len(cur) - 1
            while split > 0:
                test = cur[:split]
                if fitz.get_text_length(test, fontname="helv", fontsize=10.0) <= max_w:
                    sp = test.rfind(' ')
                    if sp > 0:
                        split = sp + 1
                    break
                split -= 1
            lines.append(cur[:split])
            cur = cur[split:]
        via_y = 189.7
        for vl in lines:
            txt(page, (116.5, via_y), vl, font="F1", size=10.0)
            via_y += 12.0

    txt(page, (45.6, 213.6), "Zugbindung", font="F0", size=10.0)
    txt(page, (116.5, 213.7),
        f"{zugtyp} {train_num}, {int(dep_hour):02d}:{int(dep_min):02d} Uhr am {vs}",
        font="F1", size=10.0)

    if fare == 'Super Sparpreis':
        txt(page, (45.6, 224.9),
            "Eine Stornierung Ihrer Fahrkarte ist ausgeschlossen.",
            font="F0", size=6.9)
    elif fare == 'Sparpreis':
        txt(page, (45.6, 224.9),
            "Stornierung bis 1 Tag vor Geltungstag gegen 10,00\u20ac Geb\u00fchr m\u00f6glich.",
            font="F0", size=6.9)

    txt(page, (42.5, 242.0),
        f"Gesamtpreis {price}. Gebucht am {cfg['booking_date']} um {datetime.now().strftime('%H:%M')} Uhr.",
        font="F0", size=6.9)
    txt(page, (42.5, 250.4),
        "Dieses Dokument ist nicht vorsteuerabzugsf\u00e4hig.",
        font="F0", size=6.9)

    page.insert_image(fitz.Rect(372.8, 209.5, 545.6, 300.0),
                      filename=ticket_num_img)

    page.draw_line(fitz.Point(453.5, 255.1), fitz.Point(549.9, 255.1),
                   color=(0, 0, 0), width=0.566)
    txt(page, (501.7, 266.0), "Zangenabdruck", font="F0", size=6.9)

    txt(page, (368.5, 281.8), cfg['name'], font="F0", size=10.0)
    txt(page, (368.5, 293.8), f"Auftragsnummer: {cfg['order_number']}",
        font="F0", size=10.0)

    txt(page, (42.5, 321.5),
        f"Ihre Reiseverbindung und Reservierung - Einfache Fahrt am {vs}",
        font="F1", size=10.0)

    col_x = [42.5, 170.1, 209.8, 249.4, 283.5, 340.2, 549.9]
    for i in range(len(col_x)):
        x0, x1 = col_x[i], col_x[i + 1] if i + 1 < len(col_x) else 549.9
        page.draw_line(fitz.Point(x0, 321.9), fitz.Point(x1, 321.9),
                       color=(0, 0, 0), width=0.566)
        page.draw_line(fitz.Point(x1, 335.2), fitz.Point(x0, 335.2),
                       color=(0, 0, 0), width=0.283)

    headers = [("Halt", 42.5), ("Datum", 170.1), ("Zeit", 209.8),
               ("Gleis", 249.4), ("Produkte", 283.5),
               ("Reservierung / Hinweise", 340.2)]
    for label, x in headers:
        txt(page, (x, 334.7), label, font="F1", size=8.3)

    vs_short = vs[:6] if len(vs) >= 6 else vs[:5]
    dep_gl_str = f" Gl.{dep_gleis}" if dep_gleis else ""
    txt(page, (42.5, 347.8), f"{von}{dep_gl_str}", font="F0", size=8.3)
    txt(page, (42.5, 357.8), nach, font="F0", size=8.3)
    txt(page, (170.1, 347.8), vs_short, font="F0", size=8.3)
    txt(page, (170.1, 357.8), vs_short, font="F0", size=8.3)
    txt(page, (209.8, 347.8), f"ab {int(dep_hour):02d}:{int(dep_min):02d}", font="F0", size=8.3)
    txt(page, (209.8, 357.8), f"an {arr_hour:02d}:{arr_min:02d}", font="F0", size=8.3)
    txt(page, (249.4, 347.8), dep_gleis, font="F0", size=8.3)
    txt(page, (249.4, 357.8), arr_gleis, font="F0", size=8.3)
    txt(page, (283.5, 347.8), f"{zugtyp} {train_num}", font="F0", size=8.3)

    txt(page, (42.5, 377.9), "Wichtige Nutzungshinweise:", font="F1", size=8.3)
    cond_items = [
        "Ihre Fahrkarte ist nur g\u00fcltig mit einem amtlichen Lichtbildausweis. Dieser ist bei der Kontrolle vorzuzeigen.",
        "Bei Fahrkarten mit BahnCard-Rabatt zeigen Sie bitte zus\u00e4tzlich Ihre g\u00fcltige BahnCard vor.",
        ["Es gelten die nationalen und internationalen Bef\u00f6rderungsbedingungen der DB AG. Innerhalb von",
         "Verkehrsverb\u00fcnden und Tarifgemeinschaften gelten deren Bestimmungen. Alle Bedingungen finden Sie unter",
         "www.bahn.de/agb und www.diebefoerderer.de."],
        ["Eine Fahrkarte entspricht grunds\u00e4tzlich einem Bef\u00f6rderungsvertrag, mehrere Fahrkarten mehreren",
         "Bef\u00f6rderungsvertr\u00e4gen. Vertraglicher Bef\u00f6rderer k\u00f6nnen dabei ein oder mehrere Verkehrsunternehmen sein. F\u00fcr",
         "die Eisenbahnfahrt handelt es sich bei dieser Fahrkarte um eine Durchgangsfahrkarte gem\u00e4\u00df der Fahrgastrechte-",
         "Verordnung (EU) 2021/782 f\u00fcr den Eisenbahnverkehr. F\u00fcr eine Fahrkarte, die neben der Eisenbahnfahrt noch",
         "die Fahrt mit einem anderen Verkehrstr\u00e4ger umfasst (z.B. Schiff zu den Nordseeinseln; \u00d6PNV) gilt: Die Fahrkarte",
         "dokumentiert dann je einen gesonderten Bef\u00f6rderungsvertrag pro Richtung und pro Verkehrstr\u00e4ger. Die Haftung",
         "f\u00fcr fahrgastrechtliche Anspr\u00fcche gilt dann auch nur f\u00fcr den jeweiligen Bef\u00f6rderungsvertrag."],
        ["Bei einer zu erwartenden Versp\u00e4tung ab 20 Minuten am Zielbahnhof Ihrer Fahrkarte ist die Zugbindung Ihrer Fahrt",
         "ohne besondere Bescheinigung aufgehoben."],
        ["Kleinkindabteile, Rollstuhlpl\u00e4tze und Vorrangpl\u00e4tze f\u00fcr Personen mit eingeschr\u00e4nkter Mobilit\u00e4t sowie Pl\u00e4tze f\u00fcr",
         "Reisende mit BahnBonus Gold- oder Platinstatus sind bei Bedarf f\u00fcr diese Personengruppen freizugeben."],
    ]
    cy = 388.4
    for item in cond_items:
        if isinstance(item, str):
            txt(page, (42.9, cy), "-", font="F0", size=8.3)
            txt(page, (48.5, cy), item, font="F0", size=8.3)
            cy += 10.0
        else:
            txt(page, (42.9, cy), "-", font="F0", size=8.3)
            txt(page, (48.5, cy), item[0], font="F0", size=8.3)
            cy += 10.0
            for sub in item[1:]:
                txt(page, (48.5, cy), sub, font="F0", size=8.3)
                cy += 10.0

    cy += 5.0
    txt(page, (42.5, cy),
        "Bitte informieren Sie sich kurz vor Reisebeginn auf unserer Website oder in der App, ob kurzfristige Fahrplan\u00e4nderungen vorliegen. Wir",
        font="F0", size=8.3)
    cy += 10.0
    txt(page, (42.5, cy),
        "danken Ihnen f\u00fcr Ihre Buchung und w\u00fcnschen eine angenehme Reise.",
        font="F0", size=8.3)

    page.insert_image(fitz.Rect(178.9, 681.1, 434.0, 794.5), filename=wm_bottom)

    ticket_code = cfg.get('sparpreis_ref', cfg['order_number'][:8].upper())
    txt(page, (42.5, 807.9), f"Ticketcode: {ticket_code}", font="F0", size=8.3)
    txt(page, (515.2, 807.7), "Seite 1 / 1", font="F2", size=8.3)


def build_page1(doc, cfg, wm_main, wm_bottom, ticket_num_img, barcode_img):
    product = cfg.get('product', 'grp_consecutive')

    if product == 'db_sparpreis':
        _build_page1_sparpreis(doc, cfg, wm_main, wm_bottom, ticket_num_img, barcode_img)
        return

    page = doc.new_page(width=W, height=H)
    register_fonts(page)

    page.insert_image(fitz.Rect(36.57, 119.06, 349.80, 334.49), filename=wm_main)
    page.insert_image(fitz.Rect(38.27, 667.00, 561.83, 785.20), filename=wm_bottom)
    page.insert_image(fitz.Rect(392.31, 133.23, 534.04, 274.96),
                      filename=barcode_img)
    page.insert_image(fitz.Rect(392.31, 291.68, 534.04, 334.20),
                      filename=ticket_num_img)
    page.insert_image(fitz.Rect(36.85, 45.36, 82.20, 76.54),
                      filename=asset("img_xref14.jpeg"))

    txt(page, (231.39, 72.60), "Online-Ticket", font="F5", size=16)
    txt(page, (375.59, 114.0), "Please print out on A4 paper", font="F2", size=8)
    txt(page, (373.0, 145.0), "Please do not bend bar code!",
        font="F2", size=8, rotate=270)

    page.draw_rect(fitz.Rect(36.85, 119.06, 350.08, 213.17),
                   color=(0, 0, 0), width=0.57)
    page.draw_rect(fitz.Rect(36.85, 212.60, 350.08, 334.49),
                   color=(0, 0, 0), width=0.57)
    page.draw_line(fitz.Point(36.76, 212.80), fitz.Point(349.51, 212.80),
                   color=(0, 0, 0), width=0.48)
    page.draw_rect(fitz.Rect(376.84, 119.28, 546.97, 344.98),
                   color=(0, 0, 0), width=0.57)

    txt(page, (38.27, 115.23), "Fahrkarte", font="F1", size=11)
    txt(page, (88.40, 115.14), " CIV 1080", font="F0", size=11)
    txt(page, (39.69, 132.68), "G\u00fcltigkeit: ", font="F0", size=10)
    txt(page, (86.93, 132.76), f"{cfg['validity_start']} - {cfg['validity_end']}",
        font="F1", size=10)
    if product == 'eurail_global':
        pass_title = f"EURAIL GLOBAL PASS {cfg['days']} days"
        if int(cfg['days']) <= 15:
            pass_title += " FLEXI"
        else:
            pass_title += " CONTINUOUS"
    elif product == 'grp_flexi':
        pass_title = f"GERMAN RAIL PASS {cfg['days']} days FLEXI"
    elif product == 'deutschlandticket':
        pass_title = "Deutschlandticket"
    else:
        pass_title = f"GERMAN RAIL PASS {cfg['days']} days CONSECUTIVE"
    txt(page, (39.69, 225.17), pass_title, font="F1", size=10)

    if product == 'deutschlandticket':
        txt(page, (39.69, 239.83), "G\u00fcltig in allen Nahverkehrsz\u00fcgen in ganz Deutschland", font="F0", size=9)
        txt(page, (39.69, 252.57), f"Klasse: 2   1 Person(en)", font="F0", size=9)
    else:
        txt(page, (39.69, 239.83), f"Klasse: {cfg['klasse']}", font="F0", size=10)
        txt(page, (39.69, 254.57), f"Person(en): 1    {cfg['passenger_type']}", font="F0", size=10)

    page.draw_rect(fitz.Rect(36.60, 367.68, 349.54, 482.57),
                   color=(0, 0, 0), width=0.45)
    page.draw_line(fitz.Point(36.96, 403.46), fitz.Point(349.74, 403.46),
                   color=(0, 0, 0), width=0.57)

    txt(page, (39.69, 363.26), "Zahlungspositionen und Preis", font="F1", size=11)

    for x, label in [(133.23, "Preis"), (189.92, "MwSt (D)"),
                     (232.44, "19%"), (266.46, "MwSt (D)"), (308.98, "7%")]:
        txt(page, (x, 380.30), label, font="F1", size=8)

    price = cfg['price']
    mwst7 = cfg.get('mwst7', '0,00\u20ac')
    for x, val in [(39.69, "Fahrkarte"), (133.23, price), (189.92, "0,00\u20ac"),
                   (232.44, "0,00\u20ac"), (266.46, price),
                   (308.98, mwst7)]:
        txt(page, (x, 394.41), val, font="F0", size=8)

    txt(page, (39.69, 417.15), cfg['payment_method'], font="F1", size=8)
    txt(page, (39.69, 431.26), f"Betrag   {price}", font="F0", size=8)
    txt(page, (39.69, 441.18), f"Datum   {cfg['payment_date']}", font="F0", size=8)

    txt(page, (39.69, 460.59),
        "Ihr Konto wurde mit dem oben angegebenen Betrag belastet. Die Buchung Ihres",
        font="F0", size=8)
    txt(page, (39.69, 469.09),
        f"Online-Tickets erfolgte am {cfg['booking_date']}. DB Fernverkehr AG/DB Regio AG,",
        font="F0", size=8)
    txt(page, (39.69, 477.59),
        "Europa-Allee 78 - 84, 60486 Frankfurt am Main, Steuernummer: 29/550/00001.",
        font="F0", size=8)

    page.draw_line(fitz.Point(476.22, 417.37), fitz.Point(563.22, 417.37),
                   color=(0, 0, 0), width=1.11)
    txt(page, (507.40, 428.42), "Zangenabdruck", font="F0", size=8)

    txt(page, (362.84, 519.98), cfg['name'], font="F1", size=10)
    txt(page, (362.84, 535.20), "Passport:", font="F0", size=10)
    txt(page, (500.35, 535.20), "Not avaliable", font="F0", size=10)
    txt(page, (362.84, 547.68), "Auftragsnummer:", font="F0", size=10)
    txt(page, (486.30, 547.68), cfg['order_number'], font="F0", size=10)
    txt(page, (362.84, 560.15), "Ticket-ID:", font="F0", size=10)
    txt(page, (519.77, 560.15), cfg['ticket_id'], font="F0", size=10)

    txt(page, (36.85, 585.66), "Conditions of use:", font="F1", size=8)
    if product == 'eurail_global':
        pass_type_text = "FLEXI" if int(cfg['days']) <= 15 else "CONTINUOUS"
        conditions = [
            f"- Valid {cfg['days']} days from {cfg['validity_start']} to {cfg['validity_end']}, {cfg['klasse_ordinal']} class {cfg['passenger_type']}.",
            f"- The Eurail Global Pass ({pass_type_text}) is valid in 33 European countries.",
            "- The ticket must be printed on white A4 paper (letter).",
            "- The Eurail Global Pass is strictly personal, non-transferable and only valid in conjunction with the passenger\u2019s valid passport.",
            "- Travel with this pass is carried out according to the existing public regulations and the general and specific",
            "transportation regulations of the participating railway companies.",
            "- For detailed conditions of use and participating countries please refer to www.eurail.com",
        ]
    elif product == 'deutschlandticket':
        conditions = [
            f"- G\u00fcltig vom {cfg['validity_start']} bis {cfg['validity_end']}.",
            "- G\u00fcltig in allen Z\u00fcgen des \u00f6ffentlichen Nahverkehrs (RE, RB, S-Bahn, U-Bahn, Stra\u00dfenbahn, Bus) deutschlandweit.",
            "- Das Deutschlandticket ist personengebunden und nicht \u00fcbertragbar.",
            "- Gilt nicht im Fernverkehr (ICE, IC/EC).",
            "- Monatsabonnement - automatische Verl\u00e4ngerung zum Monatsende.",
        ]
    elif product == 'grp_flexi':
        conditions = [
            f"- {cfg['days']} freely selectable travel days within validity from {cfg['validity_start']} to {cfg['validity_end']}, {cfg['klasse_ordinal']} class {cfg['passenger_type']}.",
            "- Up to two children between 6 and 11 years of age may accompany one person for free who is holding one adult pass. Children must be in",
            "possession of CHILD passes.",
            "- The ticket must be printed on white A4 paper (letter).",
            "- The German Rail Pass (GRP) is strictly personal, non-transferable and only valid in conjunction with the passenger\u2019s valid identification card.",
            "- Travel with this GRP is carried out according to Germany\u2019s existing public regulations and Deutsche Bahn\u2019s (DB) general and specific",
            "transportation regulations which can be obtained by applying to the carrier in question.",
            "- For the validity of the GRP on trains of other carriers within Germany please refer to www.diebefoerderer.de",
        ]
    else:
        conditions = [
            f"- Valid {cfg['days']} days from {cfg['validity_start']} to {cfg['validity_end']}, {cfg['klasse_ordinal']} class {cfg['passenger_type']}.",
            "- Up to two children between 6 and 11 years of age may accompany one person for free who is holding one adult pass. Children must be in",
            "possession of CHILD passes.",
            "- The ticket must be printed on white A4 paper (letter).",
            "- The German Rail Pass (GRP) is strictly personal, non-transferable and only valid in conjunction with the passenger\u2019s valid identification card.",
            "- Travel with this GRP is carried out according to Germany\u2019s existing public regulations and Deutsche Bahn\u2019s (DB) general and specific",
            "transportation regulations which can be obtained by applying to the carrier in question.",
            "- For the validity of the GRP on trains of other carriers within Germany please refer to www.diebefoerderer.de",
        ]
    y = 594.67
    for line in conditions:
        txt(page, (36.85, y), line, font="F0", size=8)
        y += 9.07

    page.draw_rect(fitz.Rect(37.39, 665.66, 563.24, 785.79),
                   color=(0, 0, 0), width=0.48)
    txt(page, (184.25, 724.07), cfg['name'], font="F1", size=10)

    txt(page, (494.27, 808.71), f"{cfg['ticket_id']} - Seite 1/1",
        font="F2", size=8)


def _build_page2_grp(page, SZ):
    """Page 2 content for German Rail Pass (Consecutive & Flexi)."""
    page.insert_image(fitz.Rect(52.55, 170.56, 91.93, 209.82),
                      filename=asset("img_xref19.jpeg"))
    page.insert_image(fitz.Rect(44.62, 219.37, 99.86, 270.77),
                      filename=asset("img_xref20.jpeg"))
    page.insert_image(fitz.Rect(52.67, 279.30, 92.04, 318.70),
                      filename=asset("img_xref17.jpeg"))
    page.insert_image(fitz.Rect(52.55, 336.19, 91.93, 374.68),
                      filename=asset("img_xref18.jpeg"))

    grey = (0.502, 0.502, 0.502)
    for y in [214.47, 271.96, 324.71, 388.72]:
        page.draw_line(fitz.Point(108.68, y), fitz.Point(544.42, y),
                       color=grey, width=1.25)

    page.draw_line(fitz.Point(295.51, 349.20), fitz.Point(377.60, 349.20),
                   color=(0, 0, 0), width=0.60)
    page.draw_line(fitz.Point(133.20, 360.60), fitz.Point(223.60, 360.60),
                   color=(0, 0, 0), width=0.60)
    page.draw_line(fitz.Point(60.49, 513.92), fitz.Point(187.99, 513.92),
                   color=(0, 0, 0), width=0.60)

    txt(page, (70.61, 97.59),
        "Thank you for booking at www.bahn.com!", font="F5", size=SZ)
    txt(page, (70.61, 109.01),
        "Please note the following information about your online ticket:",
        font="F4", size=SZ)
    txt(page, (70.61, 136.31),
        "Please print out your online ticket on white A4 paper (letter). Make sure that images are displayed ",
        font="F4", size=SZ)
    txt(page, (70.61, 147.60),
        "when printing out your online ticket. ", font="F4", size=SZ)
    txt(page, (132.41, 175.91),
        "The German Rail Pass (GRP) is strictly personal, non-transferable and only valid ",
        font="F4", size=SZ)
    txt(page, (132.41, 187.31),
        "together with your passport.", font="F4", size=SZ)
    txt(page, (133.31, 230.11),
        "A ticket generally represents a contract of carriage. The contractual carrier in this ",
        font="F4", size=SZ)
    txt(page, (133.31, 241.51),
        "contract may be one or more transport companies. Information on passenger rights ",
        font="F4", size=SZ)
    txt(page, (133.31, 252.90),
        "can be obtained from the train manager, at sales locations and at ",
        font="F4", size=SZ)
    txt(page, (133.31, 264.30),
        "www.bahn.de/passengersrights", font="F5", size=SZ)
    txt(page, (303.19, 264.30), ".", font="F4", size=SZ)
    txt(page, (133.20, 296.61),
        "Refund or exchange is only possible up until 1 day before validity. As of 1st day of ",
        font="F4", size=SZ)
    txt(page, (133.20, 308.01),
        "validity, no exchange or refund possible.", font="F4", size=SZ)
    txt(page, (133.20, 337.91),
        "Just before you start your journey, please check any possible timetable changes. ",
        font="F4", size=SZ)
    txt(page, (133.20, 349.20),
        "Information is available online (at ", font="F4", size=SZ)
    txt(page, (295.51, 349.20), "www.bahn.com", font="F5", size=SZ)
    txt(page, (377.49, 349.20), ", or by mobile at ", font="F4", size=SZ)
    txt(page, (133.20, 360.59), "http://m.bahn.de", font="F5", size=SZ)
    txt(page, (223.71, 360.59),
        "), by calling the DB service number on +49 (0)30 2970 (costs ",
        font="F4", size=SZ)
    txt(page, (133.20, 372.02),
        "depend on provider) daily from 00:00 to 24:00, and at the DB stations.",
        font="F4", size=SZ)
    txt(page, (53.69, 411.42), "Further conditions of use:", font="F5", size=SZ)

    further = [
        (53.69, 434.21, "F4",
         "- All GRPs entitle the holder to a specific number of travel days for a continuous period. The GRP Twin   "),
        (53.69, 445.60, "F4",
         "Pass is valid for two passengers travelling together on one pass. "),
        (53.69, 457.00, "F4",
         "- The passenger may not begin the first journey before 00h00 (12:00 a.m.) on the first day of"),
        (53.69, 468.39, "F4",
         "   validity. The last journey must be completed at latest by 24h00 (12:00 p.m.) of the last day of"),
        (53.69, 479.82, "F4",
         "   validity (date and times of the official timetables). "),
        (53.69, 491.21, "F4",
         "- It is valid throughout Germany on DB trains, including Salzburg Hbf (Austria) and Basel Bad Bf   "),
        (53.69, 502.49, "F4",
         "  (Switzerland). For the validity of the GRP on trains of other carriers within Germany please refer to "),
        (53.69, 513.92, "F5", "  www.diebefoerderer.de"),
        (187.99, 513.92, "F4", "."),
        (53.69, 525.31, "F4",
         "- Your GRP entitles you to travel also on the following routes outside of Germany:"),
    ]
    for x, y, font, text in further:
        txt(page, (x, y), text, font=font, size=SZ)
    txt(page, (76.39, 533.36), "\u2022", font="F4", size=4.3)
    txt(page, (76.39, 544.75), "\u2022", font="F4", size=4.3)
    for x, y, text in [
        (93.40, 536.71, "on ICE International trains to Li\u00e8ge and Brussels,"),
        (93.40, 548.10, "on DB-\u00d6BB EuroCity trains to Kufstein, Innsbruck, Bolzano/Bozen, Trento, Verona, Bologna and "),
        (93.40, 559.50, "Venice."),
    ]:
        txt(page, (x, y), text, font="F4", size=SZ)
    for x, y, text in [
        (53.69, 570.89, "- In case of misuse the GRP holder will be charged with the maximum price of a DB domestic point-"),
        (53.69, 582.32, "  to-point ticket per journey."),
        (53.69, 593.71, "- The GRP exempts the holder from paying a surcharge on high speed trains.  "),
        (53.69, 605.11, "  Reservations are recommended. Reservations are mandatory on night trains. The GRP is not valid "),
        (53.69, 616.50, "  on Autozug and charter trains."),
        (53.69, 627.90, "- GRP holders must pay all supplements and reservation fees for overnight accommodation, "),
        (53.69, 639.29, "  registered luggage, meals and other services available on board the trains."),
    ]:
        txt(page, (x, y), text, font="F4", size=SZ)
    txt(page, (228.90, 737.31), "We wish you a pleasant journey.", font="F5", size=SZ)


def _build_page2_eurail(page, SZ):
    """Page 2 content for Eurail Global Pass."""
    grey = (0.502, 0.502, 0.502)
    for y in [160.0, 270.0, 370.0, 460.0]:
        page.draw_line(fitz.Point(53.69, y), fitz.Point(544.42, y),
                       color=grey, width=1.0)

    txt(page, (70.61, 97.59),
        "Thank you for booking your Eurail Global Pass!", font="F5", size=SZ)
    txt(page, (70.61, 109.01),
        "Please note the following information about your online ticket:",
        font="F4", size=SZ)
    txt(page, (70.61, 136.31),
        "Please print out your online ticket on white A4 paper (letter). Make sure that images are displayed ",
        font="F4", size=SZ)
    txt(page, (70.61, 147.60),
        "when printing out your online ticket. ", font="F4", size=SZ)
    txt(page, (53.69, 175.91),
        "The Eurail Global Pass is strictly personal, non-transferable and only valid together with your ",
        font="F4", size=SZ)
    txt(page, (53.69, 187.31),
        "valid passport or national ID card.", font="F4", size=SZ)
    txt(page, (53.69, 210.11),
        "A ticket generally represents a contract of carriage. The contractual carrier in this contract may be ",
        font="F4", size=SZ)
    txt(page, (53.69, 221.51),
        "one or more transport companies.", font="F4", size=SZ)
    txt(page, (53.69, 245.00),
        "Refund or exchange is only possible up until 1 day before validity. As of 1st day of validity, no ",
        font="F4", size=SZ)
    txt(page, (53.69, 256.40),
        "exchange or refund possible.", font="F4", size=SZ)

    txt(page, (53.69, 285.00), "Further conditions of use:", font="F5", size=SZ)
    conditions = [
        "- The Eurail Global Pass is valid in 33 European countries on the national railways and on selected",
        "  private railway and ferry companies.",
        "- The pass holder may not begin the first journey before 00h00 on the first day of validity.",
        "  The last journey must be completed by 23h59 of the last day of validity.",
        "- Flexi passes: Each travel day starts at 00:00 and ends at 23:59. The travel day must be recorded",
        "  on the pass before boarding the first train of the day.",
        "- Seat reservations are recommended on most high-speed and night trains. Reservation fees are not",
        "  included in the pass price.",
        "- The pass does not cover supplements for premium services, sleeping accommodations, meals,",
        "  or other optional services on board.",
        "- In case of misuse, the pass holder will be charged the full fare for the journey.",
        "- For detailed route validity and participating companies please refer to www.eurail.com",
    ]
    y = 300.0
    for line in conditions:
        txt(page, (53.69, y), line, font="F4", size=SZ)
        y += 11.4

    txt(page, (53.69, y + 20), "Participating countries:", font="F5", size=SZ)
    countries = (
        "Austria, Belgium, Bosnia-Herzegovina, Bulgaria, Croatia, Czech Republic, Denmark, Estonia, "
        "Finland, France, Germany, Great Britain, Greece, Hungary, Ireland, Italy, Latvia, Lithuania, "
        "Luxembourg, Montenegro, Netherlands, North Macedonia, Norway, Poland, Portugal, Romania, "
        "Serbia, Slovakia, Slovenia, Spain, Sweden, Switzerland, Turkey."
    )
    cy = y + 35
    while countries:
        chunk = countries[:110]
        last_space = chunk.rfind(' ')
        if last_space > 0 and len(countries) > 110:
            chunk = countries[:last_space]
            countries = countries[last_space + 1:]
        else:
            countries = ""
        txt(page, (53.69, cy), chunk, font="F4", size=SZ)
        cy += 11.4

    txt(page, (228.90, 737.31), "We wish you a pleasant journey.", font="F5", size=SZ)


def _build_page2_sparpreis(page, SZ):
    """Page 2 content for DB Sparpreis/Super Sparpreis."""
    grey = (0.502, 0.502, 0.502)
    for y in [160.0, 270.0, 370.0]:
        page.draw_line(fitz.Point(53.69, y), fitz.Point(544.42, y),
                       color=grey, width=1.0)

    txt(page, (70.61, 97.59),
        "Vielen Dank f\u00fcr Ihre Buchung auf www.bahn.de!", font="F5", size=SZ)
    txt(page, (70.61, 109.01),
        "Bitte beachten Sie die folgenden Informationen zu Ihrem Online-Ticket:",
        font="F4", size=SZ)
    txt(page, (70.61, 136.31),
        "Bitte drucken Sie Ihr Online-Ticket auf wei\u00dfem A4-Papier aus. Achten Sie darauf, dass Bilder beim ",
        font="F4", size=SZ)
    txt(page, (70.61, 147.60),
        "Drucken angezeigt werden.", font="F4", size=SZ)
    txt(page, (53.69, 175.91),
        "Das Online-Ticket ist nur in Verbindung mit einem g\u00fcltigen Ausweis (Personalausweis oder Reisepass) ",
        font="F4", size=SZ)
    txt(page, (53.69, 187.31),
        "oder einer BahnCard g\u00fcltig.", font="F4", size=SZ)
    txt(page, (53.69, 210.11),
        "Zugbindung: Ihr Ticket gilt nur f\u00fcr die gebuchte Verbindung. Z\u00fcge des Nahverkehrs (z.B. RE, RB, ",
        font="F4", size=SZ)
    txt(page, (53.69, 221.51),
        "IRE, S-Bahn) k\u00f6nnen Sie f\u00fcr die An-/Weiterreise zum/vom Fernverkehrsbahnhof nutzen.",
        font="F4", size=SZ)
    txt(page, (53.69, 245.00),
        "Super Sparpreis-Tickets sind vom Umtausch und von der Stornierung ausgeschlossen.",
        font="F4", size=SZ)
    txt(page, (53.69, 256.40),
        "Sofortstornierung: Innerhalb von 3 Stunden nach Buchung kostenlos m\u00f6glich.",
        font="F4", size=SZ)

    txt(page, (53.69, 285.00), "Weitere Hinweise:", font="F5", size=SZ)
    conditions = [
        "- Kinder bis 5 Jahre fahren immer kostenfrei.",
        "- Kinder von 6 bis 14 Jahren fahren in Begleitung einer Person ab 15 Jahre kostenfrei.",
        "  Sie m\u00fcssen aber bei der Buchung angegeben werden.",
        "- \u00c4nderungen im Fahrplan finden Sie unter www.bahn.de oder im DB Navigator.",
        "- Informationen zu Fahrg\u00e4sterechten: www.bahn.de/fahrgastrechte",
        "- DB-Servicenummer: +49 (0)30 2970 (kostenpflichtig), t\u00e4glich 00:00 - 24:00 Uhr.",
    ]
    y = 300.0
    for line in conditions:
        txt(page, (53.69, y), line, font="F4", size=SZ)
        y += 11.4

    txt(page, (228.90, 737.31), "Wir w\u00fcnschen Ihnen eine gute Reise.", font="F5", size=SZ)


def _build_page2_deutschlandticket(page, SZ):
    """Page 2 content for Deutschlandticket."""
    grey = (0.502, 0.502, 0.502)
    for y in [160.0, 270.0, 370.0]:
        page.draw_line(fitz.Point(53.69, y), fitz.Point(544.42, y),
                       color=grey, width=1.0)

    txt(page, (70.61, 97.59),
        "Ihr Deutschlandticket", font="F5", size=SZ)
    txt(page, (70.61, 109.01),
        "Bitte beachten Sie die folgenden Informationen:",
        font="F4", size=SZ)
    txt(page, (70.61, 136.31),
        "Bitte drucken Sie Ihr Ticket auf wei\u00dfem A4-Papier aus oder nutzen Sie es digital \u00fcber den ",
        font="F4", size=SZ)
    txt(page, (70.61, 147.60),
        "DB Navigator.", font="F4", size=SZ)
    txt(page, (53.69, 175.91),
        "Das Deutschlandticket ist personengebunden und nicht \u00fcbertragbar. Es ist nur in Verbindung mit ",
        font="F4", size=SZ)
    txt(page, (53.69, 187.31),
        "einem g\u00fcltigen Ausweis g\u00fcltig.", font="F4", size=SZ)

    txt(page, (53.69, 210.11),
        "G\u00fcltigkeit: Das Deutschlandticket berechtigt zur Nutzung aller Z\u00fcge des \u00f6ffentlichen Nahverkehrs ",
        font="F4", size=SZ)
    txt(page, (53.69, 221.51),
        "(RE, RB, S-Bahn, U-Bahn, Stra\u00dfenbahn, Bus) in ganz Deutschland.",
        font="F4", size=SZ)
    txt(page, (53.69, 245.00),
        "Das Ticket gilt NICHT im Fernverkehr (ICE, IC/EC, TGV, Nightjet).",
        font="F5", size=SZ)

    txt(page, (53.69, 285.00), "Weitere Hinweise:", font="F5", size=SZ)
    conditions = [
        "- Preis: 63,00 EUR pro Monat (Abonnement).",
        "- K\u00fcndigung: Monatlich k\u00fcndbar zum Monatsende.",
        "- 1. Klasse: Aufstieg mit Zuschlag je nach Verkehrsverbund m\u00f6glich.",
        "- Mitnahme: Keine kostenlose Mitnahme weiterer Personen oder Fahrr\u00e4der (je nach Verbund).",
        "- Weitere Informationen: www.deutschlandticket.de",
    ]
    y = 300.0
    for line in conditions:
        txt(page, (53.69, y), line, font="F4", size=SZ)
        y += 11.4

    txt(page, (228.90, 737.31), "Wir w\u00fcnschen Ihnen eine gute Reise.", font="F5", size=SZ)


def build_page2(doc, cfg=None):
    page = doc.new_page(width=W, height=H)
    register_fonts(page)
    SZ = 9.5
    page.insert_image(fitz.Rect(36.85, 45.36, 82.20, 76.54),
                      filename=asset("img_xref14.jpeg"))

    product = cfg.get('product', 'grp_consecutive') if cfg else 'grp_consecutive'
    if product == 'eurail_global':
        _build_page2_eurail(page, SZ)
    elif product == 'db_sparpreis':
        _build_page2_sparpreis(page, SZ)
    elif product == 'deutschlandticket':
        _build_page2_deutschlandticket(page, SZ)
    else:
        _build_page2_grp(page, SZ)


def generate_pdf(cfg):
    """Generate the complete ticket PDF and return bytes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        wm_main = os.path.join(tmpdir, "wm_main.jpeg")
        wm_bottom = os.path.join(tmpdir, "wm_bottom.jpeg")
        ticket_num = os.path.join(tmpdir, "ticket_num.jpeg")
        barcode = os.path.join(tmpdir, "barcode.png")

        generate_watermark_main(cfg, wm_main)
        generate_watermark_bottom(cfg, wm_bottom)
        generate_ticket_number_image(cfg['ticket_id'], ticket_num)
        generate_aztec_barcode(cfg, barcode)

        doc = fitz.open()
        doc.set_metadata({
            "producer": "eos.uptrade",
            "creationDate": "D:20260101120000",
        })

        build_page1(doc, cfg, wm_main, wm_bottom, ticket_num, barcode)
        build_page2(doc, cfg)

        pdf_bytes = doc.tobytes(garbage=4, deflate=True)
        doc.close()
        return pdf_bytes


# ─── ROUTES ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_FORM


def _calc_mwst7(price_str):
    """Calculate MwSt 7% from a price string like '191,00\u20ac'."""
    raw = price_str.replace('\u20ac', '').replace('.', '').replace(',', '.').strip()
    try:
        total = float(raw)
    except ValueError:
        return '0,00\u20ac'
    mwst = total * 7 / 107
    return f"{mwst:,.2f}\u20ac".replace(',', 'X').replace('.', ',').replace('X', '.')


PRODUCT_LABELS = {
    "grp_consecutive": "German Rail Pass",
    "grp_flexi": "German Rail Pass",
    "eurail_global": "Eurail Global Pass",
    "db_sparpreis": "Super Sparpreis",
    "deutschlandticket": "Deutschlandticket",
}


RESIDENCE_CODES = {
    "Germany": 276, "Austria": 40, "Belgium": 56, "Bulgaria": 100,
    "Croatia": 191, "Czech Republic": 203, "Denmark": 208, "Estonia": 233,
    "Finland": 246, "France": 250, "Great Britain": 826, "Greece": 300,
    "Hungary": 348, "Ireland": 372, "Italy": 380, "Latvia": 428,
    "Lithuania": 440, "Luxembourg": 442, "Netherlands": 528,
    "Norway": 578, "Poland": 616, "Portugal": 620, "Romania": 642,
    "Serbia": 688, "Slovakia": 703, "Slovenia": 705, "Spain": 724,
    "Sweden": 752, "Switzerland": 756, "Turkey": 792,
    "United Kingdom": 826, "United States": 840,
}


def _detect_passenger_type(birth_date_str, reference_date_str):
    """Auto-detect ERWACHSENER/JUGENDLICHER from birth date (youth = 12-27)."""
    try:
        birth = datetime.strptime(birth_date_str, "%d.%m.%Y")
        ref = datetime.strptime(reference_date_str, "%d.%m.%Y")
    except ValueError:
        return "ERWACHSENER"
    age = ref.year - birth.year - ((ref.month, ref.day) < (birth.month, birth.day))
    if 12 <= age <= 27:
        return "JUGENDLICHER"
    return "ERWACHSENER"


def _build_cfg(name, birth_date, validity_start, validity_end, ticket_id,
               order_number, klasse, days, passenger_type, price,
               payment_method, payment_date, booking_date, product,
               residence="Germany", station_from="", station_to="",
               zugtyp="ICE", fare_name="",
               departure_hour="13", departure_minute="30",
               train_number="919", via_text="",
               departure_track="", arrival_track=""):
    if not ticket_id:
        ticket_id = str(random.randint(1000000, 9999999))
    if not order_number:
        order_number = str(random.randint(1000000000000, 9999999999999))
    if not payment_date:
        payment_date = validity_start
    if not booking_date:
        booking_date = validity_start

    if product == 'deutschlandticket':
        passenger_type = "ERWACHSENER"
        klasse = "2"
        if not price or price == "0,00\u20ac":
            price = "63,00\u20ac"
    elif not passenger_type or passenger_type == "AUTO":
        passenger_type = _detect_passenger_type(birth_date, validity_start)

    if not fare_name:
        fare_name = "Super Sparpreis" if product == "db_sparpreis" else ""

    klasse_ordinal = "1st" if klasse == "1" else "2nd"
    mwst7 = _calc_mwst7(price)

    cfg = {
        "name": name,
        "birth": birth_date,
        "validity_start": validity_start,
        "validity_end": validity_end,
        "ticket_id": ticket_id,
        "order_number": order_number,
        "klasse": klasse,
        "klasse_ordinal": klasse_ordinal,
        "days": days,
        "passenger_type": passenger_type,
        "price": price,
        "mwst7": mwst7,
        "payment_method": payment_method,
        "payment_date": payment_date,
        "booking_date": booking_date,
        "product": product,
        "product_label": PRODUCT_LABELS.get(product, "German Rail Pass"),
        "residence": residence,
        "residence_code": RESIDENCE_CODES.get(residence, 276),
    }

    if product == 'db_sparpreis':
        cfg['station_from'] = station_from or 'Berlin Hbf'
        cfg['station_to'] = station_to or 'M\u00fcnchen Hbf'
        cfg['zugtyp'] = zugtyp or 'ICE'
        cfg['fare_name'] = fare_name
        cfg['departure_hour'] = int(departure_hour) if departure_hour else 13
        cfg['departure_minute'] = int(departure_minute) if departure_minute else 30
        cfg['train_number'] = train_number or '919'
        cfg['via_text'] = via_text or ''
        cfg['departure_track'] = departure_track or ''
        cfg['arrival_track'] = arrival_track or ''

    return cfg


@app.post("/generate")
async def generate(
    name: str = Form(...),
    birth_date: str = Form(...),
    validity_start: str = Form(...),
    validity_end: str = Form(...),
    ticket_id: str = Form(""),
    order_number: str = Form(""),
    klasse: str = Form("2"),
    days: str = Form("15"),
    passenger_type: str = Form("ERWACHSENER"),
    price: str = Form("452,00\u20ac"),
    payment_method: str = Form("SEPA"),
    payment_date: str = Form(""),
    booking_date: str = Form(""),
    product: str = Form("grp_consecutive"),
    residence: str = Form("Germany"),
    station_from: str = Form(""),
    station_to: str = Form(""),
    zugtyp: str = Form("ICE"),
    fare_name: str = Form(""),
    departure_hour: str = Form("13"),
    departure_minute: str = Form("30"),
    train_number: str = Form("919"),
    via_text: str = Form(""),
    departure_track: str = Form(""),
    arrival_track: str = Form(""),
):
    cfg = _build_cfg(name, birth_date, validity_start, validity_end, ticket_id,
                     order_number, klasse, days, passenger_type, price,
                     payment_method, payment_date, booking_date, product,
                     residence, station_from, station_to, zugtyp, fare_name,
                     departure_hour, departure_minute, train_number,
                     via_text, departure_track, arrival_track)

    pdf_bytes = generate_pdf(cfg)

    if "/" in name:
        parts = name.split("/", 1)
        nachname_part = parts[0].strip() if parts else name
        vorname_part = parts[1].strip() if len(parts) > 1 else ""
    else:
        words = name.strip().split()
        if len(words) >= 2:
            vorname_part = " ".join(words[:-1])
            nachname_part = words[-1]
        else:
            nachname_part = name.strip()
            vorname_part = ""

    barcode_b64 = generate_barcode_base64(cfg)
    watermark_b64 = generate_watermark_base64(cfg)

    ticket_entry = {
        "auftragsnummer": cfg["order_number"],
        "ticket_id": cfg["ticket_id"],
        "preis": cfg["price"],
        "product": product,
        "ticket_type_label": PRODUCT_LABELS.get(product, product),
        "name": name,
        "nachname": nachname_part,
        "vorname": vorname_part,
        "geburtsdatum": birth_date,
        "klasse": klasse,
        "passagier_typ": passenger_type,
        "gueltig_von": cfg["validity_start"],
        "gueltig_bis": cfg["validity_end"],
        "created_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "pdf_url": f"/download/{cfg['ticket_id']}",
        "barcode_base64": barcode_b64,
        "watermark_base64": watermark_b64,
    }
    if product in ("db_sparpreis", "deutschlandticket"):
        ticket_entry["station_from"] = cfg.get("station_from", "")
        ticket_entry["station_to"] = cfg.get("station_to", "")
        ticket_entry["zugtyp"] = cfg.get("zugtyp", "ICE")
        ticket_entry["train_number"] = cfg.get("train_number", "919")
        ticket_entry["departure_hour"] = cfg.get("departure_hour", 13)
        ticket_entry["departure_minute"] = cfg.get("departure_minute", 30)
    TICKET_STORE[cfg["order_number"]] = ticket_entry
    _save_ticket_store()

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=ticket_{cfg['ticket_id']}.pdf"
        }
    )


@app.post("/api/generate")
async def api_generate(
    nachname: str = Form(...),
    vorname: str = Form(...),
    geburtsdatum: str = Form(...),
    klasse: str = Form("2"),
    passagier_typ: str = Form("ERWACHSENER"),
    gueltig_von: str = Form(""),
    gueltig_bis: str = Form(""),
    product: str = Form("grp_consecutive"),
    tage: str = Form("15"),
    von: str = Form(""),
    nach: str = Form(""),
    zug_typ: str = Form("ICE"),
    zug_nummer: str = Form("919"),
    ticket_id: str = Form(""),
    order_number: str = Form(""),
):
    """JSON API endpoint for Android app."""
    name = f"{nachname}/{vorname}"
    days_int = int(tage) if tage.isdigit() else 15

    if not gueltig_von:
        gueltig_von = datetime.now().strftime("%d.%m.%Y")
    if not gueltig_bis:
        gueltig_bis = _calc_validity_end(gueltig_von, days_int, product)

    price_table = ALL_PRICES.get(product, {})
    price = ""
    if price_table:
        day_prices = price_table.get(days_int, {})
        if not day_prices:
            first_key = next(iter(price_table), None)
            day_prices = price_table.get(first_key, {})
        price = day_prices.get((klasse, passagier_typ), "")

    cfg = _build_cfg(
        name=name,
        birth_date=geburtsdatum,
        validity_start=gueltig_von,
        validity_end=gueltig_bis,
        ticket_id=ticket_id,
        order_number=order_number,
        klasse=klasse,
        days=str(days_int),
        passenger_type=passagier_typ,
        price=price,
        payment_method="SEPA",
        payment_date="",
        booking_date="",
        product=product,
        station_from=von,
        station_to=nach,
        zugtyp=zug_typ,
        train_number=zug_nummer,
    )

    generate_pdf(cfg)
    barcode_b64 = generate_barcode_base64(cfg)
    watermark_b64 = generate_watermark_base64(cfg)

    ticket_data = {
        "auftragsnummer": cfg["order_number"],
        "ticket_id": cfg["ticket_id"],
        "preis": cfg["price"],
        "product": product,
        "ticket_type_label": PRODUCT_LABELS.get(product, product),
        "name": name,
        "nachname": nachname,
        "vorname": vorname,
        "geburtsdatum": geburtsdatum,
        "klasse": klasse,
        "passagier_typ": passagier_typ,
        "gueltig_von": gueltig_von,
        "gueltig_bis": gueltig_bis,
        "created_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "pdf_url": f"/download/{cfg['ticket_id']}",
        "barcode_base64": barcode_b64,
        "watermark_base64": watermark_b64,
    }
    if product in ("db_sparpreis", "deutschlandticket"):
        ticket_data["station_from"] = cfg.get("station_from", "")
        ticket_data["station_to"] = cfg.get("station_to", "")
        ticket_data["zugtyp"] = cfg.get("zugtyp", "ICE")
        ticket_data["train_number"] = cfg.get("train_number", "919")
        ticket_data["departure_hour"] = cfg.get("departure_hour", 13)
        ticket_data["departure_minute"] = cfg.get("departure_minute", 30)

    TICKET_STORE[cfg["order_number"]] = ticket_data
    _save_ticket_store()

    return JSONResponse(ticket_data)


@app.get("/api/ticket/{auftragsnummer}")
async def api_ticket_lookup(auftragsnummer: str):
    """Look up a ticket by Auftragsnummer."""
    _load_ticket_store()
    ticket = TICKET_STORE.get(auftragsnummer)
    if ticket is None:
        return JSONResponse({"error": "Ticket nicht gefunden"}, status_code=404)
    return JSONResponse(ticket)


@app.get("/api/tickets")
async def api_tickets_list():
    """List all stored tickets (without barcode/watermark data for efficiency)."""
    _load_ticket_store()
    tickets = []
    for nr, t in TICKET_STORE.items():
        tickets.append({
            "auftragsnummer": t.get("auftragsnummer", nr),
            "ticket_id": t.get("ticket_id", ""),
            "name": t.get("name", ""),
            "product": t.get("product", ""),
            "ticket_type_label": t.get("ticket_type_label", ""),
            "preis": t.get("preis", ""),
            "gueltig_von": t.get("gueltig_von", ""),
            "gueltig_bis": t.get("gueltig_bis", ""),
            "created_at": t.get("created_at", ""),
        })
    return JSONResponse({"tickets": tickets, "total": len(tickets)})


@app.delete("/api/ticket/{auftragsnummer}")
async def api_ticket_delete(auftragsnummer: str):
    """Delete a ticket by Auftragsnummer."""
    _load_ticket_store()
    if auftragsnummer in TICKET_STORE:
        _delete_ticket_from_store(auftragsnummer)
        return JSONResponse({"status": "deleted"})
    return JSONResponse({"error": "Ticket nicht gefunden"}, status_code=404)


# ─── DB NAVIGATOR API ENDPOINTS ──────────────────────────────────────────────
# These endpoints speak the DB Vendo API format so the modified DB Navigator
# APK can display tickets generated by this server.


def _parse_date_to_iso(date_str: str) -> str:
    """Convert DD.MM.YYYY to ISO 8601 with timezone."""
    try:
        parts = date_str.strip().split(".")
        if len(parts) == 3:
            return f"{parts[2]}-{parts[1]}-{parts[0]}T12:00:00+02:00"
    except Exception:
        pass
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S+02:00")


def _ticket_to_vendo_booking(ticket: dict) -> dict:
    """Convert a stored ticket to DB Vendo BuchungsanfrageErgebnisModel format."""
    auftragsnummer = ticket.get("auftragsnummer", "")
    name = ticket.get("name", "")
    klasse = ticket.get("klasse", "2")
    product_label = ticket.get("ticket_type_label", ticket.get("product", "Fahrkarte"))
    gueltig_von = ticket.get("gueltig_von", "")
    gueltig_bis = ticket.get("gueltig_bis", "")
    station_from = ticket.get("station_from", "Berlin Hbf")
    station_to = ticket.get("station_to", "München Hbf")
    zugtyp = ticket.get("zugtyp", "ICE")
    train_number = ticket.get("train_number", "919")
    dep_hour = ticket.get("departure_hour", 13)
    dep_min = ticket.get("departure_minute", 30)

    kw_id = str(_uuid.uuid4())
    start_iso = _parse_date_to_iso(gueltig_von)
    end_iso = _parse_date_to_iso(gueltig_bis)

    try:
        dep_dt = datetime.strptime(gueltig_von, "%d.%m.%Y")
        dep_dt = dep_dt.replace(hour=int(dep_hour), minute=int(dep_min))
        arr_dt = dep_dt + timedelta(hours=5)
        dep_iso = dep_dt.strftime("%Y-%m-%dT%H:%M:%S+02:00")
        arr_iso = arr_dt.strftime("%Y-%m-%dT%H:%M:%S+02:00")
        dauer = int((arr_dt - dep_dt).total_seconds() // 60)
    except Exception:
        dep_iso = start_iso
        arr_iso = end_iso
        dauer = 300

    eva_from = str(DB_STATIONS.get(station_from, 8011160))
    eva_to = str(DB_STATIONS.get(station_to, 8000261))

    return {
        "auftragsbestaetigung": {
            "auftragsnummer": auftragsnummer,
            "auftragstyp": {"auftragstyp": "KAUF"},
            "reisender": name,
            "gutscheinRueckerstattungen": [],
            "fahrt": {
                "einfacheFahrt": {
                    "kundenwunschId": kw_id,
                    "verbindung": {
                        "alternative": False,
                        "reiseDauer": dauer,
                        "umstiegeAnzahl": 0,
                        "verbindungsAbschnitte": [{
                            "typ": {"typ": "FAHRT"},
                            "abschnittsDauer": dauer,
                            "abgangsDatum": dep_iso,
                            "abgangsOrt": {
                                "name": station_from,
                                "locationId": eva_from,
                                "evaNr": eva_from,
                            },
                            "ankunftsDatum": arr_iso,
                            "ankunftsOrt": {
                                "name": station_to,
                                "locationId": eva_to,
                                "evaNr": eva_to,
                            },
                            "halte": [],
                            "echtzeitNotizen": [],
                            "himNotizen": [],
                            "attributNotizen": [],
                            "reservierungsMeldungen": [],
                            "auslastungsInfos": [],
                            "zugNummer": train_number,
                            "verkehrsmittelNummer": f"{zugtyp} {train_number}",
                        }],
                        "kontext": "",
                        "schemaVersion": "1",
                        "schemaName": "default",
                        "echtzeitNotizen": [],
                        "himNotizen": [],
                        "auslastungsInfos": [],
                        "serviceDays": [],
                        "checksum": "",
                    }
                },
                "hinRueckFahrt": None,
            },
            "produkt": {
                "anzeigename": product_label,
                "klasse": {"klasse": int(klasse) if klasse.isdigit() else 2},
                "ersterGeltungszeitpunkt": start_iso,
                "kundenwunschId": kw_id,
                "emobileBcUnterdrueckt": False,
                "produktInfo": "",
                "letzterGeltungszeitpunkt": end_iso,
            },
            "lastMinuteKontingentVerwendet": False,
        },
        "multistepzahlungInfo": None,
    }


def _ticket_to_reise_index(ticket: dict, idx: int) -> tuple:
    """Convert a stored ticket to AuftragsIndexModel + ReiseIndexModel."""
    auftragsnummer = ticket.get("auftragsnummer", "")
    gueltig_von = ticket.get("gueltig_von", "")
    kw_id = str(_uuid.uuid4())
    start_iso = _parse_date_to_iso(gueltig_von)
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+02:00")

    auftrag_index = {
        "aenderungsDatum": now_iso,
        "auftragsnummer": auftragsnummer,
        "kundenwunschIds": [kw_id],
    }
    reise_index = {
        "reisekettenId": idx + 1,
        "rkUuid": str(_uuid.uuid4()),
        "aenderungsDatum": now_iso,
        "startDatum": start_iso,
        "kundenwunschId": kw_id,
    }
    return auftrag_index, reise_index


@app.post("/mob/buchungen/anonym")
async def mob_buchungen_anonym(request: Request):
    """DB Navigator: anonymous booking endpoint.
    Accepts the Vendo booking format and returns a booking confirmation
    based on stored ticket data."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    auftragsnummer = body.get("auftragsnummer", "")
    nachname = body.get("nachname", "")

    if not auftragsnummer and not nachname:
        return JSONResponse(
            {"error": "auftragsnummer und nachname erforderlich"},
            status_code=400,
            media_type="application/x.db.vendo.mob.buchung.v19+json",
        )

    _load_ticket_store()
    ticket = TICKET_STORE.get(auftragsnummer)
    if ticket is None:
        return JSONResponse(
            {"error": "Ticket nicht gefunden"},
            status_code=404,
            media_type="application/x.db.vendo.mob.buchung.v19+json",
        )

    if nachname:
        stored_nachname = ticket.get("nachname", "")
        stored_name = ticket.get("name", "")
        query = nachname.strip().lower()
        match = (
            stored_nachname.strip().lower() == query
            or stored_name.strip().lower() == query
            or query in stored_name.strip().lower()
            or query in stored_nachname.strip().lower()
        )
        if not match:
            return JSONResponse(
                {"error": "Nachname stimmt nicht überein"},
                status_code=403,
                media_type="application/x.db.vendo.mob.buchung.v19+json",
            )

    result = _ticket_to_vendo_booking(ticket)
    return JSONResponse(
        result,
        media_type="application/x.db.vendo.mob.buchung.v19+json",
    )


@app.post("/mob/buchungen")
async def mob_buchungen(request: Request):
    """DB Navigator: booking endpoint (same logic as anonym)."""
    return await mob_buchungen_anonym(request)


@app.post("/mob/buchungen/abschliessen")
async def mob_buchungen_abschliessen(request: Request):
    """DB Navigator: complete booking."""
    return await mob_buchungen_anonym(request)


@app.post("/mob/buchungen/abschliessen/anonym")
async def mob_buchungen_abschliessen_anonym(request: Request):
    """DB Navigator: complete anonymous booking."""
    return await mob_buchungen_anonym(request)


@app.get("/mob/reisenuebersicht")
async def mob_reisenuebersicht(
    kundenprofilId: str = "",
    nurAktuelleAuftraege: bool = False,
):
    """DB Navigator: trip overview ('Meine Reisen').
    Returns all stored tickets as trips."""
    _load_ticket_store()

    auftrags_indizes = []
    reise_indizes = []

    for idx, (nr, ticket) in enumerate(TICKET_STORE.items()):
        ai, ri = _ticket_to_reise_index(ticket, idx)
        auftrags_indizes.append(ai)
        reise_indizes.append(ri)

    return JSONResponse(
        {
            "auftragsIndizes": auftrags_indizes,
            "reiseIndizes": reise_indizes,
        },
        media_type="application/x.db.vendo.mob.reisenuebersicht.v7+json",
    )


@app.post("/mob/reisen")
async def mob_reisen_create(request: Request):
    """DB Navigator: create/lookup a trip."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    _load_ticket_store()
    if TICKET_STORE:
        first_ticket = next(iter(TICKET_STORE.values()))
        result = _ticket_to_vendo_booking(first_ticket)
        return JSONResponse(
            result.get("auftragsbestaetigung", {}),
            media_type="application/x.db.vendo.mob.freiereisen.v5+json",
        )
    return JSONResponse({"error": "Keine Reisen vorhanden"}, status_code=404)


@app.get("/mob/reisen/{reise_id}")
async def mob_reisen_detail(reise_id: str):
    """DB Navigator: get trip details by ID."""
    _load_ticket_store()
    for nr, ticket in TICKET_STORE.items():
        if nr == reise_id or ticket.get("ticket_id") == reise_id:
            result = _ticket_to_vendo_booking(ticket)
            return JSONResponse(
                result.get("auftragsbestaetigung", {}),
                media_type="application/x.db.vendo.mob.freiereisen.v5+json",
            )
    return JSONResponse({"error": "Reise nicht gefunden"}, status_code=404)


@app.post("/mob/reisen/{reise_id}")
async def mob_reisen_update(reise_id: str, request: Request):
    """DB Navigator: update trip."""
    return await mob_reisen_detail(reise_id)


@app.post("/mob/reisen/{reise_id}/alternativen")
async def mob_reisen_alternativen(reise_id: str, request: Request):
    """DB Navigator: get alternative connections for a trip."""
    return await mob_reisen_detail(reise_id)


def _ticket_to_manuell_geladen(ticket: dict) -> dict:
    """Convert a stored ticket to ManuellGeladenerAuftragModel format.
    This is the response format for POST /mob/auftrag/{nr}/manuellLaden,
    which is called when the user enters Auftragsnummer + Nachname."""
    auftragsnummer = ticket.get("auftragsnummer", "")
    name = ticket.get("name", "")
    nachname = ticket.get("nachname", "")
    vorname = ticket.get("vorname", "")
    klasse = ticket.get("klasse", "2")
    product_label = ticket.get("ticket_type_label", ticket.get("product", "Fahrkarte"))
    gueltig_von = ticket.get("gueltig_von", "")
    gueltig_bis = ticket.get("gueltig_bis", "")
    station_from = ticket.get("station_from", "Berlin Hbf")
    station_to = ticket.get("station_to", "München Hbf")
    zugtyp = ticket.get("zugtyp", "ICE")
    train_number = ticket.get("train_number", "919")
    barcode_b64 = ticket.get("barcode_base64", "")

    kw_id = str(_uuid.uuid4())
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+02:00")
    start_iso = _parse_date_to_iso(gueltig_von)
    end_iso = _parse_date_to_iso(gueltig_bis)

    gueltig_text = f"Gültig vom {gueltig_von} bis {gueltig_bis}"

    ticket_obj = {
        "ticket": barcode_b64,
        "mediaTyp": "BARCODE",
        "ticketSicherheit": {
            "showCounter": False,
            "logo": None,
            "anzeigeAb": start_iso,
            "anzeigeBis": end_iso,
            "overlayDaten": None,
        },
        "anzeige": {
            "fahrtberechtigungAnlagezeitpunkt": now_iso,
            "gueltigkeitAb": start_iso,
            "auftragsnummer": auftragsnummer,
            "gueltigkeitText": gueltig_text,
            "verbund": None,
        },
        "rawBarcode": {
            "typ": "MOBILE_PLUS",
            "data": barcode_b64,
        },
    }

    reise_info = {
        "angebotsname": product_label,
        "ticketStatus": "GUELTIG",
        "materialisierungsart": "MOB",
        "upgradeAuftrag": False,
        "geraetebindungStatus": None,
        "reisendenInformation": [{
            "vorname": vorname,
            "nachname": nachname,
        }],
        "fahrtrichtung": "EINFACHE_FAHRT",
        "verbindung": None,
        "reservierungen": [],
        "istVerknuepft": False,
        "teilpreis": ticket.get("preis", ""),
        "resStatus": None,
        "fahrradResStatus": None,
        "raeumlicheGueltigkeit": {
            "von": station_from,
            "nach": station_to,
        } if station_from else None,
        "ticket": ticket_obj,
        "verbundInformationen": None,
        "klasse": "_2" if klasse == "2" else "_1",
        "reiseDetails": None,
    }

    standard_infos = {
        "buchungsdatum": now_iso,
        "aenderungsDatum": now_iso,
        "auftragsnummer": auftragsnummer,
        "anonymeBuchung": True,
        "zeitlicheGueltigkeit": {
            "ersterGeltungszeitpunkt": start_iso,
            "letzterGeltungszeitpunkt": end_iso,
        },
        "kundenwunschId": kw_id,
        "status": "GUELTIG",
        "letzterGeltungszeitpunkt": end_iso,
        "privaterKundenkontobezug": False,
        "rechnungsausstellung": False,
        "identifikationsperson": {
            "anrede": "",
            "vorname": vorname,
            "nachname": nachname,
            "abweichenderReisender": False,
        },
        "statusErsatzerstattung": None,
    }

    return {
        "anonymerZugriff": {
            "accessToken": str(_uuid.uuid4()),
        },
        "auftragsbezogeneReisen": [{
            "katalog": None,
            "streckenzeitkarte": None,
            "vertrag": None,
            "reise": {
                "standardInfos": standard_infos,
                "reiseInfos": reise_info,
            },
            "reisekette": None,
            "autonomeReservierung": None,
        }],
    }


@app.post("/mob/auftrag/{auftragsnummer}/manuellLaden")
async def mob_auftrag_manuell_laden(auftragsnummer: str, request: Request):
    """DB Navigator: manually load an order by Auftragsnummer + Nachname.
    This is the endpoint called when the user enters Auftragsnummer + Nachname
    in the 'Meine Reisen' section of the app."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    nachname = body.get("nachname", "")

    _load_ticket_store()
    ticket = TICKET_STORE.get(auftragsnummer)
    if ticket is None:
        return JSONResponse(
            {"error": "Auftrag nicht gefunden"},
            status_code=404,
            media_type="application/x.db.vendo.mob.auftraege.v11+json",
        )

    if nachname:
        stored_nachname = ticket.get("nachname", "")
        stored_name = ticket.get("name", "")
        query = nachname.strip().lower()
        match = (
            stored_nachname.strip().lower() == query
            or stored_name.strip().lower() == query
            or query in stored_name.strip().lower()
            or query in stored_nachname.strip().lower()
        )
        if not match:
            return JSONResponse(
                {"error": "Nachname stimmt nicht überein"},
                status_code=403,
                media_type="application/x.db.vendo.mob.auftraege.v11+json",
            )

    result = _ticket_to_manuell_geladen(ticket)
    return JSONResponse(
        result,
        media_type="application/x.db.vendo.mob.auftraege.v11+json",
    )


@app.get("/dashboard/login", response_class=HTMLResponse)
async def dashboard_login(error: str = ""):
    """Login page for the dashboard."""
    error_html = f'<p style="color:#EC0016;margin-bottom:12px">{error}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard Login</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; display: flex; justify-content: center; align-items: center; min-height: 100vh; }}
.login-card {{ background: white; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); padding: 40px; width: 100%; max-width: 400px; }}
.login-card h1 {{ color: #EC0016; font-size: 24px; margin-bottom: 8px; }}
.login-card p.sub {{ color: #6b6b6b; font-size: 14px; margin-bottom: 24px; }}
input {{ width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; margin-bottom: 16px; }}
input:focus {{ outline: none; border-color: #EC0016; }}
button {{ width: 100%; padding: 12px; background: #EC0016; color: white; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; }}
button:hover {{ background: #c40014; }}
</style>
</head>
<body>
<div class="login-card">
    <h1>DB Tickets</h1>
    <p class="sub">Dashboard-Zugang</p>
    {error_html}
    <form method="POST" action="/dashboard/login">
        <input type="password" name="password" placeholder="Passwort" autofocus required />
        <button type="submit">Anmelden</button>
    </form>
</div>
</body>
</html>"""


@app.post("/dashboard/login")
async def dashboard_login_post(password: str = Form(...)):
    """Handle dashboard login."""
    if password == DASHBOARD_PASSWORD:
        token = _make_session_token(password)
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie(key="dashboard_session", value=token, httponly=True, max_age=86400)
        return response
    return RedirectResponse(url="/dashboard/login?error=Falsches+Passwort", status_code=303)


@app.get("/dashboard/logout")
async def dashboard_logout():
    """Logout from the dashboard."""
    response = RedirectResponse(url="/dashboard/login", status_code=303)
    response.delete_cookie(key="dashboard_session")
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Visual dashboard showing all stored tickets."""
    session = request.cookies.get("dashboard_session", "")
    if session != _make_session_token(DASHBOARD_PASSWORD):
        return RedirectResponse(url="/dashboard/login", status_code=303)
    _load_ticket_store()
    rows = ""
    for nr, t in TICKET_STORE.items():
        name = t.get("name", "")
        product = t.get("ticket_type_label", t.get("product", ""))
        preis = t.get("preis", "")
        gueltig_von = t.get("gueltig_von", "")
        gueltig_bis = t.get("gueltig_bis", "")
        created = t.get("created_at", "")
        auftrag = t.get("auftragsnummer", nr)
        rows += f"""<tr>
            <td>{auftrag}</td>
            <td>{name}</td>
            <td>{product}</td>
            <td>{preis}</td>
            <td>{gueltig_von}</td>
            <td>{gueltig_bis}</td>
            <td>{created}</td>
            <td><button class="btn-del" onclick="deleteTicket('{auftrag}')">L\u00f6schen</button></td>
        </tr>"""

    total = len(TICKET_STORE)
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DB Tickets Dashboard</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; color: #1b1b1b; }}
.header {{ background: #EC0016; color: white; padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; }}
.header h1 {{ font-size: 22px; }}
.header .badge {{ background: rgba(255,255,255,0.2); padding: 4px 12px; border-radius: 12px; font-size: 14px; }}
.container {{ max-width: 1200px; margin: 24px auto; padding: 0 16px; }}
.stats {{ display: flex; gap: 16px; margin-bottom: 24px; }}
.stat-card {{ background: white; border-radius: 12px; padding: 20px; flex: 1; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
.stat-card .number {{ font-size: 32px; font-weight: bold; color: #EC0016; }}
.stat-card .label {{ font-size: 14px; color: #6b6b6b; margin-top: 4px; }}
.card {{ background: white; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); overflow: hidden; }}
.card-header {{ padding: 16px 20px; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; align-items: center; }}
.card-header h2 {{ font-size: 18px; }}
table {{ width: 100%; border-collapse: collapse; }}
th {{ background: #f8f8f8; padding: 12px 16px; text-align: left; font-size: 13px; color: #6b6b6b; font-weight: 600; text-transform: uppercase; }}
td {{ padding: 12px 16px; border-top: 1px solid #f0f0f0; font-size: 14px; }}
tr:hover {{ background: #fafafa; }}
.btn-del {{ background: #EC0016; color: white; border: none; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }}
.btn-del:hover {{ background: #c40014; }}
.btn-backup {{ background: #1455C0; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; }}
.btn-backup:hover {{ background: #0d3d8e; }}
.empty {{ text-align: center; padding: 40px; color: #6b6b6b; }}
.nav {{ display: flex; gap: 12px; }}
.nav a {{ color: white; text-decoration: none; background: rgba(255,255,255,0.2); padding: 6px 14px; border-radius: 6px; font-size: 14px; }}
.nav a:hover {{ background: rgba(255,255,255,0.3); }}
@media (max-width: 768px) {{
  .stats {{ flex-direction: column; }}
  table {{ font-size: 12px; }}
  th, td {{ padding: 8px; }}
}}
</style>
</head>
<body>
<div class="header">
    <h1>DB Tickets Dashboard</h1>
    <div class="nav">
        <a href="/">Ticket erstellen</a>
        <a href="/dashboard">Dashboard</a>
        <a href="/dashboard/logout">Abmelden</a>
    </div>
</div>
<div class="container">
    <div class="stats">
        <div class="stat-card">
            <div class="number">{total}</div>
            <div class="label">Gespeicherte Tickets</div>
        </div>
    </div>
    <div class="card">
        <div class="card-header">
            <h2>Alle Tickets</h2>
            <button class="btn-backup" onclick="downloadBackup()">Backup herunterladen</button>
        </div>
        {'<table><thead><tr><th>Auftragsnr.</th><th>Name</th><th>Produkt</th><th>Preis</th><th>Von</th><th>Bis</th><th>Erstellt</th><th></th></tr></thead><tbody>' + rows + '</tbody></table>' if rows else '<div class="empty">Noch keine Tickets vorhanden</div>'}
    </div>
</div>
<script>
const API_KEY = '{API_SECRET_KEY}';
async function deleteTicket(nr) {{
    if (!confirm('Ticket ' + nr + ' wirklich l\\u00f6schen?')) return;
    const res = await fetch('/api/ticket/' + nr, {{
        method: 'DELETE',
        headers: {{ 'X-API-Key': API_KEY }}
    }});
    if (res.ok) location.reload();
    else alert('Fehler beim L\\u00f6schen');
}}
async function downloadBackup() {{
    const res = await fetch('/api/backup', {{
        headers: {{ 'X-API-Key': API_KEY }}
    }});
    const data = await res.json();
    const blob = new Blob([JSON.stringify(data, null, 2)], {{ type: 'application/json' }});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'tickets_backup_' + new Date().toISOString().slice(0,10) + '.json';
    a.click();
}}
</script>
</body>
</html>"""


@app.get("/api/backup")
async def api_backup():
    """Export all tickets as JSON backup."""
    backup_data = {
        "exported_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "total_tickets": len(TICKET_STORE),
        "tickets": {}
    }
    for nr, t in TICKET_STORE.items():
        backup_data["tickets"][nr] = {
            k: v for k, v in t.items()
            if k not in ("barcode_base64", "watermark_base64")
        }
    return JSONResponse(backup_data)


@app.post("/api/restore")
async def api_restore(file: UploadFile = File(...)):
    """Restore tickets from a JSON backup."""
    content = await file.read()
    try:
        data = json.loads(content.decode("utf-8"))
        tickets = data.get("tickets", {})
        restored = 0
        for nr, t in tickets.items():
            if nr not in TICKET_STORE:
                TICKET_STORE[nr] = t
                restored += 1
        _save_ticket_store()
        return JSONResponse({"status": "ok", "restored": restored})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/ticket-lookup")
async def ticket_lookup_by_name(
    auftragsnummer: str = Form(...),
    nachname: str = Form(...),
):
    """Look up a ticket by Auftragsnummer + Nachname (public, no auth needed)."""
    _load_ticket_store()
    ticket = TICKET_STORE.get(auftragsnummer)
    if ticket is None:
        return JSONResponse({"error": "Ticket nicht gefunden"}, status_code=404)
    stored_nachname = ticket.get("nachname", "")
    stored_name = ticket.get("name", "")
    query = nachname.strip().lower()
    match = (
        stored_nachname.strip().lower() == query
        or stored_name.strip().lower() == query
        or query in stored_name.strip().lower()
        or query in stored_nachname.strip().lower()
    )
    if not match:
        return JSONResponse({"error": "Nachname stimmt nicht überein"}, status_code=403)
    safe = {k: v for k, v in ticket.items() if k not in ("barcode_base64", "watermark_base64")}
    safe["barcode_base64"] = ticket.get("barcode_base64", "")
    safe["watermark_base64"] = ticket.get("watermark_base64", "")
    return JSONResponse(safe)


@app.get("/lookup", response_class=HTMLResponse)
async def lookup_page():
    """Public ticket lookup page — enter Auftragsnummer + Nachname to view ticket."""
    return LOOKUP_HTML


@app.get("/download/{ticket_id}")
async def download_ticket(ticket_id: str):
    """Serve a previously generated ticket PDF by ticket_id (re-generates)."""
    return JSONResponse({"error": "Direct download not available. Use /generate endpoint."}, status_code=404)


@app.post("/api/barcode")
async def api_barcode(
    nachname: str = Form(...),
    vorname: str = Form(...),
    geburtsdatum: str = Form(...),
    klasse: str = Form("2"),
    passagier_typ: str = Form("ERWACHSENER"),
    gueltig_von: str = Form(""),
    gueltig_bis: str = Form(""),
    product: str = Form("grp_consecutive"),
    tage: str = Form("15"),
    von: str = Form(""),
    nach: str = Form(""),
    zug_typ: str = Form("ICE"),
    zug_nummer: str = Form("919"),
    ticket_id: str = Form(""),
    order_number: str = Form(""),
):
    """Returns the Aztec barcode PNG for the given ticket data (same as in PDF)."""
    name = f"{nachname}/{vorname}"
    days_int = int(tage) if tage.isdigit() else 15

    if not gueltig_von:
        gueltig_von = datetime.now().strftime("%d.%m.%Y")
    if not gueltig_bis:
        gueltig_bis = _calc_validity_end(gueltig_von, days_int, product)

    price_table = ALL_PRICES.get(product, {})
    price = ""
    if price_table:
        day_prices = price_table.get(days_int, {})
        if not day_prices:
            first_key = next(iter(price_table), None)
            day_prices = price_table.get(first_key, {})
        price = day_prices.get((klasse, passagier_typ), "")

    cfg = _build_cfg(
        name=name,
        birth_date=geburtsdatum,
        validity_start=gueltig_von,
        validity_end=gueltig_bis,
        ticket_id=ticket_id,
        order_number=order_number,
        klasse=klasse,
        days=str(days_int),
        passenger_type=passagier_typ,
        price=price,
        payment_method="SEPA",
        payment_date="",
        booking_date="",
        product=product,
        station_from=von,
        station_to=nach,
        zugtyp=zug_typ,
        train_number=zug_nummer,
    )

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        barcode_path = tmp.name

    generate_aztec_barcode(cfg, barcode_path)

    with open(barcode_path, "rb") as f:
        barcode_bytes = f.read()
    os.unlink(barcode_path)

    return StreamingResponse(
        io.BytesIO(barcode_bytes),
        media_type="image/png",
        headers={"Content-Disposition": "inline; filename=barcode.png"},
    )


@app.post("/api/watermark")
async def api_watermark(
    nachname: str = Form(...),
    vorname: str = Form(...),
    geburtsdatum: str = Form(...),
    klasse: str = Form("2"),
    passagier_typ: str = Form("ERWACHSENER"),
    gueltig_von: str = Form(""),
    gueltig_bis: str = Form(""),
    product: str = Form("grp_consecutive"),
    tage: str = Form("15"),
    von: str = Form(""),
    nach: str = Form(""),
    zug_typ: str = Form("ICE"),
    zug_nummer: str = Form("919"),
    ticket_id: str = Form(""),
    order_number: str = Form(""),
):
    """Returns the combined watermark image (ticket number + bottom watermark) as JPEG."""
    name = f"{nachname}/{vorname}"
    days_int = int(tage) if tage.isdigit() else 15

    if not gueltig_von:
        gueltig_von = datetime.now().strftime("%d.%m.%Y")
    if not gueltig_bis:
        gueltig_bis = _calc_validity_end(gueltig_von, days_int, product)

    price_table = ALL_PRICES.get(product, {})
    price = ""
    if price_table:
        day_prices = price_table.get(days_int, {})
        if not day_prices:
            first_key = next(iter(price_table), None)
            day_prices = price_table.get(first_key, {})
        price = day_prices.get((klasse, passagier_typ), "")

    cfg = _build_cfg(
        name=name,
        birth_date=geburtsdatum,
        validity_start=gueltig_von,
        validity_end=gueltig_bis,
        ticket_id=ticket_id,
        order_number=order_number,
        klasse=klasse,
        days=str(days_int),
        passenger_type=passagier_typ,
        price=price,
        payment_method="SEPA",
        payment_date="",
        booking_date="",
        product=product,
        station_from=von,
        station_to=nach,
        zugtyp=zug_typ,
        train_number=zug_nummer,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        ticket_num_path = os.path.join(tmpdir, "ticket_num.jpeg")
        wm_bottom_path = os.path.join(tmpdir, "wm_bottom.jpeg")
        combined_path = os.path.join(tmpdir, "watermark_combined.jpeg")

        generate_ticket_number_image(cfg['ticket_id'], ticket_num_path)
        generate_watermark_bottom(cfg, wm_bottom_path)

        num_img = cv2.imread(ticket_num_path)
        bottom_img = cv2.imread(wm_bottom_path)

        target_w = 1024
        if num_img.shape[1] != target_w:
            num_img = cv2.resize(num_img, (target_w, int(num_img.shape[0] * target_w / num_img.shape[1])))
        if bottom_img.shape[1] != target_w:
            bottom_img = cv2.resize(bottom_img, (target_w, int(bottom_img.shape[0] * target_w / bottom_img.shape[1])))

        combined = np.vstack([num_img, bottom_img])
        cv2.imwrite(combined_path, combined, [cv2.IMWRITE_JPEG_QUALITY, 92])

        with open(combined_path, "rb") as f:
            img_bytes = f.read()

    return StreamingResponse(
        io.BytesIO(img_bytes),
        media_type="image/jpeg",
        headers={"Content-Disposition": "inline; filename=watermark.jpg"},
    )


def _calc_validity_end(start_str, days_int, product):
    """Calculate validity end date from start + days."""
    try:
        dt = datetime.strptime(start_str, "%d.%m.%Y")
    except ValueError:
        return start_str
    if product == "deutschlandticket":
        if dt.month == 12:
            end_dt = datetime(dt.year + 1, 1, 1) - timedelta(days=1)
        else:
            end_dt = datetime(dt.year, dt.month + 1, 1) - timedelta(days=1)
    elif product == "db_sparpreis":
        end_dt = dt + timedelta(days=1)
    elif product == "grp_flexi":
        end_dt = dt + timedelta(days=29)
    elif product == "eurail_global" and days_int <= 15:
        end_dt = dt + timedelta(days=29)
    else:
        end_dt = dt + timedelta(days=days_int - 1)
    return end_dt.strftime("%d.%m.%Y")


@app.post("/batch")
async def batch_generate(file: UploadFile = File(...)):
    """Generate multiple tickets from CSV upload. Returns ZIP with PDFs."""
    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, row in enumerate(reader):
            product = row.get("product", "grp_consecutive").strip()
            days_str = row.get("days", "15").strip()
            klasse = row.get("klasse", "2").strip()
            ptype = row.get("passenger_type", "ERWACHSENER").strip()
            start = row.get("validity_start", "01.01.2026").strip()
            days_int = int(days_str)

            price_table = ALL_PRICES.get(product, PRICES_GRP_CONSECUTIVE)
            price = row.get("price", "").strip()
            if not price and days_int in price_table:
                price = price_table[days_int].get((klasse, ptype), "0,00\u20ac")
            if not price:
                price = "0,00\u20ac"

            end = row.get("validity_end", "").strip()
            if not end:
                end = _calc_validity_end(start, days_int, product)

            cfg = _build_cfg(
                name=row.get("name", "Passenger").strip(),
                birth_date=row.get("birth_date", "01.01.2000").strip(),
                validity_start=start,
                validity_end=end,
                ticket_id=row.get("ticket_id", "").strip(),
                order_number=row.get("order_number", "").strip(),
                klasse=klasse,
                days=days_str,
                passenger_type=ptype,
                price=price,
                payment_method=row.get("payment_method", "SEPA").strip(),
                payment_date=row.get("payment_date", "").strip(),
                booking_date=row.get("booking_date", "").strip(),
                product=product,
                residence=row.get("residence", "Germany").strip(),
                station_from=row.get("station_from", "").strip(),
                station_to=row.get("station_to", "").strip(),
                zugtyp=row.get("zugtyp", "ICE").strip(),
                fare_name=row.get("fare_name", "").strip(),
            )

            pdf_bytes = generate_pdf(cfg)
            filename = f"ticket_{i+1:03d}_{cfg['ticket_id']}.pdf"
            zf.writestr(filename, pdf_bytes)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=tickets_batch.zip"}
    )


# ─── HTML ────────────────────────────────────────────────────────────────────

LOOKUP_HTML = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Meine Tickets</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #f0f2f5; min-height: 100vh; display: flex; justify-content: center;
       align-items: flex-start; padding: 40px 20px; }
.container { max-width: 560px; width: 100%; }
.card { background: #fff; border-radius: 12px; box-shadow: 0 2px 20px rgba(0,0,0,0.08);
        padding: 40px; margin-bottom: 20px; }
h1 { font-size: 24px; margin-bottom: 8px; color: #1a1a1a; }
.subtitle { color: #666; font-size: 14px; margin-bottom: 28px; }
.form-group { margin-bottom: 16px; }
label { display: block; font-size: 13px; font-weight: 600; color: #333; margin-bottom: 4px; }
input { width: 100%; padding: 10px 12px; border: 1px solid #d0d5dd; border-radius: 8px;
        font-size: 14px; color: #1a1a1a; transition: border-color 0.2s; }
input:focus { outline: none; border-color: #ec0016; box-shadow: 0 0 0 3px rgba(236,0,22,0.1); }
button { width: 100%; padding: 12px; background: #ec0016; color: #fff; border: none;
         border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer;
         transition: background 0.2s; margin-top: 8px; }
button:hover { background: #c9000f; }
button:disabled { background: #ccc; cursor: wait; }
.back-link { display: inline-block; margin-bottom: 20px; color: #ec0016; text-decoration: none;
             font-size: 14px; font-weight: 600; }
.back-link:hover { text-decoration: underline; }
.error { background: #fef2f2; border: 1px solid #fecaca; color: #dc2626; padding: 12px;
         border-radius: 8px; margin-top: 16px; display: none; font-size: 14px; }
.ticket-result { display: none; margin-top: 20px; }
.ticket-card { background: #fff; border-radius: 12px; border: 2px solid #ec0016;
               overflow: hidden; }
.ticket-header { background: #ec0016; color: #fff; padding: 20px; }
.ticket-header h2 { font-size: 20px; margin: 0; color: #fff; }
.ticket-header .ticket-type { font-size: 13px; opacity: 0.9; margin-top: 4px; }
.ticket-body { padding: 20px; }
.ticket-row { display: flex; justify-content: space-between; padding: 10px 0;
              border-bottom: 1px solid #f0f0f0; }
.ticket-row:last-child { border-bottom: none; }
.ticket-label { font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }
.ticket-value { font-size: 15px; color: #1a1a1a; font-weight: 600; text-align: right; }
.ticket-barcode { text-align: center; padding: 20px; border-top: 2px dashed #eee; }
.ticket-barcode img { max-width: 200px; }
.ticket-watermark { text-align: center; padding: 10px 20px 20px; }
.ticket-watermark img { max-width: 100%; border-radius: 8px; border: 1px solid #eee; }
</style>
</head>
<body>
<div class="container">
<a href="/" class="back-link">&larr; Zum Ticket Generator</a>

<div class="card">
  <h1>Meine Tickets</h1>
  <p class="subtitle">Ticket abrufen mit Auftragsnummer und Nachname</p>

  <form id="lookupForm" onsubmit="lookupTicket(event)">
    <div class="form-group">
      <label>Auftragsnummer</label>
      <input type="text" id="auftragsNr" placeholder="z.B. 1234567890123" required />
    </div>
    <div class="form-group">
      <label>Nachname</label>
      <input type="text" id="nachname" placeholder="z.B. Mustermann" required />
    </div>
    <button type="submit" id="lookupBtn">Ticket suchen</button>
  </form>

  <div class="error" id="errorMsg"></div>
</div>

<div class="ticket-result" id="ticketResult">
  <div class="ticket-card">
    <div class="ticket-header">
      <h2 id="tProductLabel">—</h2>
      <div class="ticket-type" id="tAuftrag">—</div>
    </div>
    <div class="ticket-body">
      <div class="ticket-row"><div><span class="ticket-label">Name</span></div><div class="ticket-value" id="tName">—</div></div>
      <div class="ticket-row"><div><span class="ticket-label">Geburtsdatum</span></div><div class="ticket-value" id="tGeburt">—</div></div>
      <div class="ticket-row"><div><span class="ticket-label">Klasse</span></div><div class="ticket-value" id="tKlasse">—</div></div>
      <div class="ticket-row"><div><span class="ticket-label">Passagiertyp</span></div><div class="ticket-value" id="tPassagier">—</div></div>
      <div class="ticket-row"><div><span class="ticket-label">Gültig von</span></div><div class="ticket-value" id="tVon">—</div></div>
      <div class="ticket-row"><div><span class="ticket-label">Gültig bis</span></div><div class="ticket-value" id="tBis">—</div></div>
      <div class="ticket-row"><div><span class="ticket-label">Preis</span></div><div class="ticket-value" id="tPreis">—</div></div>
      <div class="ticket-row"><div><span class="ticket-label">Ticket-ID</span></div><div class="ticket-value" id="tTicketId">—</div></div>
    </div>
    <div class="ticket-barcode" id="tBarcodeSection" style="display:none">
      <p style="font-size:12px;color:#888;margin-bottom:8px">Aztec Barcode</p>
      <img id="tBarcode" src="" alt="Barcode" />
    </div>
    <div class="ticket-watermark" id="tWatermarkSection" style="display:none">
      <img id="tWatermark" src="" alt="Ticket Vorschau" />
    </div>
  </div>
</div>

</div>

<script>
async function lookupTicket(e) {
  e.preventDefault();
  var btn = document.getElementById('lookupBtn');
  var errDiv = document.getElementById('errorMsg');
  var resultDiv = document.getElementById('ticketResult');
  btn.disabled = true;
  btn.textContent = 'Suche...';
  errDiv.style.display = 'none';
  resultDiv.style.display = 'none';

  var nr = document.getElementById('auftragsNr').value.trim();
  var name = document.getElementById('nachname').value.trim();

  try {
    var fd = new FormData();
    fd.append('auftragsnummer', nr);
    fd.append('nachname', name);
    var resp = await fetch('/ticket-lookup', { method: 'POST', body: fd });
    var data = await resp.json();

    if (!resp.ok) {
      errDiv.textContent = data.error || 'Ticket nicht gefunden';
      errDiv.style.display = 'block';
      btn.disabled = false;
      btn.textContent = 'Ticket suchen';
      return;
    }

    document.getElementById('tProductLabel').textContent = data.ticket_type_label || data.product || '—';
    document.getElementById('tAuftrag').textContent = 'Auftragsnr. ' + (data.auftragsnummer || '—');
    document.getElementById('tName').textContent = data.name || '—';
    document.getElementById('tGeburt').textContent = data.geburtsdatum || '—';
    document.getElementById('tKlasse').textContent = (data.klasse === '1' ? '1. Klasse' : '2. Klasse');
    document.getElementById('tPassagier').textContent = data.passagier_typ || '—';
    document.getElementById('tVon').textContent = data.gueltig_von || '—';
    document.getElementById('tBis').textContent = data.gueltig_bis || '—';
    document.getElementById('tPreis').textContent = data.preis || '—';
    document.getElementById('tTicketId').textContent = data.ticket_id || '—';

    var barcodeSection = document.getElementById('tBarcodeSection');
    if (data.barcode_base64) {
      document.getElementById('tBarcode').src = 'data:image/png;base64,' + data.barcode_base64;
      barcodeSection.style.display = 'block';
    } else {
      barcodeSection.style.display = 'none';
    }

    var wmSection = document.getElementById('tWatermarkSection');
    if (data.watermark_base64) {
      document.getElementById('tWatermark').src = 'data:image/png;base64,' + data.watermark_base64;
      wmSection.style.display = 'block';
    } else {
      wmSection.style.display = 'none';
    }

    resultDiv.style.display = 'block';
    resultDiv.scrollIntoView({ behavior: 'smooth' });
  } catch (err) {
    errDiv.textContent = 'Verbindungsfehler: ' + err.message;
    errDiv.style.display = 'block';
  }
  btn.disabled = false;
  btn.textContent = 'Ticket suchen';
}
</script>
</body>
</html>"""


HTML_FORM = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ticket Generator</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #f0f2f5; min-height: 100vh; display: flex; justify-content: center;
       align-items: flex-start; padding: 40px 20px; }
.container { max-width: 560px; width: 100%; }
.card { background: #fff; border-radius: 12px; box-shadow: 0 2px 20px rgba(0,0,0,0.08);
        padding: 40px; margin-bottom: 20px; }
h1 { font-size: 24px; margin-bottom: 8px; color: #1a1a1a; }
h2 { font-size: 18px; margin-bottom: 12px; color: #1a1a1a; }
.subtitle { color: #666; font-size: 14px; margin-bottom: 28px; }
.form-group { margin-bottom: 16px; }
label { display: block; font-size: 13px; font-weight: 600; color: #333;
        margin-bottom: 4px; }
input, select { width: 100%; padding: 10px 12px; border: 1px solid #d0d5dd;
                border-radius: 8px; font-size: 14px; color: #1a1a1a;
                transition: border-color 0.2s; }
input:focus, select:focus { outline: none; border-color: #ec0016; box-shadow: 0 0 0 3px rgba(236,0,22,0.1); }
.row { display: flex; gap: 12px; }
.row .form-group { flex: 1; }
button, .btn { width: 100%; padding: 12px; background: #ec0016; color: #fff;
         border: none; border-radius: 8px; font-size: 16px; font-weight: 600;
         cursor: pointer; transition: background 0.2s; margin-top: 8px; }
button:hover, .btn:hover { background: #c9000f; }
button:disabled { background: #ccc; cursor: wait; }
.btn-secondary { background: #1a365d; }
.btn-secondary:hover { background: #0f2440; }
.divider { border-top: 1px solid #eee; margin: 20px 0; }
.hint { font-size: 12px; color: #888; margin-top: 4px; }
.loading { display: none; text-align: center; padding: 20px; color: #666; }
.batch-info { background: #f8f9fa; border-radius: 8px; padding: 12px; margin-top: 12px; font-size: 12px; color: #555; }
.batch-info code { background: #e9ecef; padding: 2px 6px; border-radius: 4px; font-size: 11px; }
</style>
</head>
<body>
<div class="container">

<div class="card">
  <h1>Ticket Generator</h1>
  <p class="subtitle">German Rail Pass, Eurail, DB Sparpreis & Deutschlandticket</p>
  <a href="/lookup" style="display:inline-block;margin-bottom:16px;color:#ec0016;font-size:14px;font-weight:600;text-decoration:none">Meine Tickets abrufen &rarr;</a>

  <form id="ticketForm" action="/generate" method="post">
    <div class="form-group">
      <label>Produkt</label>
      <select name="product" id="productSelect">
        <option value="grp_consecutive" selected>German Rail Pass - Consecutive</option>
        <option value="grp_flexi">German Rail Pass - Flexi</option>
        <option value="eurail_global">Eurail Global Pass</option>
        <option value="db_sparpreis">DB Sparpreis / Super Sparpreis</option>
        <option value="deutschlandticket">Deutschlandticket (63&euro;)</option>
      </select>
    </div>

    <div id="sparpreisFields" style="display:none">
      <div class="row">
        <div class="form-group">
          <label>Von (Abfahrt)</label>
          <select name="station_from" id="stationFrom">
            <option value="Berlin Hbf" selected>Berlin Hbf</option>
            <option value="Hamburg Hbf">Hamburg Hbf</option>
            <option value="M&uuml;nchen Hbf">M&uuml;nchen Hbf</option>
            <option value="K&ouml;ln Hbf">K&ouml;ln Hbf</option>
            <option value="K&ouml;ln Messe/Deutz">K&ouml;ln Messe/Deutz</option>
            <option value="Frankfurt(Main)Hbf">Frankfurt(Main)Hbf</option>
            <option value="Stuttgart Hbf">Stuttgart Hbf</option>
            <option value="D&uuml;sseldorf Hbf">D&uuml;sseldorf Hbf</option>
            <option value="Hannover Hbf">Hannover Hbf</option>
            <option value="Leipzig Hbf">Leipzig Hbf</option>
            <option value="Dresden Hbf">Dresden Hbf</option>
            <option value="N&uuml;rnberg Hbf">N&uuml;rnberg Hbf</option>
            <option value="Bremen Hbf">Bremen Hbf</option>
            <option value="Dortmund Hbf">Dortmund Hbf</option>
            <option value="Essen Hbf">Essen Hbf</option>
            <option value="Mannheim Hbf">Mannheim Hbf</option>
            <option value="Karlsruhe Hbf">Karlsruhe Hbf</option>
            <option value="Augsburg Hbf">Augsburg Hbf</option>
            <option value="Freiburg(Brsg)Hbf">Freiburg(Brsg)Hbf</option>
            <option value="Erfurt Hbf">Erfurt Hbf</option>
            <option value="Rostock Hbf">Rostock Hbf</option>
          </select>
        </div>
        <div class="form-group">
          <label>Nach (Ankunft)</label>
          <select name="station_to" id="stationTo">
            <option value="Berlin Hbf">Berlin Hbf</option>
            <option value="Hamburg Hbf">Hamburg Hbf</option>
            <option value="M&uuml;nchen Hbf" selected>M&uuml;nchen Hbf</option>
            <option value="K&ouml;ln Hbf">K&ouml;ln Hbf</option>
            <option value="K&ouml;ln Messe/Deutz">K&ouml;ln Messe/Deutz</option>
            <option value="Frankfurt(Main)Hbf">Frankfurt(Main)Hbf</option>
            <option value="Stuttgart Hbf">Stuttgart Hbf</option>
            <option value="D&uuml;sseldorf Hbf">D&uuml;sseldorf Hbf</option>
            <option value="Hannover Hbf">Hannover Hbf</option>
            <option value="Leipzig Hbf">Leipzig Hbf</option>
            <option value="Dresden Hbf">Dresden Hbf</option>
            <option value="N&uuml;rnberg Hbf">N&uuml;rnberg Hbf</option>
            <option value="Bremen Hbf">Bremen Hbf</option>
            <option value="Dortmund Hbf">Dortmund Hbf</option>
            <option value="Essen Hbf">Essen Hbf</option>
            <option value="Mannheim Hbf">Mannheim Hbf</option>
            <option value="Karlsruhe Hbf">Karlsruhe Hbf</option>
            <option value="Augsburg Hbf">Augsburg Hbf</option>
            <option value="Freiburg(Brsg)Hbf">Freiburg(Brsg)Hbf</option>
            <option value="Erfurt Hbf">Erfurt Hbf</option>
            <option value="Rostock Hbf">Rostock Hbf</option>
          </select>
        </div>
      </div>
      <div class="row">
        <div class="form-group">
          <label>Zugtyp</label>
          <select name="zugtyp" id="zugtypSelect">
            <option value="ICE" selected>ICE</option>
            <option value="IC/EC">IC/EC</option>
            <option value="ICE/IC">ICE/IC</option>
          </select>
        </div>
        <div class="form-group">
          <label>Tarifname</label>
          <select name="fare_name" id="fareNameSelect">
            <option value="Super Sparpreis" selected>Super Sparpreis</option>
            <option value="Sparpreis">Sparpreis</option>
            <option value="Flexpreis">Flexpreis</option>
          </select>
        </div>
      </div>
      <div class="row">
        <div class="form-group">
          <label>Zugnummer</label>
          <input type="text" name="train_number" value="919" placeholder="z.B. 919">
        </div>
        <div class="form-group">
          <label>Abfahrt (Std:Min)</label>
          <div class="row">
            <input type="number" name="departure_hour" value="13" min="0" max="23" style="width:45%">
            <input type="number" name="departure_minute" value="30" min="0" max="59" style="width:45%">
          </div>
        </div>
      </div>
      <div class="row">
        <div class="form-group">
          <label>Gleis Abfahrt</label>
          <input type="text" name="departure_track" value="" placeholder="z.B. 11">
        </div>
        <div class="form-group">
          <label>Gleis Ankunft</label>
          <input type="text" name="arrival_track" value="" placeholder="z.B. 15">
        </div>
      </div>
      <input type="hidden" name="via_text" value="">
    </div>

    <div class="form-group">
      <label>Passagier Name</label>
      <input type="text" name="name" value="Test Mustermann" required>
    </div>

    <div class="form-group">
      <label>Geburtsdatum</label>
      <input type="text" name="birth_date" value="01.01.2000" placeholder="TT.MM.JJJJ" required>
    </div>

    <div class="divider"></div>

    <div class="row">
      <div class="form-group">
        <label>Tage</label>
        <select name="days" id="daysSelect">
          <option value="3">3 Tage</option>
          <option value="4">4 Tage</option>
          <option value="5">5 Tage</option>
          <option value="7">7 Tage</option>
          <option value="10">10 Tage</option>
          <option value="15" selected>15 Tage</option>
        </select>
      </div>
      <div class="form-group">
        <label>Passagiertyp</label>
        <select name="passenger_type" id="passengerSelect">
          <option value="AUTO" selected>Auto (aus Geburtsdatum)</option>
          <option value="ERWACHSENER">Erwachsener</option>
          <option value="JUGENDLICHER">Jugendlicher (12-27)</option>
        </select>
        <p class="hint" id="autoTypeHint"></p>
      </div>
    </div>

    <div class="form-group">
      <label>Wohnsitz / Residence</label>
      <select name="residence" id="residenceSelect">
        <option value="Germany" selected>Germany</option>
        <option value="Austria">Austria</option>
        <option value="Belgium">Belgium</option>
        <option value="Bulgaria">Bulgaria</option>
        <option value="Croatia">Croatia</option>
        <option value="Czech Republic">Czech Republic</option>
        <option value="Denmark">Denmark</option>
        <option value="Estonia">Estonia</option>
        <option value="Finland">Finland</option>
        <option value="France">France</option>
        <option value="Great Britain">Great Britain</option>
        <option value="Greece">Greece</option>
        <option value="Hungary">Hungary</option>
        <option value="Ireland">Ireland</option>
        <option value="Italy">Italy</option>
        <option value="Latvia">Latvia</option>
        <option value="Lithuania">Lithuania</option>
        <option value="Luxembourg">Luxembourg</option>
        <option value="Netherlands">Netherlands</option>
        <option value="Norway">Norway</option>
        <option value="Poland">Poland</option>
        <option value="Portugal">Portugal</option>
        <option value="Romania">Romania</option>
        <option value="Serbia">Serbia</option>
        <option value="Slovakia">Slovakia</option>
        <option value="Slovenia">Slovenia</option>
        <option value="Spain">Spain</option>
        <option value="Sweden">Sweden</option>
        <option value="Switzerland">Switzerland</option>
        <option value="Turkey">Turkey</option>
        <option value="United Kingdom">United Kingdom</option>
        <option value="United States">United States</option>
      </select>
    </div>

    <div class="row">
      <div class="form-group">
        <label>Gueltigkeit Start</label>
        <input type="text" name="validity_start" id="validityStart" value="01.01.2026" placeholder="TT.MM.JJJJ" required>
      </div>
      <div class="form-group">
        <label>Gueltigkeit Ende</label>
        <input type="text" name="validity_end" id="validityEnd" value="15.01.2026" placeholder="TT.MM.JJJJ" required>
        <p class="hint">Wird automatisch berechnet</p>
      </div>
    </div>

    <div class="row">
      <div class="form-group">
        <label>Ticket-ID</label>
        <input type="text" name="ticket_id" value="" placeholder="Auto-Random">
        <p class="hint">Leer = zufaellig (7 Ziffern)</p>
      </div>
      <div class="form-group">
        <label>Auftragsnummer</label>
        <input type="text" name="order_number" value="" placeholder="Auto-Random">
        <p class="hint">Leer = zufaellig (13 Ziffern)</p>
      </div>
    </div>

    <div class="divider"></div>

    <div class="row">
      <div class="form-group">
        <label>Klasse</label>
        <select name="klasse" id="klasseSelect">
          <option value="1">1. Klasse</option>
          <option value="2" selected>2. Klasse</option>
        </select>
      </div>
      <div class="form-group">
        <label>Preis</label>
        <input type="text" name="price" id="priceInput" value="452,00&#8364;">
        <p class="hint">Wird automatisch gesetzt</p>
      </div>
    </div>

    <div class="row">
      <div class="form-group">
        <label>Zahlungsmethode</label>
        <input type="text" name="payment_method" value="SEPA">
      </div>
      <div class="form-group">
        <label>Zahlungsdatum</label>
        <input type="text" name="payment_date" placeholder="= Validity Start">
        <p class="hint">Leer = gleich wie Start</p>
      </div>
    </div>

    <input type="hidden" name="booking_date" value="">

    <button type="submit" id="submitBtn">PDF Generieren & Herunterladen</button>
  </form>

  <div class="loading" id="loading">PDF wird generiert...</div>
</div>

<div class="card">
  <h2>Batch-Generierung</h2>
  <p class="subtitle">Mehrere Tickets aus CSV-Datei generieren</p>
  <form id="batchForm" action="/batch" method="post" enctype="multipart/form-data">
    <div class="form-group">
      <label>CSV-Datei hochladen</label>
      <input type="file" name="file" accept=".csv" required>
    </div>
    <button type="submit" class="btn btn-secondary" id="batchBtn">Batch generieren (ZIP)</button>
  </form>
  <div class="batch-info">
    <strong>CSV-Spalten:</strong><br>
    <code>name</code>, <code>birth_date</code>, <code>days</code>, <code>klasse</code>,
    <code>passenger_type</code>, <code>validity_start</code>, <code>product</code><br>
    <strong>Optional:</strong> <code>validity_end</code>, <code>price</code>,
    <code>ticket_id</code>, <code>order_number</code>, <code>payment_method</code><br>
    <strong>Produkt-Werte:</strong> <code>grp_consecutive</code>, <code>grp_flexi</code>, <code>eurail_global</code>,
    <code>db_sparpreis</code>, <code>deutschlandticket</code><br>
    <strong>Sparpreis extra:</strong> <code>station_from</code>, <code>station_to</code>, <code>zugtyp</code>, <code>fare_name</code>
  </div>
</div>

</div>

<script>
var ALL_PRICES = {
  "grp_consecutive": {
    "3":  {"2": {"ERWACHSENER": "191,00\u20ac", "JUGENDLICHER": "153,00\u20ac"},
           "1": {"ERWACHSENER": "255,00\u20ac", "JUGENDLICHER": "204,00\u20ac"}},
    "4":  {"2": {"ERWACHSENER": "218,00\u20ac", "JUGENDLICHER": "174,00\u20ac"},
           "1": {"ERWACHSENER": "290,00\u20ac", "JUGENDLICHER": "232,00\u20ac"}},
    "5":  {"2": {"ERWACHSENER": "240,00\u20ac", "JUGENDLICHER": "192,00\u20ac"},
           "1": {"ERWACHSENER": "320,00\u20ac", "JUGENDLICHER": "256,00\u20ac"}},
    "7":  {"2": {"ERWACHSENER": "279,00\u20ac", "JUGENDLICHER": "223,00\u20ac"},
           "1": {"ERWACHSENER": "372,00\u20ac", "JUGENDLICHER": "298,00\u20ac"}},
    "10": {"2": {"ERWACHSENER": "367,00\u20ac", "JUGENDLICHER": "294,00\u20ac"},
           "1": {"ERWACHSENER": "490,00\u20ac", "JUGENDLICHER": "392,00\u20ac"}},
    "15": {"2": {"ERWACHSENER": "452,00\u20ac", "JUGENDLICHER": "362,00\u20ac"},
           "1": {"ERWACHSENER": "603,00\u20ac", "JUGENDLICHER": "482,00\u20ac"}}
  },
  "grp_flexi": {
    "3":  {"2": {"ERWACHSENER": "192,00\u20ac", "JUGENDLICHER": "154,00\u20ac"},
           "1": {"ERWACHSENER": "256,00\u20ac", "JUGENDLICHER": "205,00\u20ac"}},
    "4":  {"2": {"ERWACHSENER": "222,00\u20ac", "JUGENDLICHER": "178,00\u20ac"},
           "1": {"ERWACHSENER": "296,00\u20ac", "JUGENDLICHER": "237,00\u20ac"}},
    "5":  {"2": {"ERWACHSENER": "246,00\u20ac", "JUGENDLICHER": "197,00\u20ac"},
           "1": {"ERWACHSENER": "328,00\u20ac", "JUGENDLICHER": "262,00\u20ac"}},
    "7":  {"2": {"ERWACHSENER": "292,00\u20ac", "JUGENDLICHER": "234,00\u20ac"},
           "1": {"ERWACHSENER": "389,00\u20ac", "JUGENDLICHER": "311,00\u20ac"}},
    "10": {"2": {"ERWACHSENER": "392,00\u20ac", "JUGENDLICHER": "314,00\u20ac"},
           "1": {"ERWACHSENER": "523,00\u20ac", "JUGENDLICHER": "418,00\u20ac"}},
    "15": {"2": {"ERWACHSENER": "486,00\u20ac", "JUGENDLICHER": "389,00\u20ac"},
           "1": {"ERWACHSENER": "648,00\u20ac", "JUGENDLICHER": "518,00\u20ac"}}
  },
  "eurail_global": {
    "4":  {"2": {"ERWACHSENER": "261,00\u20ac", "JUGENDLICHER": "209,00\u20ac"},
           "1": {"ERWACHSENER": "348,00\u20ac", "JUGENDLICHER": "278,00\u20ac"}},
    "5":  {"2": {"ERWACHSENER": "296,00\u20ac", "JUGENDLICHER": "237,00\u20ac"},
           "1": {"ERWACHSENER": "395,00\u20ac", "JUGENDLICHER": "316,00\u20ac"}},
    "7":  {"2": {"ERWACHSENER": "349,00\u20ac", "JUGENDLICHER": "279,00\u20ac"},
           "1": {"ERWACHSENER": "465,00\u20ac", "JUGENDLICHER": "372,00\u20ac"}},
    "10": {"2": {"ERWACHSENER": "415,00\u20ac", "JUGENDLICHER": "332,00\u20ac"},
           "1": {"ERWACHSENER": "553,00\u20ac", "JUGENDLICHER": "442,00\u20ac"}},
    "15": {"2": {"ERWACHSENER": "489,00\u20ac", "JUGENDLICHER": "391,00\u20ac"},
           "1": {"ERWACHSENER": "652,00\u20ac", "JUGENDLICHER": "522,00\u20ac"}},
    "22": {"2": {"ERWACHSENER": "448,00\u20ac", "JUGENDLICHER": "358,00\u20ac"},
           "1": {"ERWACHSENER": "597,00\u20ac", "JUGENDLICHER": "478,00\u20ac"}},
    "31": {"2": {"ERWACHSENER": "560,00\u20ac", "JUGENDLICHER": "448,00\u20ac"},
           "1": {"ERWACHSENER": "747,00\u20ac", "JUGENDLICHER": "597,00\u20ac"}}
  },
  "deutschlandticket": {
    "1": {"2": {"ERWACHSENER": "63,00\u20ac"}}
  }
};

var DAY_OPTIONS = {
  "grp_consecutive": [3, 4, 5, 7, 10, 15],
  "grp_flexi": [3, 4, 5, 7, 10, 15],
  "eurail_global": [4, 5, 7, 10, 15, 22, 31],
  "db_sparpreis": [1],
  "deutschlandticket": [1]
};

function updateDaysOptions() {
  var product = document.getElementById('productSelect').value;
  var daysSelect = document.getElementById('daysSelect');
  var options = DAY_OPTIONS[product] || [15];
  var currentVal = parseInt(daysSelect.value);
  daysSelect.innerHTML = '';
  options.forEach(function(d) {
    var opt = document.createElement('option');
    opt.value = d;
    opt.text = d + ' Tage';
    if (d === currentVal) opt.selected = true;
    daysSelect.appendChild(opt);
  });
  if (!options.includes(currentVal)) {
    daysSelect.value = options[options.length - 1];
  }
}

function detectPassengerType() {
  var birthStr = document.querySelector('input[name="birth_date"]').value;
  var startStr = document.getElementById('validityStart').value;
  var bp = birthStr.split('.'), sp = startStr.split('.');
  if (bp.length !== 3 || sp.length !== 3) return 'ERWACHSENER';
  var bd = new Date(parseInt(bp[2]), parseInt(bp[1])-1, parseInt(bp[0]));
  var sd = new Date(parseInt(sp[2]), parseInt(sp[1])-1, parseInt(sp[0]));
  var age = sd.getFullYear() - bd.getFullYear();
  if (sd.getMonth() < bd.getMonth() || (sd.getMonth() === bd.getMonth() && sd.getDate() < bd.getDate())) age--;
  return (age >= 12 && age <= 27) ? 'JUGENDLICHER' : 'ERWACHSENER';
}

function getEffectivePassengerType() {
  var sel = document.getElementById('passengerSelect').value;
  if (sel === 'AUTO') return detectPassengerType();
  return sel;
}

function updateAutoHint() {
  var sel = document.getElementById('passengerSelect').value;
  var hint = document.getElementById('autoTypeHint');
  if (sel === 'AUTO') {
    var detected = detectPassengerType();
    hint.textContent = 'Erkannt: ' + (detected === 'JUGENDLICHER' ? 'Jugendlicher' : 'Erwachsener');
  } else {
    hint.textContent = '';
  }
}

function updatePrice() {
  var product = document.getElementById('productSelect').value;
  if (product === 'deutschlandticket') {
    document.getElementById('priceInput').value = "63,00\u20ac";
    return;
  }
  if (product === 'db_sparpreis') {
    return;
  }
  var days = document.getElementById('daysSelect').value;
  var klasse = document.getElementById('klasseSelect').value;
  var ptype = getEffectivePassengerType();
  var pt = ALL_PRICES[product];
  if (pt && pt[days] && pt[days][klasse] && pt[days][klasse][ptype]) {
    document.getElementById('priceInput').value = pt[days][klasse][ptype];
  }
  updateAutoHint();
}

function updateValidityEnd() {
  var product = document.getElementById('productSelect').value;
  var startStr = document.getElementById('validityStart').value;
  var days = parseInt(document.getElementById('daysSelect').value);
  var parts = startStr.split('.');
  if (parts.length !== 3) return;
  var d = parseInt(parts[0]), m = parseInt(parts[1]) - 1, y = parseInt(parts[2]);
  if (isNaN(d) || isNaN(m) || isNaN(y)) return;
  var dt = new Date(y, m, d);
  if (product === 'deutschlandticket') {
    dt = new Date(y, m + 1, 0);
  } else if (product === 'db_sparpreis') {
    dt.setDate(dt.getDate() + 1);
  } else if (product === 'grp_flexi' || (product === 'eurail_global' && days <= 15)) {
    dt.setDate(dt.getDate() + 29);
  } else {
    dt.setDate(dt.getDate() + days - 1);
  }
  var dd = String(dt.getDate()).padStart(2, '0');
  var mm = String(dt.getMonth() + 1).padStart(2, '0');
  var yyyy = dt.getFullYear();
  document.getElementById('validityEnd').value = dd + '.' + mm + '.' + yyyy;
}

function toggleProductFields() {
  var product = document.getElementById('productSelect').value;
  var spFields = document.getElementById('sparpreisFields');
  var daysRow = document.getElementById('daysSelect').closest('.row');
  var residenceGrp = document.getElementById('residenceSelect').closest('.form-group');
  var passengerGrp = document.getElementById('passengerSelect').closest('.row');

  spFields.style.display = (product === 'db_sparpreis') ? 'block' : 'none';

  if (product === 'db_sparpreis' || product === 'deutschlandticket') {
    daysRow.style.display = 'none';
  } else {
    daysRow.style.display = 'flex';
  }

  if (product === 'deutschlandticket') {
    document.getElementById('klasseSelect').value = '2';
    document.getElementById('klasseSelect').disabled = true;
    document.getElementById('priceInput').value = "63,00\u20ac";
    document.getElementById('priceInput').readOnly = true;
    document.getElementById('passengerSelect').value = 'ERWACHSENER';
  } else {
    document.getElementById('klasseSelect').disabled = false;
    document.getElementById('priceInput').readOnly = false;
  }

  if (product === 'eurail_global') {
    residenceGrp.style.display = 'block';
  } else {
    residenceGrp.style.display = 'none';
  }
}

function onProductChange() {
  updateDaysOptions();
  toggleProductFields();
  updatePrice();
  updateValidityEnd();
}

document.getElementById('productSelect').addEventListener('change', onProductChange);
document.getElementById('daysSelect').addEventListener('change', function() { updatePrice(); updateValidityEnd(); });
document.getElementById('klasseSelect').addEventListener('change', updatePrice);
document.getElementById('passengerSelect').addEventListener('change', updatePrice);
document.getElementById('validityStart').addEventListener('change', function() { updateValidityEnd(); updatePrice(); });
document.getElementById('validityStart').addEventListener('input', function() { updateValidityEnd(); updatePrice(); });
document.querySelector('input[name="birth_date"]').addEventListener('change', updatePrice);
document.querySelector('input[name="birth_date"]').addEventListener('input', updatePrice);
updateAutoHint();

document.getElementById('ticketForm').addEventListener('submit', function() {
  document.getElementById('submitBtn').disabled = true;
  document.getElementById('submitBtn').textContent = 'Wird generiert...';
  document.getElementById('loading').style.display = 'block';
  setTimeout(function() {
    document.getElementById('submitBtn').disabled = false;
    document.getElementById('submitBtn').textContent = 'PDF Generieren & Herunterladen';
    document.getElementById('loading').style.display = 'none';
  }, 8000);
});

document.getElementById('batchForm').addEventListener('submit', function() {
  document.getElementById('batchBtn').disabled = true;
  document.getElementById('batchBtn').textContent = 'Wird generiert...';
  setTimeout(function() {
    document.getElementById('batchBtn').disabled = false;
    document.getElementById('batchBtn').textContent = 'Batch generieren (ZIP)';
  }, 30000);
});
</script>
</body>
</html>"""
