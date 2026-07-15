"""Tests für den PDF-Kontoauszug-Parser."""
from datetime import date
from decimal import Decimal

from app.services import bank_import

# Sparkassen-/Volksbank-Stil: dd.mm. + Wertstellung, Betrag mit Vorzeichen am Ende,
# Empfänger und Verwendungszweck in Folgezeilen, Salden-Zeilen als Störer.
SPARKASSE_STYLE = """Kontoauszug Nr. 6/2026 vom 01.06.2026 bis 30.06.2026
IBAN: DE02 1203 0000 0000 2020 51
Buchungstag Wert Erläuterung Betrag
alter Kontostand vom 31.05.2026 5.000,00+
01.06. 01.06. LASTSCHRIFT 119,00-
Telekom Deutschland GmbH
Rechnung 2026-042 Kundennummer 445566
03.06. 03.06. GUTSCHR.UEBERWEISUNG 1.500,00+
Kunde AG
Zahlung Projekt Alpha
15.06. 15.06. KARTENZAHLUNG 98,40-
ARAL Station 0712
neuer Kontostand vom 30.06.2026 6.282,60+
"""

# Direktbank-Stil: volles Datum, Betrag mit Minuszeichen vorn.
DIREKTBANK_STYLE = """Kontoauszug Juni 2026
05.06.2026 Kartenzahlung REWE Markt Berlin -23,45
07.06.2026 Gehalt Arion Logistics GmbH +3.450,00
"""


def test_parse_pdf_text_sparkasse_style():
    stmt = bank_import.parse_pdf_text(SPARKASSE_STYLE)
    assert stmt.file_format == "pdf"
    assert len(stmt.transactions) == 3  # Salden-Zeilen ausgefiltert

    telekom = stmt.transactions[0]
    assert telekom.amount == Decimal("-119.00")
    assert telekom.booking_date == date(2026, 6, 1)
    assert telekom.counterparty == "Telekom Deutschland GmbH"
    assert "Rechnung 2026-042" in telekom.purpose

    eingang = stmt.transactions[1]
    assert eingang.amount == Decimal("1500.00")
    assert eingang.counterparty == "Kunde AG"

    karte = stmt.transactions[2]
    assert karte.amount == Decimal("-98.40")
    assert karte.counterparty == "ARAL Station 0712"


def test_parse_pdf_text_direktbank_style():
    stmt = bank_import.parse_pdf_text(DIREKTBANK_STYLE)
    assert len(stmt.transactions) == 2
    assert stmt.transactions[0].amount == Decimal("-23.45")
    assert stmt.transactions[0].booking_date == date(2026, 6, 5)
    assert stmt.transactions[1].amount == Decimal("3450.00")


def _make_text_pdf(lines: list[str]) -> bytes:
    """Erzeugt ein minimales, valides PDF mit echter Textebene."""

    def esc(s: str) -> str:
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    content = (
        "BT /F1 11 Tf 40 800 Td "
        + " ".join(f"({esc(line)}) Tj 0 -16 Td" for line in lines)
        + " ET"
    )
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref_pos = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF"
    ).encode()
    return out


def test_parse_real_pdf_end_to_end():
    pdf = _make_text_pdf(
        [
            "Kontoauszug Nr. 6/2026",
            "01.06. 01.06. LASTSCHRIFT 119,00-",
            "Telekom Deutschland GmbH",
            "Rechnung 2026-042",
            "03.06. 03.06. GUTSCHR.UEBERWEISUNG 1.500,00+",
            "Kunde AG",
        ]
    )
    stmt = bank_import.parse_statement("auszug.pdf", pdf)
    assert stmt.file_format == "pdf"
    assert len(stmt.transactions) == 2
    assert stmt.transactions[0].amount == Decimal("-119.00")
    assert stmt.transactions[0].counterparty == "Telekom Deutschland GmbH"
    assert stmt.transactions[1].amount == Decimal("1500.00")


def test_dispatcher_detects_pdf_header():
    stmt = bank_import.parse_statement("auszug.pdf", b"%PDF-1.4 kaputt")
    assert stmt.file_format == "pdf"
    assert stmt.transactions == []


def test_pdf_year_inferred_from_header():
    text = "Auszug 2/2025\n01.02. 01.02. LASTSCHRIFT 50,00-\nStadtwerke"
    stmt = bank_import.parse_pdf_text(text)
    assert stmt.transactions[0].booking_date == date(2025, 2, 1)
