# German Rail Pass Ticket Generator

Web-App zum Generieren von Deutsche Bahn German Rail Pass Online-Tickets als PDF.

## Features

- 1:1 PDF Layout wie Original
- Dynamische Wasserzeichen mit Passagier-Name, Geburtsdatum, Ticket-ID
- Dynamische Ticket-Nummer mit Spiegeleffekt
- UIC 918.3 Aztec Barcode (dynamisch generiert aus Ticketdaten)
- Web-Formular zum einfachen Erstellen

## Installation

```bash
pip install -r requirements.txt
# oder
pip install .
```

## Starten

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Dann im Browser: `http://localhost:8000`

## Konfigurierbare Felder

- Passagier Name
- Geburtsdatum
- Gueltigkeit (Start/Ende)
- Ticket-ID
- Auftragsnummer
- Klasse (1/2)
- Preis
- Zahlungsmethode

## Technologie

- **Backend:** FastAPI + Uvicorn
- **PDF:** PyMuPDF (fitz)
- **Bilder:** Pillow, NumPy, OpenCV
- **Barcode:** aztec_code_generator (UIC 918.3)

## Dateien

```
ticket_webapp/
  app.py           # Hauptanwendung (Backend + Frontend)
  pyproject.toml   # Dependencies
  assets/          # Bilder (DB Logo, Wellenlinien, Icons)
```
