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
- 🔍 **Smarte Suche**: tippfehlertolerant, Volltext über PDF-Inhalte,
  Betragssuche („119,00"), Zeitraum-Erkennung („juni 2026")
- 📖 **OCR-Texterkennung**: auch gescannte Belege und Foto-Anhänge
  (JPG/PNG/HEIC) werden durchsuchbar, Beträge werden erkannt
- ✅ **Gegenkontrolle**: automatischer Abgleich Beleg ↔ Banktransaktion
- ☁️ **Optionale Google-Drive-Spiegelung** (unterwegs alle Belege dabei)
- 🔐 **Login-Schutz**: Passwort beim ersten Start festlegen, Session-Cookie
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

Beim **ersten Aufruf im Browser** legst du ein App-Passwort fest (mind.
8 Zeichen). Danach sind alle Seiten und die JSON-API nur noch nach Anmeldung
erreichbar; die Session hält 7 Tage. Öffentlich bleibt nur `/health`.

## Online betreiben – immer & mobil erreichbar (empfohlen)

Damit Kiara unabhängig von euren Rechnern läuft und auch **vom Handy**
erreichbar ist, betreibt man es auf einem kleinen Server (z. B. Hetzner-VPS,
~5 €/Monat, Standort Deutschland). Docker-Setup mit automatischem HTTPS ist
enthalten:

```bash
# Auf dem Server (Ubuntu, Docker installiert):
git clone https://github.com/kreativwerk/Kiara.git && cd Kiara
echo "KIARA_DOMAIN=kiara.deine-domain.de" > .env
docker compose up -d
```

Schritt für Schritt von null:

