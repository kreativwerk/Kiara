"""Speichern, Sortieren und Auswerten von E-Mail-Anhängen."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from ..categorize import categorize
from ..config import get_settings
from . import ocr
from .text_utils import extract_amounts, safe_filename, slugify

log = logging.getLogger("kiara.attachments")

# Liefert pdfplumber weniger Text als das, ist die PDF vermutlich ein Scan.
MIN_TEXT_FOR_NO_OCR = 32


MAX_TEXT_LENGTH = 20_000  # Zeichen Volltext, die pro Beleg gespeichert werden


@dataclass
class StoredFile:
    """Ergebnis des Ablegens eines Anhangs im Dateisystem."""

    sha256: str
    stored_path: Path
    relative_path: str
    size: int
    year: int
    month: int
    category: str
    detected_amount: Decimal | None
    text_content: str | None


def _target_dir(account_name: str, when: datetime) -> Path:
    """Sortierpfad: <attachments>/<konto>/<jahr>/<monat>/ – ideal für die Buchhaltung."""
    settings = get_settings()
    return (
        settings.attachments_dir
        / slugify(account_name)
        / f"{when.year:04d}"
        / f"{when.month:02d}"
    )


def extract_pdf_text(path: Path, max_pages: int = 5) -> str | None:
    """Extrahiert den Text einer PDF (Grundlage für Betragserkennung und Suche)."""
    if path.suffix.lower() != ".pdf":
        return None
    try:
        import pdfplumber  # optionaler, schwergewichtiger Import
    except Exception:  # pragma: no cover - optionale Abhängigkeit fehlt
        return None
    try:
        text_parts: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages[:max_pages]:
                text_parts.append(page.extract_text() or "")
        text = "\n".join(text_parts).strip()
        return text[:MAX_TEXT_LENGTH] or None
    except Exception as exc:  # pragma: no cover - defensiv gegen kaputte PDFs
        log.warning("PDF-Text konnte nicht gelesen werden (%s): %s", path.name, exc)
        return None


def extract_text(path: Path) -> str | None:
    """Bester verfügbarer Text für eine Datei: PDF-Text, sonst OCR.

    - PDF mit echtem Text: pdfplumber (schnell)
    - PDF ohne/mit kaum Text (Scan): OCR über die gerenderten Seiten
    - Bilder (JPG/PNG/HEIC/...): direkt OCR
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = extract_pdf_text(path)
        if text and len(text) >= MIN_TEXT_FOR_NO_OCR:
            return text
        ocr_text = ocr.ocr_pdf(path)
        result = ocr_text or text
        return result[:MAX_TEXT_LENGTH] if result else None
    if suffix in ocr.IMAGE_EXTENSIONS:
        text = ocr.ocr_image(path)
        return text[:MAX_TEXT_LENGTH] if text else None
    return None


def store_attachment(
    *,
    account_name: str,
    filename: str,
    content: bytes,
    when: datetime,
    subject: str | None = None,
) -> StoredFile:
    """Legt einen Anhang dedupliziert und einsortiert im Dateisystem ab."""
    sha256 = hashlib.sha256(content).hexdigest()
    clean_name = safe_filename(filename)
    target_dir = _target_dir(account_name, when)
    target_dir.mkdir(parents=True, exist_ok=True)

    stored_path = target_dir / f"{sha256[:12]}_{clean_name}"
    if not stored_path.exists():
        stored_path.write_bytes(content)

    settings = get_settings()
    relative_path = str(stored_path.relative_to(settings.data_dir))
    category = categorize(clean_name, subject)
    text_content = extract_text(stored_path)
    amounts = extract_amounts(text_content) if text_content else []
    detected_amount = max(amounts) if amounts else None

    return StoredFile(
        sha256=sha256,
        stored_path=stored_path,
        relative_path=relative_path,
        size=len(content),
        year=when.year,
        month=when.month,
        category=category,
        detected_amount=detected_amount,
        text_content=text_content,
    )
