"""Tests: Passwort-Zurücksetzen durch Administratoren (Web) und per CLI."""
from __future__ import annotations

from tests.conftest import TEST_EMAIL, TEST_PASSWORD

from app import auth
from app.cli import main as cli_main
from app.models import User


def _login(client, email, password):
    client.cookies.clear()
    return client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=False
    )


def _create_user(client, db, email, *, is_admin=False):
    resp = client.post(
        "/settings/users",
        data={
            "name": email.split("@")[0],
            "email": email,
            "password": "start-passwort-1",
            **({"is_admin": "true"} if is_admin else {}),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.expire_all()
    return db.query(User).filter(User.email == email).one()


def test_admin_resets_user_password(client, db):
    user = _create_user(client, db, "mitarbeiter@example.org")
    resp = client.post(
        f"/settings/users/{user.id}/password",
        data={"password": "ganz-neues-pw-9"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "Neues%20Passwort" in resp.headers["location"].replace("+", "%20")
    db.expire_all()
    assert auth.authenticate(db, "mitarbeiter@example.org", "ganz-neues-pw-9") is not None
    assert auth.authenticate(db, "mitarbeiter@example.org", "start-passwort-1") is None


def test_reset_rejects_short_password(client, db):
    user = _create_user(client, db, "kurz@example.org")
    resp = client.post(
        f"/settings/users/{user.id}/password",
        data={"password": "kurz"},
        follow_redirects=False,
    )
    assert "mindestens" in resp.headers["location"].replace("%20", " ")
    db.expire_all()
    assert auth.authenticate(db, "kurz@example.org", "start-passwort-1") is not None


def test_non_admin_cannot_reset(client, db):
    _create_user(client, db, "normal@example.org")
    victim = _create_user(client, db, "opfer@example.org")

    assert _login(client, "normal@example.org", "start-passwort-1").status_code == 303
    resp = client.post(
        f"/settings/users/{victim.id}/password",
        data={"password": "gehackt-pw-123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.expire_all()
    assert auth.authenticate(db, "opfer@example.org", "start-passwort-1") is not None
    assert auth.authenticate(db, "opfer@example.org", "gehackt-pw-123") is None


def test_org_admin_cannot_reset_foreign_org_user(client, db):
    # Betreiber legt eine zweite Organisation mit eigenem Admin an.
    resp = client.post(
        "/settings/orgs",
        data={
            "org_name": "Arion Logistics",
            "admin_name": "Albert",
            "admin_email": "chef@arion.example",
            "admin_password": "arion-start-pw",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Der Arion-Admin darf den Betreiber (andere Organisation) nicht anfassen.
    db.expire_all()
    owner = db.query(User).filter(User.email == TEST_EMAIL).one()
    assert _login(client, "chef@arion.example", "arion-start-pw").status_code == 303
    client.post(
        f"/settings/users/{owner.id}/password",
        data={"password": "uebernahme-pw-1"},
        follow_redirects=False,
    )
    db.expire_all()
    assert auth.authenticate(db, TEST_EMAIL, TEST_PASSWORD) is not None

    # Der Betreiber darf umgekehrt den Arion-Admin zurücksetzen (Passwort vergessen).
    arion_admin = db.query(User).filter(User.email == "chef@arion.example").one()
    assert _login(client, TEST_EMAIL, TEST_PASSWORD).status_code == 303
    client.post(
        f"/settings/users/{arion_admin.id}/password",
        data={"password": "arion-neu-pw-77"},
        follow_redirects=False,
    )
    db.expire_all()
    assert auth.authenticate(db, "chef@arion.example", "arion-neu-pw-77") is not None


# ---------------------------------------------------------------------------
# CLI-Rettungsanker (bei kompletter Aussperrung, via SSH/Docker)
# ---------------------------------------------------------------------------


def test_cli_list_users_and_reset(client, db, capsys):
    _create_user(client, db, "vergessen@example.org")

    assert cli_main(["list-users"]) == 0
    out = capsys.readouterr().out
    assert "vergessen@example.org" in out
    assert TEST_EMAIL in out
    assert "Betreiber" in out

    assert cli_main(["reset-password", "vergessen@example.org", "rettung-pw-99"]) == 0
    db.expire_all()
    assert auth.authenticate(db, "vergessen@example.org", "rettung-pw-99") is not None


def test_cli_reset_unknown_email(client, db, capsys):
    assert cli_main(["reset-password", "gibtsnicht@example.org", "irgendein-pw-1"]) == 1


def test_cli_reset_reactivates_disabled_user(client, db):
    user = _create_user(client, db, "deaktiviert@example.org")
    user.active = False
    db.commit()
    assert cli_main(["reset-password", "deaktiviert@example.org", "wieder-da-pw-1"]) == 0
    db.expire_all()
    assert auth.authenticate(db, "deaktiviert@example.org", "wieder-da-pw-1") is not None
