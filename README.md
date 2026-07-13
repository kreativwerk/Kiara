# Kiara – Belegarchiv & Buchhaltungs-Gegenkontrolle

Kiara bindet mehrere E-Mail-Postfächer per IMAP an (z. B. **IONOS**, **GMX**,
WEB.DE, Gmail, Outlook), lädt automatisch **alle Anhänge** herunter, sortiert
sie einsortiert nach **Konto / Jahr / Monat** ins Dateisystem und legt eine
durchsuchbare Übersicht an – ideal für die Buchhaltung.

Als **Gegenkontrolle** kannst du deinen **Kontoauszug** hochladen (CSV,
CAMT.053/XML oder MT940). Kiara gleicht die Beträge automatisch mit den
erkannten Rechnungsbelegen ab und zeigt dir, welche Zahlungen einen Beleg
haben – und welche noch fehlen.

## Funktionen

- 📥 **Mehrere IMAP-Konten** mit Voreinstellungen für IONOS & GMX
- 🔒 **Verschlüsselte** Speicherung der Postfach-Passwörter (Fernet)
- 🗂️ Anhänge **dedupliziert** (SHA-256) und **sortiert** abgelegt
- 🏷️ **Automatische Kategorisierung** (Rechnung, Beleg, Gutschrift, Mahnung, …)
- 💶 **Betragserkennung** aus PDF-Rechnungen (pdfplumber)
- 🏦 **Kontoauszug-Import**: CSV (dt. Banken), CAMT.053, MT940
- ✅ **Gegenkontrolle**: automatischer Abgleich Beleg ↔ Banktransaktion
- ☁️ **Optionale Google-Drive-Spiegelung** (unterwegs alle Belege dabei)
- 🌐 **Web-Oberfläche** + **JSON-API** + **CLI** (für Cron)

## Schnellstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# optional: Konfiguration anpassen
cp .env.example .env

# Webserver starten
python run.py
# -> http://127.0.0.1:8000
```

Beim ersten Start werden Datenbank (`data/kiara.sqlite`) und Verzeichnisse
automatisch angelegt. Der Verschlüsselungsschlüssel wird – falls nicht per
`KIARA_SECRET_KEY` gesetzt – einmalig in `data/.kiara_key` erzeugt.

## Konto anbinden

1. In der Weboberfläche auf **Konten → Neues Konto anbinden**.
2. Anbieter wählen (IONOS/GMX füllen Server & Port automatisch vor).
3. E-Mail-Adresse als Benutzername und das Postfach-Passwort eingeben.
4. **Testen** prüft die Verbindung, **Sync** holt die Anhänge.

> Hinweis: Bei GMX und IONOS muss der **IMAP-Zugriff** ggf. in den
> Kontoeinstellungen des Anbieters aktiviert sein.

Presets:

| Anbieter | IMAP-Server            | Port |
|----------|------------------------|------|
| IONOS    | `imap.ionos.de`        | 993  |
| GMX      | `imap.gmx.net`         | 993  |
| WEB.DE   | `imap.web.de`          | 993  |
| Gmail    | `imap.gmail.com`       | 993  |
| Outlook  | `outlook.office365.com`| 993  |

## Gegenkontrolle

Unter **Gegenkontrolle** den Kontoauszug hochladen. Kiara importiert die
Transaktionen und ordnet automatisch passende Belege zu (Abgleich über Betrag
und Datum, plus Namensabgleich). Vorschläge lassen sich **bestätigen** oder
**lösen**.

## Google Drive (optional)

Kiara kann das Belegarchiv **zusätzlich nach Google Drive spiegeln** – gleiche
Ordnerstruktur (Konto/Jahr/Monat). So hast du alle Belege auch unterwegs in der
Drive-App dabei. Die lokalen Dateien bleiben die Quelle der Wahrheit; Drive ist
ein zuschaltbarer Spiegel (An/Aus-Schalter unter **Einstellungen**).

Einrichtung (einmalig):

1. Google-Bibliotheken installieren (in `requirements.txt` enthalten):
   `pip install google-api-python-client google-auth-oauthlib`
2. In der [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
   ein Projekt anlegen, die **Google Drive API** aktivieren und eine
   **OAuth-Client-ID** vom Typ „Webanwendung" erstellen.
3. Als autorisierten Redirect-URI eintragen:
   `http://127.0.0.1:8000/settings/drive/callback`
4. Die `client_secret*.json` unter **Einstellungen → OAuth-Zugangsdaten hochladen**
   hochladen, dann **Mit Google verbinden** und die Spiegelung aktivieren.

Kiara verwendet den minimalen Scope `drive.file` – es sieht und verwaltet nur die
von ihm selbst erstellten Dateien, nicht dein übriges Google Drive. Das
OAuth-Token wird verschlüsselt gespeichert.

> Ohne diese Einrichtung läuft Kiara unverändert weiter – die Spiegelung ist
> rein optional.

## Speicherstruktur

```
data/
├── kiara.sqlite                 # Metadaten
├── attachments/
│   └── <konto>/<jahr>/<monat>/  # sortierte Belege
│       └── <hash>_<datei>
├── statements/                  # hochgeladene Kontoauszüge
├── google_client_secret.json    # optional: Google-OAuth-Zugangsdaten
└── .kiara_key                   # Verschlüsselungsschlüssel
```

Die Google-Drive-Spiegelung nutzt dieselbe `<konto>/<jahr>/<monat>`-Struktur
unter einem Wurzelordner „Kiara" in deinem Drive.

## CLI (für Cron)

```bash
python -m app.cli sync         # alle aktiven Konten synchronisieren
python -m app.cli reconcile    # Gegenkontrolle neu berechnen
python -m app.cli add-account --name "IONOS" --provider ionos \
    --username konto@example.de --password '***'
```

Beispiel-Cronjob (stündlich):

```
0 * * * * cd /pfad/zu/Kiara && .venv/bin/python -m app.cli sync
```

## JSON-API (Auszug)

| Methode | Pfad                        | Zweck                        |
|---------|-----------------------------|------------------------------|
| GET     | `/api/stats`                | Kennzahlen                   |
| GET     | `/api/accounts`             | Konten auflisten             |
| POST    | `/api/accounts`             | Konto anlegen                |
| POST    | `/api/accounts/{id}/sync`   | Konto synchronisieren        |
| POST    | `/api/sync`                 | Alle Konten synchronisieren  |
| POST    | `/api/reconcile`            | Gegenkontrolle berechnen     |
| GET     | `/api/attachments`          | Belege auflisten/filtern     |

Interaktive Doku: `http://127.0.0.1:8000/docs`

## Tests

```bash
pip install -r requirements.txt
pytest -q
```

## Technik

FastAPI · SQLAlchemy 2 · SQLite · Jinja2 · cryptography (Fernet) · pdfplumber

## Sicherheit & Datenschutz

- Alle Daten bleiben **lokal** auf deinem System.
- Postfach-Passwörter werden verschlüsselt gespeichert; der Schlüssel liegt in
  `data/.kiara_key` (nicht ins Git einchecken – steht in `.gitignore`).
- Für den Produktivbetrieb hinter einem Reverse-Proxy sollte zusätzlich eine
  Zugriffs-Authentifizierung vorgeschaltet werden.
