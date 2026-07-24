"""Tests für Benutzerverwaltung und Migration des Alt-Passworts."""
from __future__ import annotations

from tests.conftest import TEST_EMAIL, TEST_PASSWORD

from app import auth
from app import settings_store as store
from app.models import User


def _login(client, email, password):
    client.cookies.clear()
    return client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=False
    )


def test_legacy_password_migrates_to_admin_user(anon_client, db):
    # Alt-Installation: nur das Einzel-App-Passwort existiert.
    store.set_value(db, auth.AUTH_PASSWORD_KEY, auth.hash_password("altes-passwort1"))
    auth.migrate_legacy_password(db)

    user = db.query(User).one()
    assert user.email == "admin"
    assert user.is_admin is True

    # Anmeldung mit "admin" + altem Passwort funktioniert weiter.
    resp = _login(anon_client, "admin", "altes-passwort1")
    assert resp.headers["location"] == "/"


def test_admin_creates_user_who_can_login(client):
    resp = client.post(
        "/settings/users",
        data={"name": "Ehefrau", "email": "frau@example.org", "password": "sicher-1234"},
        follow_redirects=False,
    )
    assert "angelegt" in resp.headers["location"]

    resp = _login(client, "frau@example.org", "sicher-1234")
    assert resp.headers["location"] == "/"
    assert client.get("/api/stats").status_code == 200


def test_duplicate_email_rejected(client):
    payload = {"name": "Doppelt", "email": "doppelt@example.org", "password": "sicher-1234"}
    client.post("/settings/users", data=payload)
    resp = client.post("/settings/users", data=payload, follow_redirects=False)
    assert "schon" in resp.headers["location"]


def test_non_admin_cannot_manage_users(client, db):
    client.post(
        "/settings/users",
        data={"name": "Normalo", "email": "normalo@example.org", "password": "sicher-1234"},
    )
    _login(client, "normalo@example.org", "sicher-1234")

    resp = client.post(
        "/settings/users",
        data={"name": "Hacker", "email": "hacker@example.org", "password": "sicher-1234"},
        follow_redirects=False,
    )
    assert "Administratoren" in resp.headers["location"]
    db.expire_all()
    assert db.query(User).filter_by(email="hacker@example.org").count() == 0

    # Benutzerliste wird Nicht-Admins nicht angezeigt
    resp = client.get("/settings")
    assert "Neuen Benutzer anlegen" not in resp.text


def test_deactivated_user_is_locked_out(client, db):
    client.post(
        "/settings/users",
        data={"name": "Weg", "email": "weg@example.org", "password": "sicher-1234"},
    )
    db.expire_all()
    target = db.query(User).filter_by(email="weg@example.org").one()

    resp = client.post(f"/settings/users/{target.id}/toggle", follow_redirects=False)
    assert "deaktiviert" in resp.headers["location"]

    resp = _login(client, "weg@example.org", "sicher-1234")
    assert "/login" in resp.headers["location"]  # abgelehnt


def test_cannot_remove_last_admin(client, db):
    db.expire_all()
    me = db.query(User).filter_by(email=TEST_EMAIL).one()

    # sich selbst deaktivieren/löschen: verboten
    resp = client.post(f"/settings/users/{me.id}/toggle", follow_redirects=False)
    assert "selbst" in resp.headers["location"]
    resp = client.post(f"/settings/users/{me.id}/delete", follow_redirects=False)
    assert "selbst" in resp.headers["location"]


def test_change_own_password(client):
    resp = client.post(
        "/settings/password",
        data={"password": "nagelneu-999", "password2": "nagelneu-999"},
        follow_redirects=False,
    )
    from urllib.parse import unquote

    assert "geändert" in unquote(resp.headers["location"])

    resp = _login(client, TEST_EMAIL, "nagelneu-999")
    assert resp.headers["location"] == "/"
    resp = _login(client, TEST_EMAIL, TEST_PASSWORD)
    assert "/login" in resp.headers["location"]  # altes Passwort ungültig


def test_sidebar_shows_user_name(client):
    resp = client.get("/settings")
    assert "Chef" in resp.text
