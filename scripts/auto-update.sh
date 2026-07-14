#!/usr/bin/env bash
# Kiara Auto-Update: prüft, ob es eine neue offizielle Version (main) gibt,
# und spielt sie automatisch ein. Gedacht für einen Cron-Job auf dem Server.
#
# Einmalige Einrichtung (als root, im Kiara-Verzeichnis):
#   chmod +x scripts/auto-update.sh
#   (crontab -l 2>/dev/null; echo "*/5 * * * * /root/Kiara/scripts/auto-update.sh >> /var/log/kiara-update.log 2>&1") | crontab -
#
# Danach landet jede gemergte Änderung binnen ~5 Minuten live.
# Daten (Belege, Datenbank, Schlüssel) liegen im Docker-Volume und
# bleiben bei jedem Update unangetastet.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="/tmp/kiara-update.lock"

# Nie zwei Updates gleichzeitig laufen lassen.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    exit 0
fi

cd "$REPO_DIR"
git fetch origin main --quiet

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse origin/main)"

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0  # bereits aktuell
fi

echo "[$(date '+%F %T')] Neue Version gefunden: ${LOCAL:0:7} -> ${REMOTE:0:7}"
git checkout -B main origin/main --quiet
docker compose up -d --build
docker image prune -f >/dev/null 2>&1 || true
echo "[$(date '+%F %T')] Update eingespielt (${REMOTE:0:7})."
