"""Tests für Parallel-Sync-Schutz, SQLite-WAL und Filter mit leeren Werten."""
from __future__ import annotations

from app.models import EmailAccount
from app.security import encrypt
from app.services import sync as sync_module


def test_sqlite_wal_and_busy_timeout_enabled():
    from app.database import engine

    with engine.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        timeout = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
    assert str(mode).lower() == "wal"
    assert int(timeout) >= 30000


def test_sync_skipped_when_already_running(db):
    account = EmailAccount(
        name="Doppelt",
        host="imap.example.org",
        username="u@example.org",
        password_enc=encrypt("secret"),
    )
    db.add(account)
    db.commit()

    # Simuliert: für dieses Konto läuft bereits ein Sync.
    sync_module._pending_accounts.add(account.id)
    try:
        result = sync_module.sync_account(db, account)
    finally:
        sync_module._pending_accounts.discard(account.id)

    assert "läuft bereits" in result.message
    # Kein Fehler, kein Verbindungsversuch – Konto bleibt unangetastet.
    assert result.ok is True
    assert result.new_emails == 0


def test_attachments_filter_accepts_empty_params(client):
    # Genau die URL, die das Filter-Formular bei leeren Feldern erzeugt:
    resp = client.get("/attachments?account_id=&category=&year=&q=")
    assert resp.status_code == 200
    assert "Belege" in resp.text


def test_attachments_filter_with_values(client):
    resp = client.get("/attachments?account_id=1&category=rechnung&year=2026&q=test")
    assert resp.status_code == 200
