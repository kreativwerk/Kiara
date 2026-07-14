"""Texterkennung (OCR) für gescannte Belege und Foto-Anhänge.

Optionales Feature nach demselben Muster wie die Drive-Anbindung: Fehlen die
OCR-Werkzeuge (Tesseract-Binary, pytesseract, pypdfium2), liefert alles hier
still ``None`` und Kiara läuft unverändert weiter – nur eben ohne Volltext
für Scans.

Benötigt:
- Systempaket ``tesseract-ocr`` (+ ``tesseract-ocr-deu`` für Deutsch)
- Python: ``pytesseract``, ``pypdfium2`` (PDF-Seiten rendern),
  optional ``pillow-heif`` (iPhone-HEIC-Fotos)
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from ..config import get_settings

log = logging.getLogger("kiara.ocr")

# Bildformate, die direkt per OCR gelesen werden.
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic"}

# Auflösung fürs Rendern gescannter PDF-Seiten (300 dpi = OCR-Standard).
_PDF_RENDER_SCALE = 300 / 72
_MAX_PDF_PAGES = 3


@lru_cache
def ocr_available() -> bool:
    """True, wenn pytesseract UND das Tesseract-Binary nutzbar sind."""
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


@lru_cache
def _lang() -> str:
    """Konfigurierte OCR-Sprachen, gefiltert auf tatsächlich installierte."""
    import pytesseract

    wanted = get_settings().ocr_lang.split("+")
    try:
        installed = set(pytesseract.get_languages(config=""))
    except Exception:
        return "eng"
    usable = [lang for lang in wanted if lang in installed]
    return "+".join(usable) if usable else "eng"


@lru_cache
def _register_heif() -> None:
    """HEIC-Unterstützung für Pillow aktivieren (falls pillow-heif da ist)."""
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except Exception:
        pass


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return cleaned or None


def ocr_image(path: Path) -> str | None:
    """Liest den Text aus einem Bild (Foto/Scan)."""
    if not ocr_available():
        return None
    try:
        import pytesseract
        from PIL import Image

        _register_heif()
        with Image.open(path) as img:
            gray = img.convert("L")  # Graustufen verbessern die Erkennung
            return _clean(pytesseract.image_to_string(gray, lang=_lang()))
    except Exception as exc:  # noqa: BLE001 - defensiv gegen kaputte Bilder
        log.warning("OCR fehlgeschlagen (%s): %s", path.name, exc)
        return None


def ocr_pdf(path: Path, max_pages: int = _MAX_PDF_PAGES) -> str | None:
    """OCR für gescannte PDFs: Seiten rendern, dann Texterkennung."""
    if not ocr_available():
        return None
    try:
        import pypdfium2 as pdfium
        import pytesseract
    except Exception:
        return None
    try:
        parts: list[str] = []
        pdf = pdfium.PdfDocument(str(path))
        try:
            for index, page in enumerate(pdf):
                if index >= max_pages:
                    break
                bitmap = page.render(scale=_PDF_RENDER_SCALE, grayscale=True)
                image = bitmap.to_pil()
                parts.append(pytesseract.image_to_string(image, lang=_lang()))
        finally:
            pdf.close()
        return _clean("\n".join(parts))
    except Exception as exc:  # noqa: BLE001
        log.warning("PDF-OCR fehlgeschlagen (%s): %s", path.name, exc)
        return None
