"""Import von Kontoauszügen: CSV (dt. Banken), CAMT.053 (XML) und MT940."""
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from xml.etree import ElementTree as ET

from .text_utils import parse_amount

# ---------------------------------------------------------------------------
# Datencontainer
# ---------------------------------------------------------------------------


@dataclass
class ParsedTransaction:
    amount: Decimal
    booking_date: date | None = None
    value_date: date | None = None
    currency: str = "EUR"
    counterparty: str | None = None
    purpose: str | None = None
    reference: str | None = None

    @property
    def dedupe_hash(self) -> str:
        base = "|".join(
            [
                self.booking_date.isoformat() if self.booking_date else "",
                f"{self.amount:.2f}",
                (self.counterparty or "").strip().lower(),
                (self.purpose or "").strip().lower()[:120],
                (self.reference or "").strip(),
            ]
        )
        return hashlib.sha256(base.encode()).hexdigest()


@dataclass
class ParsedStatement:
    file_format: str
    account_iban: str | None = None
    transactions: list[ParsedTransaction] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Datums-Helfer
# ---------------------------------------------------------------------------

_DATE_FORMATS = ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "booking_date": ("buchungstag", "buchungsdatum", "datum", "booking date", "date"),
    "value_date": ("valuta", "wertstellung", "valutadatum", "value date"),
    "amount": ("betrag", "umsatz", "amount", "betrag (eur)", "betrag eur"),
    "currency": ("währung", "waehrung", "currency"),
    "counterparty": (
        "beguenstigter/zahlungspflichtiger",
        "begünstigter/zahlungspflichtiger",
        "auftraggeber/empfänger",
        "name",
        "empfänger",
        "zahlungsempfänger",
        "counterparty",
        "payee",
    ),
    "purpose": ("verwendungszweck", "buchungstext", "vorgang/verwendungszweck", "purpose", "description"),
    "reference": ("kundenreferenz", "mandatsreferenz", "reference", "referenz"),
}


def _normalize_header(name: str) -> str:
    return name.strip().strip('"').lower()


