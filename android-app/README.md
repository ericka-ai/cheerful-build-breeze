# DB Tickets - Android App

Native Android-App zum Erstellen von DB Tickets (German Rail Pass, Eurail Global Pass, Deutschlandticket, DB Sparpreis).

## Features

- **Startbildschirm** mit Ticket-Typ-Auswahl:
  - German Rail Pass (Konsekutiv/Flexi)
  - Eurail Global Pass
  - Deutschlandticket
  - DB Sparpreis
- **Formular** mit Nachname und Auftragsnummer
- **Server-Integration** mit dem FastAPI-Backend (`/api/generate`)
- **Echte Tickets** werden vom Server geladen (Auftragsnummer + Nachname)
- **Bottom-Navigation** mit Reisen, Buchen, Profil
- **Server-URL Einstellung** im Profil-Tab konfigurierbar

## Voraussetzungen

- Android 7.0+ (API Level 24)
- Laufender FastAPI-Backend-Server (ticket_webapp)

## APK installieren

1. `DBTickets-debug.apk` auf das Android-Geraet uebertragen
2. In den Einstellungen "Installation aus unbekannten Quellen" erlauben
3. APK oeffnen und installieren

## Server einrichten

Standard Server-URL: `https://cheerful-build-breeze-8.onrender.com`

1. App starten
2. Im Tab "Profil" die Server-URL pruefen/aendern
3. Speichern

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
      MainActivity.kt          # Hauptaktivitaet mit Navigation
      BuchenFragment.kt        # Verbindungssuche
      ReisenFragment.kt        # Ticket-Liste
      ProfilFragment.kt        # Profil + Server-Einstellungen
      Ticket.kt                # Datenmodell
      TicketStore.kt           # Lokaler Ticket-Speicher
      TicketDisplayActivity.kt # Ticket-Detailansicht
      TicketApiClient.kt       # HTTP-Client fuer Server-API
      ServerConfig.kt          # Server-URL Verwaltung
    res/
      layout/                  # XML Layouts
      values/                  # Strings, Colors, Themes
```

## API Endpoint

Die App nutzt `POST /api/generate` mit folgenden Feldern:
- `auftragsnummer` (Pflicht)
- `nachname` (Pflicht)

Response (JSON):
```json
{
  "auftragsnummer": "1234567890123",
  "nachname": "Mustermann",
  "ticket_id": "1234567",
  "klasse": "2. Klasse",
  "preis": "452,00\u20ac",
  "product": "German Rail Pass (Konsekutiv)",
  "gueltig_von": "23.05.2026",
  "gueltig_bis": "06.06.2026",
  "status": "G\u00fcltig"
}
```
