"""
Web app for generating Deutsche Bahn German Rail Pass Online-Tickets.
FastAPI backend with HTML frontend form.
"""

import fitz  # PyMuPDF
import math
import os
import random
import string
import tempfile
import io
import zlib

import cv2
import numpy as np
import aztec_code_generator as aztec
from PIL import Image, ImageDraw, ImageFont
from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(APP_DIR, "assets")

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    code = aztec.AztecCode(barcode_data, ec_percent=70)
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
    txt(page, (39.69, 225.17), f"GERMAN RAIL PASS 15 days CONSECUTIVE",
        font="F1", size=10)
    txt(page, (39.69, 239.83), f"Klasse: {cfg['klasse']}", font="F0", size=10)
    txt(page, (39.69, 254.57), f"Person(en): 1    ERWACHSENER", font="F0", size=10)

    page.draw_rect(fitz.Rect(36.60, 367.68, 349.54, 482.57),
                   color=(0, 0, 0), width=0.45)
    page.draw_line(fitz.Point(36.96, 403.46), fitz.Point(349.74, 403.46),
                   color=(0, 0, 0), width=0.57)

    txt(page, (39.69, 363.26), "Zahlungspositionen und Preis", font="F1", size=11)

    for x, label in [(133.23, "Preis"), (189.92, "MwSt (D)"),
                     (232.44, "19%"), (266.46, "MwSt (D)"), (308.98, "7%")]:
        txt(page, (x, 380.30), label, font="F1", size=8)

    price = cfg['price']
    for x, val in [(39.69, "Fahrkarte"), (133.23, price), (189.92, "0,00\u20ac"),
                   (232.44, "0,00\u20ac"), (266.46, price),
                   (308.98, "29,57\u20ac")]:
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
        f"- Valid 15 days from {cfg['validity_start']} to {cfg['validity_end']}, 2nd class ERWACHSENER.",
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


