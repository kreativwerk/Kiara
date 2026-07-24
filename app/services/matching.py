"""Gegenkontrolle: Belege (Anhänge) automatisch Banktransaktionen zuordnen.

Grundregel: Der **Betrag allein reicht nie** für eine automatische Zuordnung.
Zusätzlich muss ein Identitäts-Beweis vorliegen – der Zahlungsempfänger oder
eine Referenz-/Rechnungsnummer aus dem Verwendungszweck muss im Beleg
(Dateiname, Betreff, Absender oder PDF-Volltext) wiederzufinden sein. Das
verhindert Fehlzuordnungen bei häufigen Beträgen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Attachment, BankStatement, BankTransaction, Match

DEFAULT_DATE_WINDOW = 60  # Tage: ein Beleg darf so lange vor der Zahlung liegen
DEFAULT_AMOUNT_TOLERANCE = Decimal("0.01")
SCORE_THRESHOLD = 0.6

AMOUNT_SCORE = 0.5       # Betrag stimmt (notwendige Bedingung)
NAME_SCORE = 0.25        # Empfängername im Beleg gefunden
REFERENCE_SCORE = 0.35   # Referenz-/Rechnungsnummer im Beleg gefunden
IDENTITY_CAP = 0.4       # Name + Referenz zusammen gedeckelt
DATE_SCORE_MAX = 0.25    # Bonus für zeitliche Nähe

# Referenz-Kandidaten aus dem Verwendungszweck: mind. 6 Zeichen, mind. 1 Ziffer.
_REF_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9./-]{5,}")

# Häufige Wörter, die als "Name" nichts beweisen.
_NAME_STOPWORDS = {
    "gmbh", "gmbh.", "ag", "kg", "ohg", "ug", "e.k.", "co.", "und", "the",
    "sepa", "lastschrift", "überweisung", "ueberweisung", "gutschrift",
    "basislastschrift", "dauerauftrag", "kartenzahlung", "entgelt",
}


@dataclass
class MatchCandidate:
    transaction_id: int
    attachment_id: int
    score: float


def _attachment_date(att: Attachment) -> date | None:
    if att.year and att.month:
        return date(att.year, att.month, 1)
    return None


def _haystack(att: Attachment) -> str:
    parts = [att.sender_email or "", att.subject or "", att.filename or ""]
    if att.text_content:
        parts.append(att.text_content)
    return " ".join(parts).lower()


def _name_bonus(txn: BankTransaction, haystack: str) -> float:
    counterparty = (txn.counterparty or "").lower()
    if not counterparty:
        return 0.0
    tokens = [
        t for t in re.split(r"[^a-zäöüß0-9]+", counterparty)
        if len(t) >= 4 and t not in _NAME_STOPWORDS
    ]
    if tokens and any(token in haystack for token in tokens):
        return NAME_SCORE
    return 0.0


def _reference_bonus(txn: BankTransaction, att: Attachment) -> float:
    """Referenz-/Rechnungsnummern aus dem Verwendungszweck im Beleg suchen."""
    if not att.text_content:
        return 0.0
    text = att.text_content.lower()
    source = f"{txn.purpose or ''} {txn.reference or ''}".lower()
    for token in _REF_TOKEN.findall(source):
        if not any(ch.isdigit() for ch in token):
            continue
        # Reine Datums-/Betragsfragmente überspringen
        if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2,4}", token):
            continue
        if token in text:
            return REFERENCE_SCORE
    return 0.0


def _date_bonus(txn: BankTransaction, att: Attachment, date_window: int) -> float:
    att_date = _attachment_date(att)
    if not att_date or not txn.booking_date:
        return 0.0
    delta = (txn.booking_date - att_date).days
    if 0 <= delta <= date_window:
        return DATE_SCORE_MAX * (1 - delta / date_window)
    if -5 <= delta < 0:
        return DATE_SCORE_MAX / 2  # Beleg leicht nach Buchung (Toleranz)
    return 0.0


def _score(
    txn: BankTransaction,
    att: Attachment,
    date_window: int,
    tolerance: Decimal,
) -> float:
    if att.detected_amount is None:
        return 0.0
    if abs(Decimal(att.detected_amount) - abs(Decimal(txn.amount))) > tolerance:
        return 0.0

    identity = min(
        IDENTITY_CAP,
        _name_bonus(txn, _haystack(att)) + _reference_bonus(txn, att),
    )
    if identity == 0.0:
        # Betrag allein beweist nichts -> keine automatische Zuordnung.
        return 0.0

    score = AMOUNT_SCORE + identity + _date_bonus(txn, att, date_window)
    return round(min(score, 1.0), 3)


def reconcile(
    db: Session,
    org_id: int | None = None,
    *,
    date_window: int = DEFAULT_DATE_WINDOW,
    tolerance: Decimal = DEFAULT_AMOUNT_TOLERANCE,
) -> int:
    """Berechnet automatische Zuordnungen neu (pro Organisation).

    Bestätigte Matches bleiben erhalten. ``org_id=None`` bedeutet: über alle
    Daten (nur für Wartung/Tests gedacht).
    """
    # Bestehende, nicht bestätigte Auto-Matches verwerfen (nur diese Organisation).
    unconfirmed = db.query(Match).filter(Match.confirmed.is_(False))
    if org_id is not None:
        txn_ids = select(BankTransaction.id).join(BankStatement).where(
            BankStatement.org_id == org_id
        )
        unconfirmed = unconfirmed.filter(Match.transaction_id.in_(txn_ids))
    unconfirmed.delete(synchronize_session=False)
    db.commit()

    confirmed = db.execute(
        select(Match.transaction_id, Match.attachment_id).where(Match.confirmed.is_(True))
    ).all()
    used_txns = {row[0] for row in confirmed}
    used_atts = {row[1] for row in confirmed}

    txn_stmt = select(BankTransaction)
    att_stmt = select(Attachment).where(Attachment.detected_amount.is_not(None))
    if org_id is not None:
        txn_stmt = txn_stmt.join(BankStatement).where(BankStatement.org_id == org_id)
        att_stmt = att_stmt.where(Attachment.org_id == org_id)
    transactions = db.execute(txn_stmt).scalars().all()
    attachments = db.execute(att_stmt).scalars().all()

    candidates: list[MatchCandidate] = []
    for txn in transactions:
        if txn.id in used_txns:
            continue
        for att in attachments:
            if att.id in used_atts:
                continue
            score = _score(txn, att, date_window, tolerance)
            if score >= SCORE_THRESHOLD:
                candidates.append(MatchCandidate(txn.id, att.id, score))

    # Greedy: höchste Scores zuerst, jede Transaktion/jeder Beleg nur einmal.
    candidates.sort(key=lambda c: c.score, reverse=True)
    created = 0
    for cand in candidates:
        if cand.transaction_id in used_txns or cand.attachment_id in used_atts:
            continue
        db.add(
            Match(
                transaction_id=cand.transaction_id,
                attachment_id=cand.attachment_id,
                score=cand.score,
                method="auto",
                confirmed=False,
            )
        )
        used_txns.add(cand.transaction_id)
        used_atts.add(cand.attachment_id)
        created += 1
    db.commit()
    return created


def suggestions(
    db: Session,
    txn: BankTransaction,
    org_id: int | None = None,
    *,
    tolerance: Decimal = Decimal("0.50"),
    limit: int = 15,
) -> list[Attachment]:
    """Kandidaten für die manuelle Zuordnung: passender Betrag, Datum in der Nähe."""
    target = abs(Decimal(txn.amount))
    att_stmt = select(Attachment).where(Attachment.detected_amount.is_not(None))
    if org_id is not None:
        att_stmt = att_stmt.where(Attachment.org_id == org_id)
    attachments = db.execute(att_stmt).scalars().all()

    def sort_key(att: Attachment):
        amount_delta = abs(Decimal(att.detected_amount) - target)
        att_date = _attachment_date(att)
        if att_date and txn.booking_date:
            date_delta = abs((txn.booking_date - att_date).days)
        else:
            date_delta = 9999
        return (amount_delta, date_delta)

    close = [
        att for att in attachments
        if abs(Decimal(att.detected_amount) - target) <= tolerance
    ]
    close.sort(key=sort_key)
    return close[:limit]
