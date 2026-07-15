from datetime import date
from decimal import Decimal

from app.models import (
    Attachment,
    BankStatement,
    BankTransaction,
    EmailAccount,
)
from app.services import matching
from app.security import encrypt


def _make_account(db) -> EmailAccount:
    account = EmailAccount(
        name="Test",
        provider="custom",
        host="imap.example.org",
        port=993,
        use_ssl=True,
        username="u@example.org",
        password_enc=encrypt("secret"),
    )
    db.add(account)
    db.commit()
    return account


def test_reconcile_matches_by_amount_and_date(db):
    account = _make_account(db)

    att = Attachment(
        account_id=account.id,
        filename="Rechnung_Muster.pdf",
        sha256="a" * 64,
        stored_path="x/y.pdf",
        year=2026,
        month=6,
        category="rechnung",
        detected_amount=Decimal("119.00"),
        sender_email="rechnung@muster.de",
        subject="Rechnung Muster GmbH",
    )
    stmt = BankStatement(name="s", source_filename="s.csv", file_format="csv")
    db.add_all([att, stmt])
    db.commit()

    txn = BankTransaction(
        statement_id=stmt.id,
        booking_date=date(2026, 6, 15),
        amount=Decimal("-119.00"),
        counterparty="Muster GmbH",
        purpose="Rechnung",
        dedupe_hash="h1",
    )
    db.add(txn)
    db.commit()

    created = matching.reconcile(db)
    assert created == 1

    db.refresh(txn)
    assert len(txn.matches) == 1
    assert txn.matches[0].attachment_id == att.id
    assert txn.matches[0].score >= 0.6


def test_no_match_on_amount_alone(db):
    """Der E.ON/eBay-Fall: gleicher Betrag, aber völlig anderer Absender
    -> darf NICHT mehr automatisch zugeordnet werden."""
    account = _make_account(db)
    att = Attachment(
        account_id=account.id,
        filename="ebay-documents - 2026-02-14T171921.520.pdf",
        sha256="e" * 64,
        stored_path="x/ebay.pdf",
        year=2026,
        month=6,
        category="rechnung",
        detected_amount=Decimal("92.00"),
        sender_email="rechnung@ebay.de",
        subject="Ihre eBay-Rechnung",
        text_content="eBay Kaufbeleg Gesamtbetrag 92,00 EUR Bestellnummer 11-22333-44",
    )
    stmt = BankStatement(name="s3", source_filename="s3.csv", file_format="csv")
    db.add_all([att, stmt])
    db.commit()
    txn = BankTransaction(
        statement_id=stmt.id,
        booking_date=date(2026, 6, 29),
        amount=Decimal("-92.00"),
        counterparty="E.ON Energie Deutschland GmbH",
        purpose="VK 242203665374 I / Betriebskosten / Nebenkosten",
        dedupe_hash="h-eon",
    )
    db.add(txn)
    db.commit()

    created = matching.reconcile(db)
    assert created == 0
    db.refresh(txn)
    assert txn.matches == []


def test_match_via_reference_number_in_text(db):
    """Referenznummer aus dem Verwendungszweck steht im PDF-Volltext -> Match,
    auch wenn Dateiname/Absender nichts hergeben."""
    account = _make_account(db)
    att = Attachment(
        account_id=account.id,
        filename="dokument_scan_0815.pdf",
        sha256="f" * 64,
        stored_path="x/eon.pdf",
        year=2026,
        month=6,
        category="rechnung",
        detected_amount=Decimal("92.00"),
        text_content="E.ON Energie Deutschland GmbH Vertragskonto 242203665374 "
                     "Abschlag Betriebskosten 92,00 EUR",
    )
    stmt = BankStatement(name="s4", source_filename="s4.csv", file_format="csv")
    db.add_all([att, stmt])
    db.commit()
    txn = BankTransaction(
        statement_id=stmt.id,
        booking_date=date(2026, 6, 29),
        amount=Decimal("-92.00"),
        counterparty="E.ON Energie Deutschland GmbH",
        purpose="VK 242203665374 I / Betriebskosten",
        dedupe_hash="h-eon2",
    )
    db.add(txn)
    db.commit()

    created = matching.reconcile(db)
    assert created == 1
    db.refresh(txn)
    assert txn.matches[0].attachment_id == att.id
    assert txn.matches[0].score >= 0.8  # Betrag + Referenz (+ Name im Text)


def test_suggestions_returns_close_amounts(db):
    account = _make_account(db)
    nah = Attachment(
        account_id=account.id, filename="nah.pdf", sha256="1" * 64,
        stored_path="x/n.pdf", year=2026, month=6, detected_amount=Decimal("92.10"),
    )
    weit = Attachment(
        account_id=account.id, filename="weit.pdf", sha256="2" * 64,
        stored_path="x/w.pdf", year=2026, month=6, detected_amount=Decimal("500.00"),
    )
    stmt = BankStatement(name="s5", source_filename="s5.csv", file_format="csv")
    db.add_all([nah, weit, stmt])
    db.commit()
    txn = BankTransaction(
        statement_id=stmt.id, booking_date=date(2026, 6, 29),
        amount=Decimal("-92.00"), dedupe_hash="h-sugg",
    )
    db.add(txn)
    db.commit()

    result = matching.suggestions(db, txn)
    names = [a.filename for a in result]
    assert "nah.pdf" in names
    assert "weit.pdf" not in names


def test_reconcile_no_match_when_amount_differs(db):
    account = _make_account(db)
    att = Attachment(
        account_id=account.id,
        filename="Beleg.pdf",
        sha256="b" * 64,
        stored_path="x/z.pdf",
        year=2026,
        month=6,
        detected_amount=Decimal("50.00"),
    )
    stmt = BankStatement(name="s2", source_filename="s2.csv", file_format="csv")
    db.add_all([att, stmt])
    db.commit()
    txn = BankTransaction(
        statement_id=stmt.id,
        booking_date=date(2026, 6, 15),
        amount=Decimal("-119.00"),
        dedupe_hash="h2",
    )
    db.add(txn)
    db.commit()

    matching.reconcile(db)
    db.refresh(txn)
    assert txn.matches == []
