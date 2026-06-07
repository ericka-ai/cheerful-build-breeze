# Exchange Telegram Bot

Ein Telegram-Bot fuer Peer-to-Peer Waehrungstausch mit automatischer
Zahlungserkennung und Gebuehrenberechnung.

## Unterstuetzte Tausch-Typen

| Von         | Nach        | Gebühr |
|-------------|-------------|--------|
| Krypto      | PayPal      | 5%     |
| PayPal      | Krypto      | 5%     |
| Krypto      | Bankkonto   | 3%     |
| Bankkonto   | Krypto      | 3%     |
| PayPal      | Bankkonto   | 2%     |
| Bankkonto   | PayPal      | 2%     |

## Unterstuetzte Kryptowaehrungen

- Bitcoin (BTC)
- Ethereum (ETH)
- Tether USDT (TRC-20)
- Litecoin (LTC)

## Funktionen

- **Automatische Krypto-Zahlungserkennung** via Blockchain-APIs
  (BlockCypher fuer BTC/LTC, Etherscan fuer ETH)
- **Echtzeit-Kurse** ueber CoinGecko (kostenlos, kein API-Key noetig)
- **PayPal Payouts API** fuer automatische Auszahlungen
- **Admin-Dashboard** mit Statistiken, Bestelluebersicht und
  manueller Bestaetigung
- **Gebuehrenberechnung** mit konfigurierbaren Prozentsaetzen
- **Bestellverwaltung** mit SQLite-Datenbank
- **Benutzer-Sperrsystem** fuer Missbrauchsschutz

## Schnellstart

```bash
# 1. Abhaengigkeiten installieren
pip install -r telegram_bot/requirements.txt

# 2. Umgebungsvariablen setzen
export TELEGRAM_BOT_TOKEN="dein-bot-token"
export ADMIN_CHAT_IDS="123456789"  # deine Telegram User-ID

# 3. Bot starten
python -m telegram_bot
```

## Konfiguration (Umgebungsvariablen)

### Pflicht

| Variable              | Beschreibung                              |
|-----------------------|-------------------------------------------|
| `TELEGRAM_BOT_TOKEN`  | Bot-Token von @BotFather                  |
| `ADMIN_CHAT_IDS`      | Komma-getrennte Admin Telegram User-IDs   |

### Krypto-Wallets

| Variable      | Beschreibung                    |
|---------------|---------------------------------|
| `WALLET_BTC`  | Bitcoin Empfangsadresse         |
| `WALLET_ETH`  | Ethereum Empfangsadresse        |
| `WALLET_USDT` | USDT (TRC-20) Empfangsadresse  |
| `WALLET_LTC`  | Litecoin Empfangsadresse        |

### PayPal

| Variable               | Beschreibung                          |
|------------------------|---------------------------------------|
| `PAYPAL_CLIENT_ID`      | PayPal App Client-ID                  |
| `PAYPAL_CLIENT_SECRET`  | PayPal App Secret                     |
| `PAYPAL_MODE`           | `sandbox` oder `live`                 |
| `PAYPAL_EMAIL`          | PayPal E-Mail (fuer Zahlungseingang)  |

### Bankdaten

| Variable       | Beschreibung              |
|---------------|---------------------------|
| `BANK_IBAN`    | IBAN fuer Ueberweisungen  |
| `BANK_BIC`     | BIC/SWIFT                 |
| `BANK_HOLDER`  | Kontoinhaber              |
| `BANK_NAME`    | Bankname                  |

### Blockchain-APIs (optional, fuer Auto-Scan)

| Variable               | Beschreibung                |
|------------------------|-----------------------------|
| `BLOCKCYPHER_API_TOKEN` | BlockCypher API Token       |
| `ETHERSCAN_API_KEY`     | Etherscan API Key           |

### Gebuehren & Limits

