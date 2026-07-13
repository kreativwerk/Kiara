"""Kleine Text-Helfer: Slugs, Dateinamen, Betragserkennung."""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")

# Beträge wie "1.234,56", "1234,56", "1,234.56", "99.90"
_AMOUNT_RE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+,\d{2}|\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})(?![\d])"
)


def slugify(value: str, default: str = "konto") -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = _SLUG_RE.sub("-", value.lower()).strip("-")
    return value or default


def safe_filename(name: str, fallback: str = "anhang.bin") -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.replace("/", "_").replace("\\", "_").strip()
    name = _UNSAFE_RE.sub("_", name).strip("._")
    return name or fallback


def parse_amount(text: str) -> Decimal | None:
    """Wandelt einen deutschen/englischen Betrags-String in ein Decimal um."""
    text = text.strip()
    if not text:
        return None
    # Deutsches Format: 1.234,56  -> 1234.56
    if "," in text and (text.rfind(",") > text.rfind(".")):
        text = text.replace(".", "").replace(" ", "").replace(",", ".")
    else:
        # Englisches Format: 1,234.56 -> 1234.56
        text = text.replace(",", "").replace(" ", "")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def extract_amounts(text: str) -> list[Decimal]:
    """Findet alle plausiblen Geldbeträge in einem Text."""
    amounts: list[Decimal] = []
    for match in _AMOUNT_RE.finditer(text):
        value = parse_amount(match.group(1))
        if value is not None:
            amounts.append(value)
    return amounts
