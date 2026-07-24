"""Tests für die Login-Schicht (Benutzerkonten)."""
from tests.conftest import TEST_EMAIL, TEST_PASSWORD

from app.auth import hash_password, verify_password


def test_password_hash_roundtrip():
    stored = hash_password("geheim123")
    assert verify_password("geheim123", stored)
    assert not verify_password("falsch", stored)
    assert not verify_password("geheim123", "kaputt")


def test_fresh_app_redirects_to_setup(anon_client):
    resp = anon_client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/setup"


def test_health_is_public(anon_client):
    assert anon_client.get("/health").status_code == 200


def test_api_requires_login(anon_client):
    resp = anon_client.get("/api/stats")
    assert resp.status_code == 401


def test_setup_rejects_short_password(anon_client):
    resp = anon_client.post(
        "/setup",
        data={"name": "A", "email": "a@b.de", "password": "kurz", "password2": "kurz"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/setup" in resp.headers["location"]


def test_setup_rejects_mismatch(anon_client):
    resp = anon_client.post(
        "/setup",
        data={
            "name": "A", "email": "a@b.de",
            "password": "langespasswort", "password2": "anderespasswort",
        },
        follow_redirects=False,
    )
    assert "/setup" in resp.headers["location"]


def test_setup_then_access(client):
    # client-Fixture hat Setup + Login bereits erledigt
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    assert client.get("/api/stats").status_code == 200


def test_login_wrong_password(client):
    client.cookies.clear()
    resp = client.post(
        "/login",
        data={"email": TEST_EMAIL, "password": "voelligfalsch"},
        follow_redirects=False,
    )
    assert "/login" in resp.headers["location"]
    assert client.get("/api/stats").status_code == 401


def test_login_correct_password(client):
    client.cookies.clear()
    resp = client.post(
        "/login",
        data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert client.get("/api/stats").status_code == 200


def test_login_is_case_insensitive_for_email(client):
    client.cookies.clear()
    resp = client.post(
        "/login",
        data={"email": TEST_EMAIL.upper(), "password": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert resp.headers["location"] == "/"


def test_logout(client):
    assert client.get("/api/stats").status_code == 200
    client.post("/logout", follow_redirects=False)
    assert client.get("/api/stats").status_code == 401


def test_setup_not_repeatable(client):
    # Benutzer existieren -> /setup leitet zum Login um, POST ändert nichts
    resp = client.get("/setup", follow_redirects=False)
    assert resp.headers["location"] == "/login"
    resp = client.post(
        "/setup",
        data={
            "name": "X", "email": "x@y.de",
            "password": "neuespasswort1", "password2": "neuespasswort1",
        },
        follow_redirects=False,
    )
    assert resp.headers["location"] == "/login"
    # altes Konto gilt weiterhin
    client.cookies.clear()
    resp = client.post(
        "/login",
        data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert resp.headers["location"] == "/"
