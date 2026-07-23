"""Tests für Ordnernamen-Verarbeitung (UTF-7, Parsing, Junk) und Fehlertexte."""
from __future__ import annotations

import imaplib

from app.services.imap_client import (
    Folder,
    _select_name,
    decode_modified_utf7,
    encode_modified_utf7,
    fetch_messages,
    friendly_error,
    list_folders,
)


# ---------------------------------------------------------------------------
# Modified UTF-7
# ---------------------------------------------------------------------------


def test_decode_modified_utf7():
    assert decode_modified_utf7("Entw&APw-rfe") == "Entwürfe"
    assert decode_modified_utf7("Gel&APY-schte Elemente") == "Gelöschte Elemente"
    assert decode_modified_utf7("INBOX") == "INBOX"
    assert decode_modified_utf7("A&-B") == "A&B"  # &- ist ein literales &


def test_encode_modified_utf7_roundtrip():
    for name in ("Entwürfe", "Gelöschte Elemente", "INBOX", "Rechnungen 2026", "A&B"):
        assert decode_modified_utf7(encode_modified_utf7(name)) == name


def test_select_name_quotes_and_encodes():
    assert _select_name("INBOX") == '"INBOX"'
    assert _select_name("Gesendete Objekte") == '"Gesendete Objekte"'
    assert _select_name("Entwürfe") == '"Entw&APw-rfe"'
    assert _select_name('Mit"Quote') == '"Mit\\"Quote"'


# ---------------------------------------------------------------------------
# LIST-Parsing
# ---------------------------------------------------------------------------


class FakeListConn:
    def __init__(self, lines):
        self._lines = lines

    def list(self):
        return "OK", self._lines


def test_list_folders_parses_quoted_names_with_spaces():
    conn = FakeListConn([
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasNoChildren) "/" "Gesendete Objekte"',
        b'(\\HasNoChildren \\Drafts) "/" "Entw&APw-rfe"',
        b'(\\Noselect \\HasChildren) "/" "[Gmail]"',
        b'(\\HasNoChildren) "/" Rechnungen',
    ])
    folders = list_folders(conn)
    by_display = {f.display: f for f in folders}

    assert "Gesendete Objekte" in by_display  # Leerzeichen korrekt
    assert "Entwürfe" in by_display           # UTF-7 dekodiert
    assert by_display["Entwürfe"].raw == "Entw&APw-rfe"
    assert by_display["Entwürfe"].special_junk is True   # \Drafts erkannt
    assert by_display["[Gmail]"].selectable is False     # \Noselect erkannt
    assert "Rechnungen" in by_display                    # Atom ohne Quotes


def test_resolve_folders_skips_junk_by_attribute_and_name(db, monkeypatch):
    from app.models import EmailAccount
    from app.security import encrypt
    from app.services import sync as sync_module

    account = EmailAccount(
        name="F", host="h", username="u", password_enc=encrypt("x"), folders="*",
    )
    db.add(account)
    db.commit()

    conn = FakeListConn([
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasNoChildren) "/" "Rechnungen"',
        b'(\\HasNoChildren \\Drafts) "/" "Entw&APw-rfe"',
        b'(\\HasNoChildren) "/" "Spamverdacht"',
        b'(\\HasNoChildren \\Sent) "/" "Gesendete Objekte"',
    ])
    kept = sync_module._resolve_folders(conn, account)
    assert kept == ["INBOX", "Rechnungen"]


def test_fetch_messages_skips_broken_folder():
    class BrokenSelectConn:
        def select(self, name, readonly=False):
            raise imaplib.IMAP4.error(
                b'EXAMINE command error: BAD [b\'expected end of data\']'
            )

    messages = list(fetch_messages(BrokenSelectConn(), "Entw&APw-rfe"))
    assert messages == []  # übersprungen statt Absturz


# ---------------------------------------------------------------------------
# Freundliche Fehlermeldungen
# ---------------------------------------------------------------------------


def test_friendly_error_auth():
    msg = friendly_error(imaplib.IMAP4.error(b"authentication failed"))
    assert "Anmeldung fehlgeschlagen" in msg
    assert "b'" not in msg  # kein Code-Kauderwelsch


def test_friendly_error_examine():
    msg = friendly_error(imaplib.IMAP4.error("EXAMINE command error: BAD"))
    assert "Ordner" in msg
    assert "BAD" not in msg


def test_friendly_error_fallback_has_no_tech_jargon():
    msg = friendly_error(Exception("б'weird stuff' traceback 0x1f"))
    assert "Protokoll" in msg
    assert "traceback" not in msg.lower() or "Protokoll" in msg


def test_friendly_error_gmail_app_password():
    msg = friendly_error(imaplib.IMAP4.error(
        b"[ALERT] Application-specific password required: "
        b"https://support.google.com/accounts/answer/185833 (Failure)"
    ))
    assert "App-Passwort" in msg
    assert "apppasswords" in msg
    assert "support.google.com" not in msg  # kein Technik-Link-Salat