| Variable                | Standard | Beschreibung                   |
|------------------------|----------|--------------------------------|
| `FEE_CRYPTO_TO_PAYPAL`  | 5.0      | Gebuehr Krypto->PayPal (%)     |
| `FEE_PAYPAL_TO_CRYPTO`  | 5.0      | Gebuehr PayPal->Krypto (%)     |
| `FEE_CRYPTO_TO_BANK`    | 3.0      | Gebuehr Krypto->Bank (%)       |
| `FEE_BANK_TO_CRYPTO`    | 3.0      | Gebuehr Bank->Krypto (%)       |
| `FEE_PAYPAL_TO_BANK`    | 2.0      | Gebuehr PayPal->Bank (%)       |
| `FEE_BANK_TO_PAYPAL`    | 2.0      | Gebuehr Bank->PayPal (%)       |
| `MIN_AMOUNT_EUR`         | 10.0     | Mindestbetrag (EUR)            |
| `MAX_AMOUNT_EUR`         | 5000.0   | Maximalbetrag (EUR)            |

### Sonstiges

| Variable                | Standard | Beschreibung                        |
|------------------------|----------|-------------------------------------|
| `DATABASE_PATH`         | `exchange_bot.db` | Pfad zur SQLite-Datenbank  |
| `ORDER_EXPIRY_MINUTES`  | 30       | Bestellung laeuft ab nach (Min.)    |
| `PAYMENT_SCAN_INTERVAL` | 30       | Blockchain-Scan Intervall (Sek.)    |

## Bot-Befehle

### Nutzer-Befehle

| Befehl               | Beschreibung                    |
|----------------------|---------------------------------|
| `/start`             | Hauptmenue anzeigen             |
| `/status <ID>`       | Bestellstatus pruefen           |
| `/cancel <ID>`       | Bestellung stornieren           |

### Admin-Befehle

| Befehl                  | Beschreibung                      |
|------------------------|-----------------------------------|
| `/admin`               | Admin-Dashboard                   |
| `/confirm <ID>`        | Zahlung bestaetigen & auszahlen   |
| `/complete <ID>`       | Bestellung manuell abschliessen   |
| `/blockuser <user_id>` | Nutzer sperren                    |
| `/unblockuser <user_id>` | Nutzer entsperren               |

## Architektur

```
telegram_bot/
├── bot.py              # Haupteinstiegspunkt
├── __main__.py         # python -m telegram_bot
├── config.py           # Konfiguration (Env-Vars)
├── handlers/
│   ├── start.py        # /start, Hauptmenue, Hilfe
│   ├── exchange.py     # Tausch-Konversationsfluss
│   └── admin.py        # Admin-Befehle & Dashboard
├── models/
│   └── order.py        # Bestellungen & Nutzer (SQLite)
├── services/
│   ├── crypto.py       # Kurse & Blockchain-Monitoring
│   ├── fees.py         # Gebuehrenberechnung
│   ├── payments.py     # PayPal & Bank-Auszahlungen
│   └── scanner.py      # Hintergrund-Zahlungsscanner
└── requirements.txt
```

## Ablauf einer Bestellung

1. Nutzer waehlt Tausch-Typ (z.B. Krypto -> PayPal)
2. Nutzer waehlt Kryptowaehrung (falls zutreffend)
3. Nutzer gibt Betrag in EUR ein
4. Nutzer gibt Auszahlungsdaten ein (PayPal-Email, IBAN, Wallet)
5. Bot zeigt Zusammenfassung mit Gebuehren
6. Nutzer bestaetigt
7. Bot zeigt Zahlungsanweisungen
8. Hintergrund-Scanner erkennt Krypto-Eingang automatisch
9. Admin bestaetigt Auszahlung -> Kunde erhaelt Geld

## Sicherheitshinweise

- Dieser Bot verarbeitet echtes Geld. Betreibe ihn nur auf einem
  sicheren Server.
- Alle sensiblen Daten (Tokens, API-Keys, Wallet-Adressen) werden
  ausschliesslich ueber Umgebungsvariablen konfiguriert.
- Pruefe die rechtlichen Anforderungen in deinem Land (KYC/AML,
  BaFin-Lizenz in Deutschland).
