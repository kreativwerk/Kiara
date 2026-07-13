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
