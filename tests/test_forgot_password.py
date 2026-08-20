"""Tests: 'Passwort vergessen' im Anmeldebereich (E-Mail-Link + Token)."""
from __future__ import annotations

import re
import time

from tests.conftest import TEST_EMAIL, TEST_PASSWORD

from app import auth, settings_store as store
from app.models import EmailAccount, User
from app.security import encrypt
from app.services import mailer


# ---------------------------------------------------------------------------
# Token-Logik
# ---------------------------------------------------------------------------


def _owner(db) -> User:
    return db.query(User).filter(User.email == TEST_EMAIL).one()


def test_reset_token_roundtrip(client, db):
    user = _owner(db)
    token = auth.create_reset_token(user)
    assert auth.verify_reset_token(db, token).id == user.id


def test_reset_token_invalid_and_expired(client, db):
    user = _owner(db)
    assert auth.verify_reset_token(db, "quatsch") is None
    # Session-Token ist KEIN Zurücksetz-Token.
    assert auth.verify_reset_token(db, auth.create_session_token(user.id)) is None
    # Abgelaufen:
    old = auth.RESET_TOKEN_MAX_AGE
    auth.RESET_TOKEN_MAX_AGE = -1
    try:
        expired = auth.create_reset_token(user)
    finally:
        auth.RESET_TOKEN_MAX_AGE = old
    assert auth.verify_reset_token(db, expired) is None


def test_reset_token_single_use(client, db):
    user = _owner(db)
    token = auth.create_reset_token(user)
    auth.set_password_for(db, user, "inzwischen-anders-1")
    db.expire_all()
    assert auth.verify_reset_token(db, token) is None  # verbraucht


# ---------------------------------------------------------------------------
# Ablauf über die Weboberfläche
# ---------------------------------------------------------------------------


def _setup_mail_account(db) -> EmailAccount:
    account = EmailAccount(
        name="Absender", provider="ionos", host="imap.ionos.de",
        username="noreply@example.org", password_enc=encrypt("x"),
    )
    db.add(account)
    db.commit()
    store.set_value(db, mailer.MAIL_ACCOUNT_KEY, str(account.id))
    return account


def test_login_page_links_forgot(client):
    client.cookies.clear()
    resp = client.get("/login")
    assert "Passwort vergessen?" in resp.text
    assert "/forgot" in resp.text


def test_forgot_page_public_and_hints_when_unconfigured(client):
    client.cookies.clear()
    resp = client.get("/forgot")
    assert resp.status_code == 200
    assert "nicht eingerichtet" in resp.text

    resp = client.post("/forgot", data={"email": TEST_EMAIL}, follow_redirects=False)
    assert "nicht%20eingerichtet" in resp.headers["location"].replace("+", "%20")


def test_forgot_sends_reset_link_and_reset_works(client, db, monkeypatch):
    _setup_mail_account(db)
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        mailer, "send_mail", lambda db_, to, subject, body: sent.append((to, subject, body))
    )

    client.cookies.clear()
    resp = client.post("/forgot", data={"email": TEST_EMAIL}, follow_redirects=False)
    assert resp.status_code == 303
    assert "Konto%20mit%20dieser" in resp.headers["location"].replace("+", "%20")
    assert len(sent) == 1
    to, subject, body = sent[0]
    assert to == TEST_EMAIL
    assert "zurücksetzen" in subject.lower()

    match = re.search(r"/reset\?token=([^\s]+)", body)
    assert match, body
    token = match.group(1)

    # Formular öffnen
    resp = client.get(f"/reset?token={token}")
    assert resp.status_code == 200
    assert TEST_EMAIL in resp.text

    # Neues Passwort setzen
    resp = client.post(
        "/reset",
        data={"token": token, "password": "frisch-gesetzt-1", "password2": "frisch-gesetzt-1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303 and "/login" in resp.headers["location"]
    db.expire_all()
    assert auth.authenticate(db, TEST_EMAIL, "frisch-gesetzt-1") is not None
    assert auth.authenticate(db, TEST_EMAIL, TEST_PASSWORD) is None

    # Derselbe Link ist danach verbraucht.
    resp = client.get(f"/reset?token={token}", follow_redirects=False)
    assert resp.status_code == 303 and "ung" in resp.headers["location"]


def test_forgot_unknown_email_same_answer_no_mail(client, db, monkeypatch):
    _setup_mail_account(db)
    sent = []
    monkeypatch.setattr(mailer, "send_mail", lambda *a, **k: sent.append(a))

    client.cookies.clear()
    resp = client.post(
        "/forgot", data={"email": "unbekannt@example.org"}, follow_redirects=False
    )
    assert "Konto%20mit%20dieser" in resp.headers["location"].replace("+", "%20")
    assert sent == []  # keine Mail, aber identische Antwort (kein Ausspähen)


def test_forgot_rate_limited(client, db, monkeypatch):
    from app.routers.auth import forgot_limiter

    _setup_mail_account(db)
    monkeypatch.setattr(mailer, "send_mail", lambda *a, **k: None)
    forgot_limiter.reset_all()
    client.cookies.clear()
    for _ in range(5):
        client.post("/forgot", data={"email": TEST_EMAIL}, follow_redirects=False)
    resp = client.post("/forgot", data={"email": TEST_EMAIL}, follow_redirects=False)
    assert "viele%20Anfragen" in resp.headers["location"].replace("+", "%20")
    forgot_limiter.reset_all()


def test_reset_password_mismatch(client, db):
    user = _owner(db)
    token = auth.create_reset_token(user)
    client.cookies.clear()
    resp = client.post(
        "/reset",
        data={"token": token, "password": "neues-pw-123", "password2": "anders-pw-123"},
        follow_redirects=False,
    )
    assert "stimmen%20nicht" in resp.headers["location"].replace("+", "%20")
    db.expire_all()
    assert auth.authenticate(db, TEST_EMAIL, TEST_PASSWORD) is not None


# ---------------------------------------------------------------------------
# Einstellungen: Absender-Konto wählen
# ---------------------------------------------------------------------------


def test_owner_sets_mail_account(client, db):
    account = EmailAccount(
        name="Buchhaltung", provider="gmx", host="imap.gmx.net",
        username="post@gmx.de", password_enc=encrypt("x"),
    )
    db.add(account)
    db.commit()

    resp = client.post(
        "/settings/mail", data={"account_id": str(account.id)}, follow_redirects=False
    )
    assert resp.status_code == 303
    db.expire_all()
    assert mailer.get_mail_account(db).id == account.id
    assert mailer.is_configured(db)

    # Abwählen deaktiviert den Versand wieder.
    client.post("/settings/mail", data={"account_id": "0"}, follow_redirects=False)
    db.expire_all()
    assert mailer.get_mail_account(db) is None


def test_smtp_settings_from_provider_and_guess():
    ionos = EmailAccount(
        name="a", provider="ionos", host="imap.ionos.de",
        username="u", password_enc=encrypt("x"),
    )
    assert mailer.smtp_settings(ionos) == ("smtp.ionos.de", 465, True)
    hotmail = EmailAccount(
        name="b", provider="hotmail", host="outlook.office365.com",
        username="u", password_enc=encrypt("x"),
    )
    assert mailer.smtp_settings(hotmail) == ("smtp.office365.com", 587, False)
    custom = EmailAccount(
        name="c", provider="custom", host="imap.firma-mail.de",
        username="u", password_enc=encrypt("x"),
    )
    assert mailer.smtp_settings(custom) == ("smtp.firma-mail.de", 465, True)
