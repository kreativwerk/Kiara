"""Tests für das Sync-Startdatum ("Synchronisieren ab")."""
from __future__ import annotations

from datetime import date

from app.models import EmailAccount
from app.services.imap_client import _imap_date, fetch_messages


def test_imap_date_format():
    assert _imap_date(date(2026, 1, 5)) == "05-Jan-2026"
    assert _imap_date(date(2025, 12, 31)) == "31-Dec-2025"


class RecordingConn:
    def __init__(self):
        self.calls = []

    def select(self, name, readonly=False):
        return "OK", None

    def uid(self, cmd, *args):
        self.calls.append((cmd, args))
        return "OK", [b""]


def test_fetch_messages_uses_since_criteria():
    conn = RecordingConn()
    list(fetch_messages(conn, "INBOX", since_date=date(2026, 1, 1)))
    assert ("search", (None, "SINCE", "01-Jan-2026")) in conn.calls


def test_fetch_messages_defaults_to_all():
    conn = RecordingConn()
    list(fetch_messages(conn, "INBOX"))
    assert ("search", (None, "ALL")) in conn.calls


def test_create_account_with_sync_since(client, db):
    resp = client.post(
        "/accounts",
        data={
            "name": "Mit Startdatum", "provider": "ionos", "host": "",
            "port": "993", "use_ssl": "true", "username": "x@y.de",
            "password": "geheim", "folders": "*", "sync_since": "2026-01-01",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.expire_all()
    account = db.query(EmailAccount).filter_by(name="Mit Startdatum").one()
    assert account.sync_since == date(2026, 1, 1)


def test_edit_account_sync_since(client, db, org_id):
    from app.security import encrypt

    account = EmailAccount(
        org_id=org_id, name="Edit", host="h", username="u",
        password_enc=encrypt("x"),
    )
    db.add(account)
    db.commit()

    resp = client.post(
        f"/accounts/{account.id}/edit",
        data={
            "name": "Edit", "host": "h", "port": "993", "use_ssl": "true",
            "username": "u", "password": "", "folders": "*",
            "sync_since": "2025-06-15", "active": "true",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.expire_all()
    assert db.get(EmailAccount, account.id).sync_since == date(2025, 6, 15)

    # Leeres Feld löscht das Startdatum wieder
    client.post(
        f"/accounts/{account.id}/edit",
        data={
            "name": "Edit", "host": "h", "port": "993", "use_ssl": "true",
            "username": "u", "password": "", "folders": "*",
            "sync_since": "", "active": "true",
        },
    )
    db.expire_all()
    assert db.get(EmailAccount, account.id).sync_since is None
