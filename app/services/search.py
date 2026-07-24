"""Smarte Beleg-Suche: tippfehlertolerant, mit Betrags- und Zeitraumerkennung.

Die Suche versteht eine freie Eingabe wie ``werkstatt juni 2026`` oder
``rechnng 119,00`` und kombiniert:

- **Volltext** über Dateiname, Betreff, Absender, Kategorie und PDF-Inhalt
- **Fuzzy-Matching** (difflib) für kleine Tippfehler
- **Umlaut-Normalisierung** ("tuv" findet "TÜV")
- **Beträge** ("119,00" oder "119" trifft den erkannten Belegbetrag,
  zur Not auch Beträge im PDF-Text)
- **Zeitraum-Tokens** ("2026" = Jahresfilter, "juni" = Monatsfilter)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Attachment
from .text_utils import parse_amount

# Länge bleibt pro Zeichen erhalten, damit Snippet-Positionen stimmen.
_NORMALIZE = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "s", "é": "e", "è": "e"})

_MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5,
    "juni": 6, "juli": 7, "august": 8, "september": 9, "oktober": 10,
    "november": 11, "dezember": 12,
}

_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
_DECIMAL_AMOUNT_RE = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{1,2}$|^\d+[.,]\d{1,2}$")
_PLAIN_NUMBER_RE = re.compile(r"^\d{1,7}$")
_WORD_RE = re.compile(r"[a-z0-9]+")

# Feld -> Gewicht: Treffer im Dateinamen zählen mehr als tief im PDF-Text.
_FIELD_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("filename", 3.0),
    ("subject", 2.0),
    ("category", 2.0),
    ("sender", 1.5),
    ("text", 1.0),
)

_FUZZY_THRESHOLD = 0.75
_MIN_SCORE = 0.5
_SNIPPET_RADIUS = 70


def normalize(value: str) -> str:
    return value.lower().translate(_NORMALIZE)


@dataclass
class ParsedQuery:
    tokens: list[str]
    amounts: list[Decimal]
    year: int | None = None
    month: int | None = None


@dataclass
class SearchHit:
    attachment: Attachment
    score: float
    snippet: str | None


def parse_query(query: str) -> ParsedQuery:
    """Zerlegt die Eingabe in Text-Tokens, Beträge und Zeitraumfilter."""
    parsed = ParsedQuery(tokens=[], amounts=[])
    for raw in query.split():
        token = normalize(raw.strip(" ,;.!?\"'€"))
        if not token:
            continue
        if _YEAR_RE.match(token) and parsed.year is None:
            parsed.year = int(token)
            continue
        if token in _MONTHS and parsed.month is None:
            parsed.month = _MONTHS[token]
            continue
        if _DECIMAL_AMOUNT_RE.match(token):
            amount = parse_amount(token)
            if amount is not None:
                parsed.amounts.append(amount)
            continue
        if _PLAIN_NUMBER_RE.match(token):
            # Ganze Zahl: kann Betrag ODER z.B. Rechnungsnummer sein -> beides.
            amount = parse_amount(token)
            if amount is not None:
                parsed.amounts.append(amount)
            parsed.tokens.append(token)
            continue
        parsed.tokens.append(token)
    return parsed


def _token_score(token: str, field_text: str, field_tokens: set[str]) -> float:
    """Score eines Suchworts in einem Feld: exakt > Präfix > fuzzy."""
    if len(token) >= 2 and token in field_text:
        return 1.0
    if len(token) < 3:
        return 0.0
    best = 0.0
    for candidate in field_tokens:
        if abs(len(candidate) - len(token)) > 3:
            continue
        if candidate.startswith(token) or token.startswith(candidate):
            best = max(best, 0.85)
            continue
        # Tippfehler stehen selten am Wortanfang – spart viele Vergleiche.
        if candidate[0] != token[0]:
            continue
        ratio = SequenceMatcher(None, token, candidate).ratio()
        if ratio >= _FUZZY_THRESHOLD:
            best = max(best, ratio * 0.9)
    return best


def _amount_variants(amount: Decimal) -> list[str]:
    english = f"{amount:,.2f}"                 # 1,234.56
    german = english.replace(",", "#").replace(".", ",").replace("#", ".")
    return [german, english, f"{amount:.2f}", f"{amount:.2f}".replace(".", ",")]


def _amount_in_text(amount: Decimal, text: str) -> bool:
    return any(variant in text for variant in _amount_variants(amount))


def _snippet(text: str | None, tokens: list[str]) -> str | None:
    """Textausschnitt rund um den ersten Treffer im PDF-Inhalt."""
    if not text:
        return None
    norm = normalize(text)
    position = -1
    for token in tokens:
        position = norm.find(token)
        if position >= 0:
            break
    if position < 0:
        return None
    start = max(0, position - _SNIPPET_RADIUS)
    end = min(len(text), position + _SNIPPET_RADIUS)
    snippet = " ".join(text[start:end].split())
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


def search(
    db: Session, query: str, limit: int = 100, org_id: int | None = None
) -> list[SearchHit]:
    """Durchsucht alle Belege und liefert die Treffer nach Relevanz sortiert."""
    query = (query or "").strip()[:200]
    if not query:
        return []
    parsed = parse_query(query)
    if not parsed.tokens and not parsed.amounts and parsed.year is None and parsed.month is None:
        return []

    stmt = select(Attachment)
    if org_id is not None:
        stmt = stmt.where(Attachment.org_id == org_id)
    if parsed.year is not None:
        stmt = stmt.where(Attachment.year == parsed.year)
    if parsed.month is not None:
        stmt = stmt.where(Attachment.month == parsed.month)
    attachments = db.execute(stmt).scalars().all()

    # Nur Zeitraum angegeben (z.B. "juni 2026"): alles aus dem Zeitraum zeigen.
    if not parsed.tokens and not parsed.amounts:
        return [SearchHit(att, 1.0, None) for att in attachments[:limit]]

    hits: list[SearchHit] = []
    for att in attachments:
        fields = {
            "filename": normalize(att.filename or ""),
            "subject": normalize(att.subject or ""),
            "category": normalize(att.category or ""),
            "sender": normalize(att.sender_email or ""),
            "text": normalize(att.text_content or ""),
        }
        field_tokens = {
            name: set(_WORD_RE.findall(value)) for name, value in fields.items()
        }

        score = 0.0
        matched = 0
        for token in parsed.tokens:
            best = 0.0
            for field_name, weight in _FIELD_WEIGHTS:
                token_score = _token_score(token, fields[field_name], field_tokens[field_name])
                best = max(best, token_score * weight)
            if best > 0:
                matched += 1
                score += best

        for amount in parsed.amounts:
            if att.detected_amount is not None and abs(
                Decimal(att.detected_amount) - amount
            ) <= Decimal("0.005"):
                matched += 1
                score += 4.0
            elif att.text_content and _amount_in_text(amount, att.text_content):
                matched += 1
                score += 2.5

        needles = len(parsed.tokens) + len(parsed.amounts)
        # Mindestens die Hälfte der Suchbegriffe muss treffen.
        if score >= _MIN_SCORE and matched >= max(1, (needles + 1) // 2):
            hits.append(
                SearchHit(att, round(score, 2), _snippet(att.text_content, parsed.tokens))
            )

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]
