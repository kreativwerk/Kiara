"""Tests für die OCR-Texterkennung."""
from __future__ import annotations

import pytest

from app.services import ocr
from app.services.attachments import extract_text

ocr_installed = pytest.mark.skipif(
    not ocr.ocr_available(), reason="Tesseract nicht installiert"
)


def _make_receipt_image(path, text_lines: list[str]) -> None:
    """Erzeugt ein gut lesbares 'Beleg-Foto' für den OCR-Test."""
    from PIL import Image, ImageDraw

    img = Image.new("L", (900, 80 + 70 * len(text_lines)), color=255)
    draw = ImageDraw.Draw(img)
    try:
        from PIL import ImageFont

        font = ImageFont.load_default(size=42)
    except Exception:
        font = None
    for i, line in enumerate(text_lines):
        draw.text((40, 40 + i * 70), line, fill=0, font=font)
    img.save(path)


@ocr_installed
def test_ocr_image_reads_text(tmp_path):
    img_path = tmp_path / "kassenbon.png"
    _make_receipt_image(img_path, ["RECHNUNG 4711", "GESAMT 119,00 EUR"])
    text = ocr.ocr_image(img_path)
    assert text is not None
    assert "RECHNUNG" in text.upper()
    assert "119,00" in text or "119.00" in text


@ocr_installed
def test_extract_text_uses_ocr_for_images(tmp_path):
    img_path = tmp_path / "beleg.jpg"
    _make_receipt_image(img_path, ["WERKSTATT MUELLER", "SUMME 842,50"])
    text = extract_text(img_path)
    assert text is not None
    assert "WERKSTATT" in text.upper()


def test_extract_text_none_for_unknown_type(tmp_path):
    path = tmp_path / "daten.xyz"
    path.write_bytes(b"whatever")
    assert extract_text(path) is None


def test_ocr_graceful_without_tesseract(tmp_path, monkeypatch):
    """Ohne Tesseract liefern alle OCR-Funktionen still None."""
    monkeypatch.setattr(ocr, "ocr_available", lambda: False)
    img = tmp_path / "scan.png"
    img.write_bytes(b"not a real png")
    assert ocr.ocr_image(img) is None
    assert ocr.ocr_pdf(tmp_path / "scan.pdf") is None


@ocr_installed
def test_scanned_pdf_fallback(tmp_path):
    """PDF ohne Textebene (nur Bild) wird über den OCR-Fallback gelesen."""
    from PIL import Image, ImageDraw
    from PIL import ImageFont

    img = Image.new("L", (900, 300), color=255)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=42)
    except Exception:
        font = None
    draw.text((40, 60), "TUEV BERICHT LKW", fill=0, font=font)
    draw.text((40, 140), "BETRAG 133,70 EUR", fill=0, font=font)
    pdf_path = tmp_path / "scan.pdf"
    img.save(pdf_path, "PDF", resolution=150)

    text = extract_text(pdf_path)
    assert text is not None
    assert "TUEV" in text.upper() or "BERICHT" in text.upper()
