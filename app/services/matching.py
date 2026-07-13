"""Gegenkontrolle: Belege (Anhänge) automatisch Banktransaktionen zuordnen."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Attachment, BankTransaction, Match

DEFAULT_DATE_WINDOW = 60  # Tage: ein Beleg darf so lange vor der Zahlung liegen
DEFAULT_AMOUNT_TOLERANCE = Decimal("0.01")
SCORE_THRESHOLD = 0.6


@dataclass
class MatchCandidate:
    transaction_id: int
    attachment_id: int
    score: float


def _attachment_date(att: Attachment) -> date | None:
    if att.year and att.month:
        return date(att.year, att.month, 1)
    return None


def _name_bonus(txn: BankTransaction, att: Attachment) -> float:
    counterparty = (txn.counterparty or "").lower()
    if not counterparty:
        return 0.0
    haystack = f"{att.sender_email or ''} {att.subject or ''} {att.filename}".lower()
    tokens = [t for t in counterparty.replace(".", " ").split() if len(t) >= 4]
    if tokens and any(token in haystack for token in tokens):
        return 0.1
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

    score = 0.6  # Betrag stimmt überein

    att_date = _attachment_date(att)
    if att_date and txn.booking_date:
        delta = (txn.booking_date - att_date).days
        if 0 <= delta <= date_window:
            score += 0.3 * (1 - delta / date_window)
        elif -5 <= delta < 0:
            score += 0.15  # Beleg leicht nach Buchung (Toleranz)

    score += _name_bonus(txn, att)
    return round(min(score, 1.0), 3)


def reconcile(
    db: Session,
    *,
    date_window: int = DEFAULT_DATE_WINDOW,
    tolerance: Decimal = DEFAULT_AMOUNT_TOLERANCE,
) -> int:
    """Berechnet automatische Zuordnungen neu. Bestätigte Matches bleiben erhalten."""
    # Bestehende, nicht bestätigte Auto-Matches verwerfen.
    db.query(Match).filter(Match.confirmed.is_(False)).delete(synchronize_session=False)
    db.commit()

    confirmed = db.execute(
        select(Match.transaction_id, Match.attachment_id).where(Match.confirmed.is_(True))
    ).all()
    used_txns = {row[0] for row in confirmed}
    used_atts = {row[1] for row in confirmed}

    transactions = db.execute(select(BankTransaction)).scalars().all()
    attachments = db.execute(
        select(Attachment).where(Attachment.detected_amount.is_not(None))
    ).scalars().all()

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