@app.post("/generate")
async def generate(
    name: str = Form(...),
    birth_date: str = Form(...),
    validity_start: str = Form(...),
    validity_end: str = Form(...),
    ticket_id: str = Form(...),
    order_number: str = Form(...),
    klasse: str = Form("2"),
    price: str = Form("452,00€"),
    payment_method: str = Form("SEPA"),
    payment_date: str = Form(""),
    booking_date: str = Form(""),
):
    if not payment_date:
        payment_date = validity_start
    if not booking_date:
        booking_date = validity_start

    cfg = {
        "name": name,
        "birth": birth_date,
        "validity_start": validity_start,
        "validity_end": validity_end,
        "ticket_id": ticket_id,
        "order_number": order_number,
        "klasse": klasse,
        "price": price,
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


# ─── JSON API for Android App ────────────────────────────────────────────────


@app.post("/api/generate")
async def api_generate(
    auftragsnummer: str = Form(...),
    nachname: str = Form(...),
):
    """JSON endpoint for Android app: accepts Auftragsnummer + Nachname,
    returns ticket data as JSON."""
    import datetime

    today = datetime.date.today()
    validity_end = today + datetime.timedelta(days=14)
    ticket_id = "".join(random.choices(string.digits, k=7))
    klasse = random.choice(["1", "2"])
    products = [
        ("German Rail Pass (Konsekutiv)", "452,00\u20ac"),
        ("German Rail Pass (Flexi)", "398,00\u20ac"),
        ("Eurail Global Pass", "521,00\u20ac"),
        ("Deutschlandticket", "49,00\u20ac"),
        ("DB Sparpreis", "29,90\u20ac"),
    ]
    product, preis = random.choice(products)

    return JSONResponse({
        "auftragsnummer": auftragsnummer,
        "nachname": nachname,
        "ticket_id": ticket_id,
        "klasse": f"{klasse}. Klasse",
        "preis": preis,
        "product": product,
        "gueltig_von": today.strftime("%d.%m.%Y"),
        "gueltig_bis": validity_end.strftime("%d.%m.%Y"),
        "status": "Gültig",
    })


@app.get("/devin", response_class=HTMLResponse)
async def devin_page():
    return DEVIN_HTML


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
  <h1>🎫 Ticket Generator</h1>
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
        <label>Gültigkeit Start</label>
        <input type="text" name="validity_start" value="01.01.2026" placeholder="TT.MM.JJJJ" required>
      </div>
      <div class="form-group">
        <label>Gültigkeit Ende</label>
        <input type="text" name="validity_end" value="15.01.2026" placeholder="TT.MM.JJJJ" required>
      </div>
    </div>

    <div class="row">
      <div class="form-group">
        <label>Ticket-ID</label>
        <input type="text" name="ticket_id" value="2310903" required>
      </div>
      <div class="form-group">
        <label>Auftragsnummer</label>
        <input type="text" name="order_number" value="2026010100110" required>
      </div>
    </div>

    <div class="divider"></div>

    <div class="row">
      <div class="form-group">
        <label>Klasse</label>
        <select name="klasse">
          <option value="1">1. Klasse</option>
          <option value="2" selected>2. Klasse</option>
        </select>
      </div>
      <div class="form-group">
        <label>Preis</label>
        <input type="text" name="price" value="452,00€">
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
        <p class="hint">Leer = gleich wie Gültigkeit Start</p>
      </div>
    </div>

    <input type="hidden" name="booking_date" value="">

    <button type="submit" id="submitBtn">PDF Generieren & Herunterladen</button>
  </form>

  <div class="loading" id="loading">⏳ PDF wird generiert...</div>
</div>

<script>
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


# ─── DEVIN PAGE HTML ─────────────────────────────────────────────────────────

DEVIN_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OpenDevin — AI Software Engineer</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,monospace;background:#171717;color:#e5e5e5;height:100vh;overflow:hidden}
.app{display:flex;height:100vh}
.sidebar{width:52px;background:#171717;border-right:1px solid #333;display:flex;flex-direction:column;align-items:center;padding:12px 0;flex-shrink:0}
.sidebar-bottom{margin-top:auto}
.sidebar button{background:none;border:none;color:#888;cursor:pointer;padding:8px;border-radius:8px;transition:all .2s}
.sidebar button:hover{background:#262626;color:#e5e5e5}
.main{flex:1;display:flex;flex-direction:column;padding:6px;gap:6px;min-width:0}
.top-row{flex:1;display:flex;gap:6px;min-height:0}
.panel{background:#262626;border:1px solid #404040;border-radius:12px;overflow:hidden;display:flex;flex-direction:column}
.chat-panel{width:35%;min-width:280px;flex-shrink:0}
.editor-panel{flex:1;min-width:0}
.terminal-panel{height:220px;flex-shrink:0}
.panel-header{display:flex;align-items:center;gap:8px;padding:8px 14px;border-bottom:1px solid #404040;background:rgba(38,38,38,.8);font-size:13px;font-weight:500;color:#d4d4d4}
.panel-header svg{width:16px;height:16px;color:#888}
.chat-messages{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:12px}
.msg{max-width:90%;padding:10px 14px;border-radius:10px;font-size:13px;line-height:1.5;white-space:pre-wrap;word-break:break-word}
.msg.assistant{background:#404040;color:#e5e5e5;align-self:flex-start}
.msg.user{background:#2563eb;color:#fff;align-self:flex-end}
.msg.thinking{background:#404040;color:#888;align-self:flex-start}
.chat-input{display:flex;align-items:center;gap:8px;padding:10px;border-top:1px solid #404040}
.chat-input input{flex:1;background:#1a1a1a;border:1px solid #404040;border-radius:8px;padding:8px 12px;color:#e5e5e5;font-size:13px;outline:none}
.chat-input input:focus{border-color:#2563eb}
.chat-input input:disabled{opacity:.5}
.chat-input button{background:none;border:none;color:#888;cursor:pointer;padding:4px;transition:color .2s}
.chat-input button:hover{color:#60a5fa}
.chat-input button:disabled{opacity:.3;cursor:not-allowed}
.tabs{display:flex;border-bottom:1px solid #404040;background:rgba(38,38,38,.8)}
.tab{padding:8px 16px;font-size:13px;color:#888;cursor:pointer;border-bottom:2px solid transparent;display:flex;align-items:center;gap:6px;transition:all .2s}
.tab:hover{color:#d4d4d4}
.tab.active{color:#d4d4d4;border-bottom-color:#3b82f6}
.tab svg{width:15px;height:15px}
.editor-body{display:flex;flex:1;min-height:0}
.file-tree{width:180px;border-right:1px solid #404040;overflow-y:auto;flex-shrink:0;padding-top:4px}
.file-tree-header{display:flex;align-items:center;gap:4px;padding:6px 10px;font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.5px}
.file-item{display:flex;align-items:center;gap:4px;padding:4px 10px;font-size:13px;color:#d4d4d4;cursor:pointer;transition:background .15s}
.file-item:hover{background:rgba(255,255,255,.05)}
.file-item.active{background:rgba(59,130,246,.15);color:#93c5fd}
.file-item svg{width:14px;height:14px;flex-shrink:0}
.code-area{flex:1;display:flex;flex-direction:column;min-width:0}
.code-tab-bar{display:flex;align-items:center;padding:4px 10px;background:#1a1a1a;border-bottom:1px solid #404040}
.code-tab{font-size:12px;color:#d4d4d4;background:#404040;padding:3px 12px;border-radius:4px}
.code-content{flex:1;overflow:auto;padding:12px;font-family:'Fira Code',Consolas,monospace;font-size:13px;background:#0a0a0a}
.code-line{display:flex}
.line-num{color:#555;width:36px;text-align:right;margin-right:16px;user-select:none;flex-shrink:0}
.line-text{color:#d4d4d4;white-space:pre}
.browser-placeholder{flex:1;display:flex;align-items:center;justify-content:center;color:#555;text-align:center;padding:40px}
.browser-placeholder svg{width:48px;height:48px;margin-bottom:12px;opacity:.3}
.term-content{flex:1;overflow-y:auto;padding:10px;font-family:'Fira Code',Consolas,monospace;font-size:13px;background:#0a0a0a}
.term-line{line-height:1.6}
.term-cmd{color:#4ade80}
.term-out{color:#d4d4d4}
.term-err{color:#f87171}
.term-info{color:#facc15}
.term-cursor{display:inline-block;width:8px;height:14px;background:#4ade80;animation:blink 1s step-end infinite;vertical-align:middle;margin-left:2px}
@keyframes blink{50%{opacity:0}}
@keyframes spin{to{transform:rotate(360deg)}}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid #555;border-top-color:#60a5fa;border-radius:50%;animation:spin .6s linear infinite;margin-right:6px;vertical-align:middle}
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;z-index:50}
.modal{background:#262626;border:1px solid #404040;border-radius:12px;padding:24px;width:100%;max-width:420px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.modal h2{font-size:17px;color:#e5e5e5;margin-bottom:16px}
.modal label{display:block;font-size:13px;color:#888;margin-bottom:4px}
.modal select,.modal input[type=password]{width:100%;background:#0a0a0a;border:1px solid #404040;border-radius:8px;padding:8px 12px;color:#e5e5e5;font-size:13px;outline:none;margin-bottom:12px}
.modal select:focus,.modal input[type=password]:focus{border-color:#3b82f6}
.modal .hint{font-size:11px;color:#666;margin-top:-8px;margin-bottom:12px}
.modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}
.modal-actions button{padding:8px 16px;border-radius:8px;font-size:13px;cursor:pointer;transition:all .2s}
.btn-cancel{background:none;border:1px solid #404040;color:#d4d4d4}
.btn-cancel:hover{background:#333}
.btn-save{background:#2563eb;border:none;color:#fff}
.btn-save:hover{background:#1d4ed8}
</style>
</head>
<body>

<div class="app" id="app">
  <div class="sidebar">
    <div class="sidebar-bottom">
      <button onclick="toggleSettings()" title="Settings">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>
      </button>
    </div>
  </div>
  <div class="main">
    <div class="top-row">
      <div class="panel chat-panel">
        <div class="panel-header">
          <span>💬 Chat</span>
          <span id="chatSpinner" style="display:none"><span class="spinner"></span></span>
        </div>
        <div class="chat-messages" id="chatMessages"></div>
        <div class="chat-input">
          <input type="text" id="chatInput" placeholder="Send a message..." onkeydown="if(event.key==='Enter')sendMessage()">
          <button onclick="sendMessage()" id="sendBtn" title="Send">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18"><path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/></svg>
          </button>
        </div>
      </div>
      <div class="panel editor-panel">
        <div class="tabs">
          <div class="tab active" id="tabEditor" onclick="switchTab('editor')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
            Code Editor
          </div>
          <div class="tab" id="tabBrowser" onclick="switchTab('browser')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
            Browser
          </div>
        </div>
        <div id="editorContent" class="editor-body" style="flex:1;min-height:0">
          <div class="file-tree" id="fileTree">
            <div class="file-tree-header">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/></svg>
              workspace
            </div>
          </div>
          <div class="code-area">
            <div class="code-tab-bar"><span class="code-tab" id="codeTabName">welcome</span></div>
            <div class="code-content" id="codeContent">
              <div class="code-line"><span class="line-num">1</span><span class="line-text" style="color:#facc15"># Welcome to OpenDevin!</span></div>
              <div class="code-line"><span class="line-num">2</span><span class="line-text" style="color:#facc15"># Ask me to write some code.</span></div>
            </div>
          </div>
        </div>
        <div id="browserContent" class="browser-placeholder" style="display:none;flex:1">
          <div>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
            <p>Browser preview will appear here</p>
            <p style="font-size:12px;color:#444;margin-top:4px">The agent can browse the web to research and test</p>
          </div>
        </div>
      </div>
    </div>
    <div class="panel terminal-panel">
      <div class="panel-header">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/></svg>
        Terminal
      </div>
      <div class="term-content" id="termContent">
        <div class="term-line term-info">OpenDevin Terminal v0.1.0</div>
        <div class="term-line term-info">Ready. Waiting for commands...</div>
        <div class="term-line term-cmd">$ <span class="term-cursor"></span></div>
      </div>
    </div>
  </div>
</div>

<div class="modal-overlay" id="settingsModal" style="display:none" onclick="if(event.target===this)toggleSettings()">
  <div class="modal">
    <h2>Settings</h2>
    <label>LLM Model</label>
    <select id="modelSelect">
      <option value="openai">GPT-OSS (Free, default)</option>
      <option value="mistral">Mistral (Free)</option>
      <option value="llama">Llama (Free)</option>
      <option value="deepseek">DeepSeek (Free)</option>
    </select>
    <p class="hint">All models are free via Pollinations AI — no API key needed</p>
    <div class="modal-actions">
      <button class="btn-cancel" onclick="toggleSettings()">Cancel</button>
      <button class="btn-save" onclick="saveSettings()">Save</button>
    </div>
  </div>
</div>

<script>
const API_URL="https://text.pollinations.ai/openai/chat/completions";
let model="openai";
let messages=[];
let files={};
let activeFile=null;
let isLoading=false;

const SYSTEM=`You are OpenDevin, an AI software engineer assistant. You help users by writing code, explaining concepts, and solving programming problems.

When the user asks you to write code or create something, respond with:
1. A brief explanation of what you'll do
2. The code in a fenced code block with the filename as a comment on the first line, e.g.:
\`\`\`python
# filename: main.py
print("hello world")
\`\`\`

You can create multiple files by using multiple code blocks. Always include the filename comment.
Keep responses concise and focused on code. You are a coding assistant, not a general chatbot.`;

function addMsg(role,content){
  const d=document.getElementById('chatMessages');
  const m=document.createElement('div');
  m.className='msg '+role;
  m.textContent=content;
  d.appendChild(m);
  d.scrollTop=d.scrollHeight;
}

function setThinking(on){
  document.getElementById('chatSpinner').style.display=on?'inline':'none';
  document.getElementById('chatInput').disabled=on;
  document.getElementById('sendBtn').disabled=on;
  isLoading=on;
  if(on){
    const d=document.getElementById('chatMessages');
    let t=document.getElementById('thinkingMsg');
    if(!t){t=document.createElement('div');t.id='thinkingMsg';t.className='msg thinking';t.innerHTML='<span class="spinner"></span> Thinking...';d.appendChild(t);d.scrollTop=d.scrollHeight}
  } else {
    const t=document.getElementById('thinkingMsg');
    if(t)t.remove();
  }
}

function termLog(lines){
  const tc=document.getElementById('termContent');
  // remove cursor line
  const cursor=tc.querySelector('.term-cmd:last-child');
  if(cursor&&cursor.querySelector('.term-cursor'))cursor.remove();
  lines.forEach(l=>{
    const d=document.createElement('div');
    d.className='term-line term-'+l.type;
    d.textContent=l.text;
    tc.appendChild(d);
  });
  const cl=document.createElement('div');
  cl.className='term-line term-cmd';
  cl.innerHTML='$ <span class="term-cursor"></span>';
  tc.appendChild(cl);
  tc.scrollTop=tc.scrollHeight;
}

function extractCode(text){
  const blocks=[];
  const re=/```(\w+)?\n([\s\S]*?)```/g;
  let m;
  while((m=re.exec(text))!==null){
    const lang=m[1]||'text';
    const code=m[2].trim();
    let fn='file.'+({python:'py',javascript:'js',typescript:'ts',html:'html',css:'css',bash:'sh',sh:'sh'}[lang]||lang);
    const fm=code.match(/^#\s*filename:\s*(.+)/m);
    if(fm)fn=fm[1].trim();
    blocks.push({filename:fn,language:lang,code:code});
  }
  return blocks;
}

function updateFileTree(){
  const ft=document.getElementById('fileTree');
  ft.innerHTML='<div class="file-tree-header"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/></svg> workspace</div>';
  Object.keys(files).forEach(fn=>{
    const d=document.createElement('div');
    d.className='file-item'+(activeFile===fn?' active':'');
    d.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="#60a5fa" stroke-width="2" width="14" height="14"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/></svg> '+fn;
    d.onclick=()=>openFile(fn);
    ft.appendChild(d);
  });
}

function openFile(fn){
  activeFile=fn;
  document.getElementById('codeTabName').textContent=fn;
  const cc=document.getElementById('codeContent');
  const lines=(files[fn]||'').split('\n');
  cc.innerHTML=lines.map((l,i)=>'<div class="code-line"><span class="line-num">'+(i+1)+'</span><span class="line-text">'+escHtml(l)+'</span></div>').join('');
  updateFileTree();
}

function escHtml(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

function switchTab(tab){
  document.getElementById('tabEditor').className='tab'+(tab==='editor'?' active':'');
  document.getElementById('tabBrowser').className='tab'+(tab==='browser'?' active':'');
  document.getElementById('editorContent').style.display=tab==='editor'?'flex':'none';
  document.getElementById('browserContent').style.display=tab==='browser'?'flex':'none';
}

function toggleSettings(){
  const m=document.getElementById('settingsModal');
  m.style.display=m.style.display==='none'?'flex':'none';
  if(m.style.display==='flex'){
    document.getElementById('modelSelect').value=model;
  }
}

function saveSettings(){
  model=document.getElementById('modelSelect').value;
  toggleSettings();
}

async function sendMessage(){
  const inp=document.getElementById('chatInput');
  const text=inp.value.trim();
  if(!text||isLoading)return;
  inp.value='';
  addMsg('user',text);
  messages.push({role:'user',content:text});
  setThinking(true);
  const short=text.length>50?text.slice(0,50)+'...':text;
  termLog([{text:'$ opendevin process "'+short+'"',type:'cmd'},{text:'Thinking...',type:'info'}]);

  try{
    const apiMsgs=[{role:'system',content:SYSTEM},...messages];
    const res=await fetch(API_URL,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:model,messages:apiMsgs,temperature:0.3})});
    if(!res.ok)throw new Error('API error '+res.status+': '+(await res.text()));
    const data=await res.json();
    const reply=data.choices?.[0]?.message?.content||'No response received.';
    messages.push({role:'assistant',content:reply});
    setThinking(false);
    addMsg('assistant',reply);

    const blocks=extractCode(reply);
    if(blocks.length>0){
      blocks.forEach(b=>{files[b.filename]=b.code});
      openFile(blocks[0].filename);
      termLog([{text:'$ opendevin process "'+short+'"',type:'cmd'},{text:'✓ Generated '+blocks.length+' file(s): '+blocks.map(b=>b.filename).join(', '),type:'out'},{text:'Files written to workspace/',type:'info'}]);
    } else {
      termLog([{text:'$ opendevin process "'+short+'"',type:'cmd'},{text:'✓ Response ready',type:'out'}]);
    }
  }catch(err){
    setThinking(false);
    addMsg('assistant','Error: '+err.message+'\n\nThe free API might be rate-limited. Try again in a moment.');
    termLog([{text:'✗ Error: '+err.message,type:'err'}]);
  }
}

// Init
addMsg('assistant','Hi! I\'m OpenDevin, an AI Software Engineer. What would you like to build with me today?\n\nTry asking me to write some code, like:\n- "Create a Python script that generates random passwords"\n- "Write a React component for a todo list"\n- "Build a simple REST API in Node.js"');
</script>
</body>
</html>"""