def _build_column_map(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    normalized = [_normalize_header(h) for h in headers]
    for field_name, aliases in _COLUMN_ALIASES.items():
        for idx, header in enumerate(normalized):
            if header in aliases:
                mapping[field_name] = idx
                break
    return mapping


def _sniff_delimiter(sample: str) -> str:
    counts = {d: sample.count(d) for d in (";", ",", "\t")}
    return max(counts, key=counts.get) or ";"


def parse_csv(content: bytes) -> ParsedStatement:
    text = content.decode("utf-8-sig", errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ParsedStatement(file_format="csv")

    # Header ist die erste Zeile, die eine bekannte Spalte enthält.
    delimiter = _sniff_delimiter("\n".join(lines[:10]))
    header_idx = 0
    for idx, line in enumerate(lines[:15]):
        cells = [_normalize_header(c) for c in line.split(delimiter)]
        if any(
            cell in aliases
            for cell in cells
            for aliases in _COLUMN_ALIASES.values()
        ):
            header_idx = idx
            break

    reader = csv.reader(io.StringIO("\n".join(lines[header_idx:])), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return ParsedStatement(file_format="csv")

    columns = _build_column_map(rows[0])
    statement = ParsedStatement(file_format="csv")
    if "amount" not in columns:
        return statement

    def cell(row: list[str], key: str) -> str | None:
        idx = columns.get(key)
        if idx is None or idx >= len(row):
            return None
        return row[idx].strip().strip('"') or None

    for row in rows[1:]:
        raw_amount = cell(row, "amount")
        amount = parse_amount(raw_amount) if raw_amount else None
        if amount is None:
            continue
        statement.transactions.append(
            ParsedTransaction(
                amount=amount,
                booking_date=_parse_date(cell(row, "booking_date")),
                value_date=_parse_date(cell(row, "value_date")),
                currency=(cell(row, "currency") or "EUR"),
                counterparty=cell(row, "counterparty"),
                purpose=cell(row, "purpose"),
                reference=cell(row, "reference"),
            )
        )
    return statement


# ---------------------------------------------------------------------------
# CAMT.053 (ISO 20022 XML)
# ---------------------------------------------------------------------------


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(elem: ET.Element, *names: str) -> ET.Element | None:
    for child in elem.iter():
        if _localname(child.tag) in names:
            return child
    return None


def _findall_direct(elem: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in elem if _localname(c.tag) == name]


def parse_camt(content: bytes) -> ParsedStatement:
    root = ET.fromstring(content)
    statement = ParsedStatement(file_format="camt")

    iban_elem = _find(root, "IBAN")
    if iban_elem is not None and iban_elem.text:
        statement.account_iban = iban_elem.text.strip()

    for entry in root.iter():
        if _localname(entry.tag) != "Ntry":
            continue

        amt_elem = _find(entry, "Amt")
        amount = parse_amount(amt_elem.text) if (amt_elem is not None and amt_elem.text) else None
        if amount is None:
            continue
        currency = amt_elem.get("Ccy", "EUR") if amt_elem is not None else "EUR"

        cd_elem = _find(entry, "CdtDbtInd")
        if cd_elem is not None and cd_elem.text == "DBIT":
            amount = -abs(amount)

        booking = _find(entry, "BookgDt")
        value = _find(entry, "ValDt")

        purpose_parts: list[str] = []
        for ustrd in entry.iter():
            if _localname(ustrd.tag) == "Ustrd" and ustrd.text:
                purpose_parts.append(ustrd.text.strip())

        counterparty = None
        name_elem = _find(entry, "Nm")
        if name_elem is not None and name_elem.text:
            counterparty = name_elem.text.strip()

        statement.transactions.append(
            ParsedTransaction(
                amount=amount,
                currency=currency,
                booking_date=_parse_date(_date_text(booking)),
                value_date=_parse_date(_date_text(value)),
                counterparty=counterparty,
                purpose=" ".join(purpose_parts) or None,
            )
        )
    return statement


def _date_text(elem: ET.Element | None) -> str | None:
    if elem is None:
        return None
    for child in elem.iter():
        if _localname(child.tag) in ("Dt", "DtTm") and child.text:
            return child.text.strip()[:10]
    return elem.text.strip()[:10] if elem.text else None


# ---------------------------------------------------------------------------
# MT940
# ---------------------------------------------------------------------------

_MT940_LINE_61 = re.compile(
    r":61:(?P<value>\d{6})(?P<booking>\d{4})?(?P<mark>[CD]R?)(?P<amount>[\d,]+)"
)


def parse_mt940(content: bytes) -> ParsedStatement:
    text = content.decode("utf-8", errors="replace")
    statement = ParsedStatement(file_format="mt940")

    current: ParsedTransaction | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith(":25:"):
            statement.account_iban = line[4:].strip() or statement.account_iban
        elif line.startswith(":61:"):
            match = _MT940_LINE_61.match(line)
            if not match:
                continue
            amount = parse_amount(match.group("amount").replace(",", "."))
            if amount is None:
                continue
            if match.group("mark").startswith("D"):
                amount = -abs(amount)
            value_date = _parse_mt_date(match.group("value"))
            booking_date = value_date
            if match.group("booking"):
                booking_date = _parse_mt_booking(match.group("value"), match.group("booking"))
            current = ParsedTransaction(
                amount=amount, booking_date=booking_date, value_date=value_date
            )
            statement.transactions.append(current)
        elif line.startswith(":86:") and current is not None:
            current.purpose = line[4:].strip() or current.purpose
    return statement


def _parse_mt_date(yymmdd: str) -> date | None:
    try:
        return datetime.strptime(yymmdd, "%y%m%d").date()
    except ValueError:
        return None


def _parse_mt_booking(value_yymmdd: str, mmdd: str) -> date | None:
    year = value_yymmdd[:2]
    try:
        return datetime.strptime(year + mmdd, "%y%m%d").date()
    except ValueError:
        return _parse_mt_date(value_yymmdd)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def parse_statement(filename: str, content: bytes) -> ParsedStatement:
    """Erkennt das Format anhand von Endung/Inhalt und parst den Kontoauszug."""
    lower = filename.lower()
    head = content[:512].lstrip()

    if lower.endswith(".xml") or head.startswith(b"<?xml") or b"<Document" in content[:2048]:
        return parse_camt(content)
    if lower.endswith(".sta") or lower.endswith(".mt940") or b":61:" in content[:4096]:
        return parse_mt940(content)
    return parse_csv(content)
