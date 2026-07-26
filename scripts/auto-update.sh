#!/usr/bin/env bash
# Kiara Auto-Update & Selbstheilung: prüft jede Minute, ob es eine neue
# offizielle Version (main) gibt, spielt sie automatisch ein UND sorgt
# dafür, dass die Container laufen (startet Gestopptes neu, räumt bei
# voller Festplatte auf).
#
# Einmalige Einrichtung (als root, im Kiara-Verzeichnis):
#   chmod +x scripts/auto-update.sh
#   (crontab -l 2>/dev/null; echo "* * * * * /root/Kiara/scripts/auto-update.sh >> /var/log/kiara-update.log 2>&1") | crontab -
#
# Daten (Belege, Datenbank, Schlüssel) liegen im Docker-Volume und
# bleiben bei jedem Update unangetastet.
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="/tmp/kiara-update.lock"

# Nie zwei Läufe gleichzeitig.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    exit 0
fi

cd "$REPO_DIR"

# --- Selbstheilung 1: volle Festplatte -------------------------------------
# Ab 85% Belegung alte Docker-Build-Reste entfernen. Die Volumes mit den
# Kiara-Daten werden dabei NIE angetastet (kein "prune --volumes"!).
DISK_USE="$(df --output=pcent / 2>/dev/null | tail -1 | tr -dc '0-9')"
if [ "${DISK_USE:-0}" -ge 85 ]; then
    echo "[$(date '+%F %T')] Festplatte ${DISK_USE}% voll – räume Docker-Build-Cache auf."
    docker builder prune -af >/dev/null 2>&1 || true
    docker image prune -af >/dev/null 2>&1 || true
    docker container prune -f >/dev/null 2>&1 || true
    echo "[$(date '+%F %T')] Aufgeräumt, Belegung jetzt: $(df -h / | tail -1 | awk '{print $5}')."
fi

# --- Selbstheilung 2: gestoppte Container ----------------------------------
# "up -d" ohne Build ist ein No-Op, wenn schon alles läuft – startet aber
# abgestürzte/gestoppte Container neu (z.B. nach einem Server-Neustart).
if ! docker compose up -d --no-build >/dev/null 2>&1; then
    echo "[$(date '+%F %T')] Start ohne Build fehlgeschlagen – versuche mit Build."
    docker compose up -d || true
fi

# --- Update auf die neueste Version ----------------------------------------
if ! git fetch origin main --quiet; then
    echo "[$(date '+%F %T')] git fetch fehlgeschlagen (Netzwerk?) – Container laufen weiter."
    exit 0
fi

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse origin/main)"

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0  # bereits aktuell
fi

echo "[$(date '+%F %T')] Neue Version gefunden: ${LOCAL:0:7} -> ${REMOTE:0:7}"
git checkout -B main origin/main --quiet
if docker compose up -d --build; then
    docker image prune -f >/dev/null 2>&1 || true
    docker builder prune -f --keep-storage=10GB >/dev/null 2>&1 || true
    echo "[$(date '+%F %T')] Update eingespielt (${REMOTE:0:7})."
else
    echo "[$(date '+%F %T')] FEHLER: Build/Start fehlgeschlagen – alte Version läuft weiter."
fi
