# DB Tickets - Android App

Native Android-App zum Erstellen von DB Tickets (German Rail Pass, Eurail Global Pass, Deutschlandticket, DB Sparpreis).

## Features

- **Startbildschirm** mit Ticket-Typ-Auswahl:
  - German Rail Pass (Konsekutiv/Flexi)
  - Eurail Global Pass
  - Deutschlandticket
  - DB Sparpreis
- **Formular** mit Nachname, Vorname, Geburtsdatum, Klasse, Passagier-Typ
- **Dynamische Felder** je nach Ticket-Typ (Reisetage, Stationen, Zugtyp)
- **Server-Integration** mit dem FastAPI-Backend (`/api/generate`)
- **Auftragsnummer** wird automatisch generiert

## Voraussetzungen

- Android 7.0+ (API Level 24)
- Laufender FastAPI-Backend-Server (ticket_webapp)

## APK installieren

1. `DBTickets-debug.apk` auf das Android-Geraet uebertragen
2. In den Einstellungen "Installation aus unbekannten Quellen" erlauben
3. APK oeffnen und installieren

## Server einrichten

1. App starten
2. Zahnrad-Icon oben rechts antippen → Einstellungen
3. Server-URL eingeben (z.B. `https://dein-server.onrender.com`)
4. Speichern

## Entwicklung

### Build-Voraussetzungen

- JDK 17
- Android SDK (API 34, Build Tools 34.0.0)

### APK bauen

```bash
cd android-app
export ANDROID_HOME=/path/to/android-sdk
./gradlew assembleDebug
```

Die APK befindet sich dann unter:
`app/build/outputs/apk/debug/app-debug.apk`

## Architektur

```
android-app/
  app/src/main/
    java/com/dbtickets/app/
      MainActivity.kt          # Startbildschirm mit Ticket-Buttons
      TicketFormActivity.kt     # Formular (Name, Geburtsdatum, etc.)
      TicketResultActivity.kt   # Ergebnis mit Auftragsnummer
      SettingsActivity.kt       # Server-URL Einstellungen
    res/
      layout/                   # XML Layouts
      values/                   # Strings, Colors, Themes
```

## API Endpoint

Die App nutzt `POST /api/generate` mit folgenden Feldern:
- `nachname`, `vorname`, `geburtsdatum` (Pflicht)
- `klasse`, `passagier_typ`, `product`, `tage`
- `gueltig_von`, `gueltig_bis`
- `von`, `nach`, `zug_typ`, `zug_nummer` (fuer Sparpreis)

Response (JSON):
```json
{
  "auftragsnummer": "1234567890123",
  "ticket_id": "1234567",
  "preis": "452,00€",
  "product": "grp_consecutive",
  "gueltig_von": "23.05.2026",
  "gueltig_bis": "06.06.2026"
}
```
