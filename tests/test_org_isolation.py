"""Mandanten-Isolation: Organisationen dürfen sich gegenseitig NICHT sehen."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from tests.conftest import TEST_EMAIL, TEST_PASSWORD

from app.models import (
    Attachment,
    BankStatement,
    BankTransaction,
    EmailAccount,
    Organization,
    User,
)
from app.security import encrypt


def _login(client, email, password):
    client.cookies.clear()
    return client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=False
    )


def _seed_two_orgs(client, db, org_id):
    """Org A (Setup, mit Daten) + Org B (Freund) mit eigenem Admin."""
    account = EmailAccount(
        org_id=org_id, name="Kreativwerk IONOS", host="imap.ionos.de",
        username="info@kreativwerk.de", password_enc=encrypt("x"),
    )
    db.add(account)
    db.commit()
    att = Attachment(
        org_id=org_id, account_id=account.id, filename="Geheime_Rechnung.pdf",
        sha256="a" * 64, stored_path="x/geheim.pdf", year=2026, month=7,
        detected_amount=Decimal("999.99"), text_content="Geheime Rechnung 999,99",
    )
    stmt = BankStatement(
        org_id=org_id, name="Kreativwerk Juli", source_filename="k.csv",
        file_format="csv", period_year=2026, period_month=7,
    )
    db.add_all([att, stmt])
    db.commit()
    txn = BankTransaction(
        statement_id=stmt.id, booking_date=date(2026, 7, 1),
        amount=Decimal("-999.99"), counterparty="Kreativwerk Lieferant",
        dedupe_hash="iso-1",
    )
    db.add(txn)
    db.commit()

    # Betreiber legt Organisation B mit eigenem Admin an
    resp = client.post(
        "/settings/orgs",
        data={
            "org_name": "Freund GmbH",
            "admin_name": "Freund",
            "admin_email": "freund@example.org",
            "admin_password": "freund-pass-1",
        },
        follow_redirects=False,
    )
    assert "angelegt" in resp.headers["location"]
    return att, stmt, txn


def test_org_b_sees_no_data_of_org_a(client, db, org_id):
    att, stmt, txn = _seed_two_orgs(client, db, org_id)

    # Als Freund (Org B) anmelden
    _login(client, "freund@example.org", "freund-pass-1")

    # API: alles leer
    stats = client.get("/api/stats").json()
    assert stats["accounts"] == 0
    assert stats["attachments"] == 0
    assert stats["transactions"] == 0
    assert client.get("/api/accounts").json() == []
    assert client.get("/api/attachments").json() == []

    # Suche findet fremde Belege nicht
    assert client.get("/api/search", params={"q": "Geheime"}).json() == []

    # Seiten zeigen fremde Daten nicht
    assert "Geheime_Rechnung" not in client.get("/attachments").text
    assert "Kreativwerk Lieferant" not in client.get("/bank").text
    assert "Kreativwerk IONOS" not in client.get("/accounts").text

    # Direktzugriffe auf fremde Objekte werden abgelehnt
    resp = client.get(f"/attachments/{att.id}/download", follow_redirects=False)
    assert resp.status_code == 303  # Umleitung mit Fehler statt Datei
    resp = client.post(f"/bank/statements/{stmt.id}/delete", follow_redirects=False)
    assert "nicht gefunden" in resp.headers["location"].replace("%20", " ")
    db.expire_all()
    assert db.query(BankStatement).count() == 1  # nichts gelöscht

    resp = client.get(f"/bank/assign/{txn.id}", follow_redirects=False)
    assert resp.status_code == 303  # kein Zugriff auf fremde Transaktion


def test_org_admin_cannot_see_or_manage_foreign_users(client, db, org_id):
    _seed_two_orgs(client, db, org_id)
    _login(client, "freund@example.org", "freund-pass-1")

    # Benutzerliste zeigt nur die eigene Organisation
    page = client.get("/settings").text
    assert "freund@example.org" in page
    assert TEST_EMAIL not in page
    assert "Neue Organisation anlegen" not in page  # kein Betreiber

    # Fremden Benutzer (Betreiber) kann er nicht deaktivieren
    db.expire_all()
    owner = db.query(User).filter_by(email=TEST_EMAIL).one()
    resp = client.post(f"/settings/users/{owner.id}/toggle", follow_redirects=False)
    db.expire_all()
    assert db.query(User).filter_by(email=TEST_EMAIL).one().active is True

    # Er kann keine Organisationen anlegen
    resp = client.post(
        "/settings/orgs",
        data={
            "org_name": "Hack", "admin_name": "H",
            "admin_email": "h@h.de", "admin_password": "hack-pass-99",
        },
        follow_redirects=False,
    )
    assert "Betreiber" in resp.headers["location"]
    db.expire_all()
    assert db.query(Organization).count() == 2


def test_owner_sees_both_orgs(client, db, org_id):
    _seed_two_orgs(client, db, org_id)
    _login(client, TEST_EMAIL, TEST_PASSWORD)

    page = client.get("/settings").text
    assert "Freund GmbH" in page          # Organisationen-Karte
    assert "freund@example.org" in page   # Benutzer beider Organisationen

    # Eigene Daten weiterhin sichtbar
    stats = client.get("/api/stats").json()
    assert stats["attachments"] == 1
    assert stats["transactions"] == 1
