"""Automatischer Hintergrund-Sync: hält das Archiv ohne Knopfdruck aktuell.

Ein Daemon-Thread synchronisiert alle aktiven Konten in festem Abstand
(``KIARA_SYNC_INTERVAL_MINUTES``, Standard 30, 0 = aus). Große Postfächer
werden so beim Erstimport automatisch Runde für Runde abgearbeitet, bis
alles da ist – danach holt jede Runde nur noch Neues.

Der Doppelstart-Schutz in ``sync_account`` sorgt dafür, dass sich der
Auto-Sync und manuelle Sync-Klicks nicht in die Quere kommen.
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("kiara.autosync")

# Erste Runde kurz nach dem Start (Server erst hochfahren lassen).
INITIAL_DELAY_SECONDS = 60


def run_loop(stop: threading.Event) -> None:
    """Sync-Schleife; läuft bis ``stop`` gesetzt wird."""
    from .config import get_settings

    interval_minutes = get_settings().sync_interval_minutes
    if interval_minutes <= 0:
        log.info("Auto-Sync deaktiviert (KIARA_SYNC_INTERVAL_MINUTES=0).")
        return

    if stop.wait(INITIAL_DELAY_SECONDS):
        return
    while not stop.is_set():
        try:
            _sync_once()
        except Exception:  # noqa: BLE001 - Schleife darf nie sterben
            log.exception("Auto-Sync-Runde fehlgeschlagen")
        if stop.wait(interval_minutes * 60):
            return


def _sync_once() -> None:
    from .database import SessionLocal
    from .services import matching
    from .services.sync import sync_all

    with SessionLocal() as db:
        results = sync_all(db)
        if results:
            matching.reconcile(db)
        new_attachments = sum(r.new_attachments for r in results)
        if new_attachments:
            log.info("Auto-Sync: %s neue Belege archiviert.", new_attachments)


def start(stop: threading.Event) -> threading.Thread:
    thread = threading.Thread(
        target=run_loop, args=(stop,), daemon=True, name="kiara-autosync"
    )
    thread.start()
    return thread
