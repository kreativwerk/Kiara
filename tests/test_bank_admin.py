"""Tests für Auszug-Upload mit Zeitraum, Auszug-Löschen und manuelle Zuordnung."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models import Attachment, BankStatement, BankTransaction, EmailAccount, Match
from app.security import encrypt

CSV_SAMPLE = (
    "Buchungstag;Beguenstigter/Zahlungspflichtiger;Verwendungszweck;Betrag\n"
    "01.06.2026;Muster GmbH;Rechnung 42;-119,00\n"
)


def _upload(client, **extra):
    data = {"name": "", "period_month": "6", "period_year": "2026"}
    data.update(extra)
    return client.post(
        "/bank/upload",
        data=data,
        files={"file": ("umsatz.csv", CSV_SAMPLE.encode(), "text/csv")},
        follow_redirects=False,
    )


def test_upload_requires_period(client):
    resp = _upload(client, period_month="0")
    assert "Monat" in resp.headers["location"]


def test_upload_stores_period_and_default_name(client, db):
    resp = _upload(client)
    assert resp.status_code == 303
    db.expire_all()
    stmt = db.query(BankStatement).one()
    assert stmt.period_month == 6
    assert stmt.period_year == 2026
    assert stmt.name == "Kontoauszug Juni 2026"


def test_delete_statement_removes_transactions(client, db):
    _upload(client)
    db.expire_all()
    stmt = db.query(BankStatement).one()
    assert db.query(BankTransaction).count() == 1

    resp = client.post(f"/bank/statements/{stmt.id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    db.expire_all()
    assert db.query(BankStatement).count() == 0
    assert db.query(BankTransaction).count() == 0


def test_manual_assign_flow(client, db):
    account = EmailAccount(
        name="T", host="imap.example.org", username="u@example.org",
        password_enc=encrypt("secret"),
    )
    db.add(account)
    db.commit()
    att = Attachment(
        account_id=account.id, filename="eon_abschlag.pdf", sha256="9" * 64,
        stored_path="x/e.pdf", year=2026, month=6, detected_amount=Decimal("92.00"),
    )
    stmt = BankStatement(
        name="s", source_filename="s.csv", file_format="csv",
        period_year=2026, period_month=6,
    )
    db.add_all([att, stmt])
    db.commit()
    txn = BankTransaction(
        statement_id=stmt.id, booking_date=date(2026, 6, 29),
        amount=Decimal("-92.00"), counterparty="E.ON", dedupe_hash="h-m",
    )
    db.add(txn)
    db.commit()

    # Zuordnungs-Seite zeigt den Kandidaten (Betrag ähnlich)
    resp = client.get(f"/bank/assign/{txn.id}")
    assert resp.status_code == 200
    assert "eon_abschlag.pdf" in resp.text

    # Zuordnen -> bestätigter manueller Match
    resp = client.post(f"/bank/assign/{txn.id}/{att.id}", follow_redirects=False)
    assert resp.status_code == 303
    db.expire_all()
    match = db.query(Match).one()
    assert match.transaction_id == txn.id
    assert match.attachment_id == att.id
    assert match.confirmed is True
    assert match.method == "manuell"
