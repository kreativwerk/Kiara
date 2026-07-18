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


# Schlüsselwörter, die den Endbetrag einer Rechnung markieren.
_STRONG_TOTAL_KEYWORDS = (
    "zu zahlen", "zahlbetrag", "rechnungsbetrag", "gesamtbetrag", "endbetrag",
    "gesamtsumme", "rechnungssumme", "zahlungsbetrag", "forderungsbetrag",
    "amount due", "total due", "grand total", "invoice total",
)
_WEAK_TOTAL_KEYWORDS = ("gesamt", "summe", "total", "brutto")


def detect_total_amount(text: str) -> Decimal | None:
    """Bester Versuch, den ENDbetrag einer Rechnung zu finden.

    Statt stumpf den größten Betrag zu nehmen (der auch eine Einzelposition
    sein kann), werden zuerst Zeilen mit typischen Endbetrag-Wörtern
    durchsucht ("Rechnungsbetrag", "zu zahlen", ...), dann schwächere
    Summen-Wörter ("Gesamt", "Summe"), und erst als letzter Ausweg der
    größte Betrag im Dokument.
    """
    lines = text.splitlines()
    strong: list[Decimal] = []
    weak: list[Decimal] = []

    for index, line in enumerate(lines):
        lower = line.lower()
        is_strong = any(k in lower for k in _STRONG_TOTAL_KEYWORDS)
        is_weak = not is_strong and any(k in lower for k in _WEAK_TOTAL_KEYWORDS)
        if not is_strong and not is_weak:
            continue
        amounts = extract_amounts(line)
        if not amounts and index + 1 < len(lines):
            # Betrag steht manchmal in der Folgezeile (Tabellen-Layout).
            amounts = extract_amounts(lines[index + 1])
        if not amounts:
            continue
        (strong if is_strong else weak).append(max(amounts))

    if strong:
        return max(strong)
    if weak:
        return max(weak)
    all_amounts = extract_amounts(text)
    return max(all_amounts) if all_amounts else None
