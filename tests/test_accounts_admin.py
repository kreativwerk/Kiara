"""Tests für Ordner-Auflösung, Fehlertexte, Konto-Bearbeiten und Hintergrund-Sync."""
from __future__ import annotations

import imaplib

from app.services.imap_client import error_text
from app.services.sync import filter_sync_folders


def test_filter_sync_folders_removes_junk():
    folders = ["INBOX", "Rechnungen", "Spam", "Papierkorb", "Gesendete Objekte", "Entwürfe", "Lieferanten"]
    assert filter_sync_folders(folders) == ["INBOX", "Rechnungen", "Lieferanten"]


def test_filter_sync_folders_fallback_inbox():
    assert filter_sync_folders(["Spam", "Trash"]) == ["INBOX"]


def test_error_text_decodes_bytes():
    exc = imaplib.IMAP4.error(b"authentication failed")
    assert error_text(exc) == "authentication failed"


def test_error_text_strips_bytes_repr():
    assert error_text(Exception("b'LOGIN failed'")) == "LOGIN failed"
    assert error_text(Exception("normaler Text")) == "normaler Text"


def _create_account(client) -> int:
    resp = client.post(
        "/api/accounts",
        json={
            "name": "Test IONOS",
            "provider": "ionos",
            "username": "info@example.de",
            "password": "geheim123",
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_edit_account(client):
    account_id = _create_account(client)

    resp = client.get(f"/accounts/{account_id}/edit")
    assert resp.status_code == 200
    assert "info@example.de" in resp.text

    resp = client.post(
        f"/accounts/{account_id}/edit",
        data={
            "name": "Test IONOS",
            "host": "imap.ionos.de",
            "port": "993",
            "use_ssl": "true",
            "username": "info@example.de",
            "password": "",  # leer = Passwort unverändert
            "folders": "*",
            "active": "true",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    listing = client.get("/api/accounts").json()
    assert listing[0]["folders"] == "*"
    assert listing[0]["active"] is True


def test_sync_runs_in_background(client, monkeypatch):
    account_id = _create_account(client)

    calls: list[int] = []
    monkeypatch.setattr("app.routers.web._run_sync_account", lambda i: calls.append(i))

    resp = client.post(f"/accounts/{account_id}/sync", follow_redirects=False)
    assert resp.status_code == 303
    assert "gestartet" in resp.headers["location"]
    # TestClient führt Hintergrund-Aufgaben nach der Antwort aus.
    assert calls == [account_id]


def test_sync_all_runs_in_background(client, monkeypatch):
    called: list[bool] = []
    monkeypatch.setattr("app.routers.web._run_sync_all", lambda org_id: called.append(True))

    resp = client.post("/sync", follow_redirects=False)
    assert resp.status_code == 303
    assert called == [True]
