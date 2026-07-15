"""Tests für den automatischen Hintergrund-Sync."""
from __future__ import annotations

import threading

from app import autosync


def test_run_loop_exits_when_disabled(monkeypatch):
    """Bei Intervall 0 beendet sich die Schleife sofort (keine Endlosschleife)."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "sync_interval_minutes", 0)
    stop = threading.Event()
    autosync.run_loop(stop)  # darf sofort zurückkehren, ohne zu blockieren


def test_run_loop_stops_on_event(monkeypatch):
    """Ein gesetztes Stop-Event beendet die Schleife vor der ersten Runde."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "sync_interval_minutes", 30)
    called = []
    monkeypatch.setattr(autosync, "_sync_once", lambda: called.append(True))

    stop = threading.Event()
    stop.set()  # sofort beenden
    autosync.run_loop(stop)
    assert called == []


def test_sync_once_runs_all(monkeypatch, db):
    """_sync_once ruft sync_all auf und stürzt ohne Konten nicht ab."""
    autosync._sync_once()  # keine aktiven Konten -> keine Exception