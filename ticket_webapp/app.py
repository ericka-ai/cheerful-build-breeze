"""
Web app for generating Deutsche Bahn German Rail Pass Online-Tickets.
FastAPI backend with HTML frontend form.
"""

import fitz  # PyMuPDF
import math
import os
import random
import tempfile
import io
import zlib

import cv2
import numpy as np
import aztec_code_generator as aztec
from PIL import Image, ImageDraw, ImageFont
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(APP_DIR, "assets")

# ─── PRICE TABLE ─────────────────────────────────────────────────────────────
# Official German Rail Pass Consecutive prices (EUR)
# Structure: PRICES[days][(class, passenger_type)] = price_string
PRICES = {
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

app = FastAPI()


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
    repeat = (f"{cfg['name']} / {cfg['birth']} / "
              f"GERMAN RAIL PASS / {cfg['klasse']} / {cfg['ticket_id']} / ")
    wavy = cv2.imread(asset("wavy_main.png"), cv2.IMREAD_GRAYSCALE)
    text = _render_text_layer(width, height, repeat)
    result = np.minimum(wavy, text)
    cv2.imwrite(output_path, result, [cv2.IMWRITE_JPEG_QUALITY, 95])


def generate_watermark_bottom(cfg, output_path):
    width, height = 1024, 232
    repeat = (f"{cfg['name']} / {cfg['birth']} / "
              f"GERMAN RAIL PASS / {cfg['klasse']} / {cfg['ticket_id']} / "
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

# Fixed header (64 bytes) - DSA signature envelope, always the same
_FIXED_HEADER = bytes.fromhex(
    "2355543031393939343030303031302d"
    "021500a559211259a8065b62af96b3b7"
    "50b457d3ac9dae021418b09f4ff8592a"
    "662d289aacdad6910177f704af000000"
)


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
        _uic_field(1, 18, 1, 33, 1, "German Rail Pass"),
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


def generate_aztec_barcode(cfg, output_path):
    """Generate a UIC 918.3 Aztec barcode image."""
    payload = _build_uic918_payload(cfg)
    compressed = zlib.compress(payload)
    barcode_data = (_FIXED_HEADER +
                    f"{len(compressed):04d}".encode('ascii') +
                    compressed)
    code = aztec.AztecCode(barcode_data, ec_percent=50)
    img = code.image(module_size=4, border=1)
    img.save(output_path, "JPEG", quality=95)


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


def build_page1(doc, cfg, wm_main, wm_bottom, ticket_num_img, barcode_img):
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
    txt(page, (39.69, 225.17), f"GERMAN RAIL PASS {cfg['days']} days CONSECUTIVE",
        font="F1", size=10)
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


def build_page2(doc):
    page = doc.new_page(width=W, height=H)
    register_fonts(page)
    SZ = 9.5

    page.insert_image(fitz.Rect(36.85, 45.36, 82.20, 76.54),
                      filename=asset("img_xref14.jpeg"))

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
        (93.40, 536.71,
         "on ICE International trains to Li\u00e8ge and Brussels,"),
        (93.40, 548.10,
         "on DB-\u00d6BB EuroCity trains to Kufstein, Innsbruck, Bolzano/Bozen, Trento, Verona, Bologna and "),
        (93.40, 559.50, "Venice."),
    ]:
        txt(page, (x, y), text, font="F4", size=SZ)

    for x, y, text in [
        (53.69, 570.89,
         "- In case of misuse the GRP holder will be charged with the maximum price of a DB domestic point-"),
        (53.69, 582.32, "  to-point ticket per journey."),
        (53.69, 593.71,
         "- The GRP exempts the holder from paying a surcharge on high speed trains.  "),
        (53.69, 605.11,
         "  Reservations are recommended. Reservations are mandatory on night trains. The GRP is not valid "),
        (53.69, 616.50, "  on Autozug and charter trains."),
        (53.69, 627.90,
         "- GRP holders must pay all supplements and reservation fees for overnight accommodation, "),
        (53.69, 639.29,
         "  registered luggage, meals and other services available on board the trains."),
    ]:
        txt(page, (x, y), text, font="F4", size=SZ)

    txt(page, (228.90, 737.31), "We wish you a pleasant journey.",
        font="F5", size=SZ)


def generate_pdf(cfg):
    """Generate the complete ticket PDF and return bytes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        wm_main = os.path.join(tmpdir, "wm_main.jpeg")
        wm_bottom = os.path.join(tmpdir, "wm_bottom.jpeg")
        ticket_num = os.path.join(tmpdir, "ticket_num.jpeg")
        barcode = os.path.join(tmpdir, "barcode.jpeg")

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
        build_page2(doc)

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
):
    if not ticket_id:
        ticket_id = str(random.randint(1000000, 9999999))
    if not order_number:
        order_number = str(random.randint(1000000000000, 9999999999999))
    if not payment_date:
        payment_date = validity_start
    if not booking_date:
        booking_date = validity_start

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
    }

    pdf_bytes = generate_pdf(cfg)

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=ticket_{ticket_id}.pdf"
        }
    )


# ─── HTML ────────────────────────────────────────────────────────────────────

HTML_FORM = """<!DOCTYPE html>
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
.card { background: #fff; border-radius: 12px; box-shadow: 0 2px 20px rgba(0,0,0,0.08);
        padding: 40px; max-width: 520px; width: 100%; }
h1 { font-size: 24px; margin-bottom: 8px; color: #1a1a1a; }
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
button { width: 100%; padding: 12px; background: #ec0016; color: #fff;
         border: none; border-radius: 8px; font-size: 16px; font-weight: 600;
         cursor: pointer; transition: background 0.2s; margin-top: 8px; }
button:hover { background: #c9000f; }
button:disabled { background: #ccc; cursor: wait; }
.divider { border-top: 1px solid #eee; margin: 20px 0; }
.hint { font-size: 12px; color: #888; margin-top: 4px; }
.loading { display: none; text-align: center; padding: 20px; color: #666; }
</style>
</head>
<body>
<div class="card">
  <h1>Ticket Generator</h1>
  <p class="subtitle">German Rail Pass Online-Ticket erstellen</p>

  <form id="ticketForm" action="/generate" method="post">
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
          <option value="ERWACHSENER" selected>Erwachsener</option>
          <option value="JUGENDLICHER">Jugendlicher (12-27)</option>
        </select>
      </div>
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
        <p class="hint">Leer = wird zufaellig generiert (7 Ziffern)</p>
      </div>
      <div class="form-group">
        <label>Auftragsnummer</label>
        <input type="text" name="order_number" value="" placeholder="Auto-Random">
        <p class="hint">Leer = wird zufaellig generiert (13 Ziffern)</p>
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
        <input type="text" name="price" id="priceInput" value="452,00\u20ac">
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
        <p class="hint">Leer = gleich wie Gueltigkeit Start</p>
      </div>
    </div>

    <input type="hidden" name="booking_date" value="">

    <button type="submit" id="submitBtn">PDF Generieren & Herunterladen</button>
  </form>

  <div class="loading" id="loading">PDF wird generiert...</div>
</div>

<script>
var PRICES = {
  "3":  {"2": {"ERWACHSENER": "191,00\\u20ac", "JUGENDLICHER": "153,00\\u20ac"},
         "1": {"ERWACHSENER": "255,00\\u20ac", "JUGENDLICHER": "204,00\\u20ac"}},
  "4":  {"2": {"ERWACHSENER": "218,00\\u20ac", "JUGENDLICHER": "174,00\\u20ac"},
         "1": {"ERWACHSENER": "290,00\\u20ac", "JUGENDLICHER": "232,00\\u20ac"}},
  "5":  {"2": {"ERWACHSENER": "240,00\\u20ac", "JUGENDLICHER": "192,00\\u20ac"},
         "1": {"ERWACHSENER": "320,00\\u20ac", "JUGENDLICHER": "256,00\\u20ac"}},
  "7":  {"2": {"ERWACHSENER": "279,00\\u20ac", "JUGENDLICHER": "223,00\\u20ac"},
         "1": {"ERWACHSENER": "372,00\\u20ac", "JUGENDLICHER": "298,00\\u20ac"}},
  "10": {"2": {"ERWACHSENER": "367,00\\u20ac", "JUGENDLICHER": "294,00\\u20ac"},
         "1": {"ERWACHSENER": "490,00\\u20ac", "JUGENDLICHER": "392,00\\u20ac"}},
  "15": {"2": {"ERWACHSENER": "452,00\\u20ac", "JUGENDLICHER": "362,00\\u20ac"},
         "1": {"ERWACHSENER": "603,00\\u20ac", "JUGENDLICHER": "482,00\\u20ac"}}
};

function updatePrice() {
  var days = document.getElementById('daysSelect').value;
  var klasse = document.getElementById('klasseSelect').value;
  var ptype = document.getElementById('passengerSelect').value;
  if (PRICES[days] && PRICES[days][klasse] && PRICES[days][klasse][ptype]) {
    document.getElementById('priceInput').value = PRICES[days][klasse][ptype];
  }
}

function updateValidityEnd() {
  var startStr = document.getElementById('validityStart').value;
  var days = parseInt(document.getElementById('daysSelect').value);
  var parts = startStr.split('.');
  if (parts.length !== 3) return;
  var d = parseInt(parts[0]), m = parseInt(parts[1]) - 1, y = parseInt(parts[2]);
  if (isNaN(d) || isNaN(m) || isNaN(y)) return;
  var dt = new Date(y, m, d);
  dt.setDate(dt.getDate() + days - 1);
  var dd = String(dt.getDate()).padStart(2, '0');
  var mm = String(dt.getMonth() + 1).padStart(2, '0');
  var yyyy = dt.getFullYear();
  document.getElementById('validityEnd').value = dd + '.' + mm + '.' + yyyy;
}

document.getElementById('daysSelect').addEventListener('change', function() { updatePrice(); updateValidityEnd(); });
document.getElementById('klasseSelect').addEventListener('change', updatePrice);
document.getElementById('passengerSelect').addEventListener('change', updatePrice);
document.getElementById('validityStart').addEventListener('change', updateValidityEnd);
document.getElementById('validityStart').addEventListener('input', updateValidityEnd);

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
</script>
</body>
</html>"""