1. **Server mieten**: [Hetzner Cloud](https://www.hetzner.com/cloud) → Projekt →
   Server erstellen (kleinstes Modell reicht, Ubuntu 24.04, Standort DE).
2. **Docker installieren**: `curl -fsSL https://get.docker.com | sh`
3. **Domain zeigen lassen**: Beim Domain-Anbieter einen **A-Record** auf die
   Server-IP setzen (z. B. `kiara.deine-domain.de`).
4. Die drei Befehle oben ausführen. Caddy holt automatisch ein
   Let's-Encrypt-Zertifikat → `https://kiara.deine-domain.de` läuft.
5. Im Browser das App-Passwort festlegen – fertig. Am Handy: Seite öffnen und
   „Zum Home-Bildschirm hinzufügen" → fühlt sich wie eine App an.

### Automatische Updates

Einmalig auf dem Server einrichten, danach spielt sich jede neue offizielle
Version (Merge auf `main`) binnen ~5 Minuten selbst ein:

```bash
cd Kiara
chmod +x scripts/auto-update.sh
(crontab -l 2>/dev/null; echo "*/5 * * * * /root/Kiara/scripts/auto-update.sh >> /var/log/kiara-update.log 2>&1") | crontab -
```

Protokoll der Updates: `/var/log/kiara-update.log`. Daten bleiben bei jedem
Update erhalten. Manuelles Update jederzeit: `git pull && docker compose up -d --build`.

Alle Daten (Datenbank, Belege, Schlüssel) liegen im Docker-Volume
`kiara-data`. Backup z. B. per
`docker run --rm -v kiara_kiara-data:/data -v $(pwd):/backup alpine tar czf /backup/kiara-backup.tar.gz /data`.

Sicherheit im Internetbetrieb: Login-Pflicht mit **Rate-Limit** (max. 5
Fehlversuche pro IP in 5 Minuten), HTTPS-only-Cookies, Passwörter/Tokens
verschlüsselt.

## Gemeinsam nutzen im Heimnetz (z. B. zweites MacBook)

Kiara muss nur auf **einem** Rechner laufen – weitere Personen greifen einfach
per Browser darauf zu (gemeinsames Archiv, gemeinsame Datenbank):

1. In der `.env` auf dem Rechner, der Kiara ausführt: `KIARA_HOST=0.0.0.0`
2. Kiara neu starten (`python run.py`). macOS fragt beim ersten Mal, ob
   eingehende Verbindungen erlaubt werden sollen → **Erlauben**.
3. Auf dem anderen Rechner im selben WLAN öffnen:
   `http://<Rechnername>.local:8000` (den Namen zeigt macOS unter
   Systemeinstellungen → Allgemein → Info, z. B. `MacBook-Pro.local`).
4. Mit demselben Kiara-Passwort anmelden – beide können parallel arbeiten.

Der Rechner mit Kiara muss dafür an und wach sein (macOS: Ruhezustand
verhindern oder `caffeinate -s python run.py`).

## Konto anbinden

1. In der Weboberfläche auf **Konten → Neues Konto anbinden**.
2. Anbieter wählen (IONOS/GMX füllen Server & Port automatisch vor).
3. E-Mail-Adresse als Benutzername und das Postfach-Passwort eingeben.
4. **Testen** prüft die Verbindung, **Sync** holt die Anhänge.

> Hinweis: Bei GMX und IONOS muss der **IMAP-Zugriff** ggf. in den
> Kontoeinstellungen des Anbieters aktiviert sein.

Das Ordner-Feld steuert, was durchsucht wird: `*` (Standard) heißt **alle
Ordner** außer Spam/Papierkorb/Entwürfe/Gesendet – so werden auch Belege aus
Unterordnern wie „Rechnungen" gefunden. Alternativ eine kommagetrennte Liste
(z. B. `INBOX, Rechnungen`). Der Sync läuft **im Hintergrund**; der Stand
erscheint direkt beim Konto. Große Postfächer werden chronologisch abgearbeitet
– der Sync merkt sich seinen Fortschritt und setzt beim nächsten Lauf fort.
Konten lassen sich über **Bearbeiten** anpassen (Passwort, Ordner, aktiv/inaktiv).

Presets:

| Anbieter | IMAP-Server            | Port |
|----------|------------------------|------|
| IONOS    | `imap.ionos.de`        | 993  |
| GMX      | `imap.gmx.net`         | 993  |
| WEB.DE   | `imap.web.de`          | 993  |
| Gmail    | `imap.gmail.com`       | 993  |
| Outlook  | `outlook.office365.com`| 993  |

## Suche

Das Suchfeld oben rechts (oder `/search`) durchsucht Dateinamen, Betreff,
Absender, Kategorie **und den Textinhalt der PDFs**:

- **Tippfehler-tolerant**: „rechnng telekom" findet die Telekom-Rechnung
- **Umlaute egal**: „tuv" findet den TÜV-Bericht
- **Beträge**: „119,00" oder „119" trifft den erkannten Belegbetrag
- **Zeiträume**: „2026" filtert aufs Jahr, „juni" auf den Monat –
  kombinierbar: „werkstatt juni 2026"

Der PDF-Text wird beim Sync automatisch erfasst. Belege aus der Zeit davor
lassen sich nachindexieren: `python -m app.cli index`

### OCR für Scans & Fotos

Gescannte PDFs (ohne echten Text) und Bild-Anhänge (JPG, PNG, HEIC, …)
werden per **Tesseract-OCR** gelesen – so tauchen auch abfotografierte
Kassenbons in der Suche auf. Im **Docker-Setup ist OCR bereits enthalten**;
bei manueller Installation:

```bash
# Linux:  apt install tesseract-ocr tesseract-ocr-deu
# macOS:  brew install tesseract tesseract-lang
```

Ohne Tesseract läuft Kiara normal weiter, nur ohne Texterkennung für Scans
(Status siehe Seite „Einstellungen"). Sprache per `KIARA_OCR_LANG`
(Standard `deu+eng`). Bestandsbelege: `python -m app.cli index`.

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
- Die Oberfläche und die API sind durch ein **App-Passwort** geschützt
  (PBKDF2-gehasht, Session über verschlüsseltes HTTP-only-Cookie).
- Postfach-Passwörter und das Google-OAuth-Token werden verschlüsselt
  gespeichert; der Schlüssel liegt in `data/.kiara_key` (nicht ins Git
  einchecken – steht in `.gitignore`).
- Für den Betrieb über das Internet zusätzlich HTTPS verwenden (z. B. über
  einen Reverse-Proxy wie Caddy oder nginx).
