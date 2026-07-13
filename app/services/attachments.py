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
from .text_utils import extract_amounts, safe_filename, slugify

log = logging.getLogger("kiara.attachments")


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


def _target_dir(account_name: str, when: datetime) -> Path:
    """Sortierpfad: <attachments>/<konto>/<jahr>/<monat>/ – ideal für die Buchhaltung."""
    settings = get_settings()
    return (
        settings.attachments_dir
        / slugify(account_name)
        / f"{when.year:04d}"
        / f"{when.month:02d}"
    )


def extract_pdf_amount(path: Path) -> Decimal | None:
    """Bester Versuch, den (größten) Betrag aus einer PDF-Rechnung zu lesen."""
    if path.suffix.lower() != ".pdf":
        return None
    try:
        import pdfplumber  # optionaler, schwergewichtiger Import
    except Exception:  # pragma: no cover - optionale Abhängigkeit fehlt
        return None
    try:
        text_parts: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages[:5]:
                text_parts.append(page.extract_text() or "")
        amounts = extract_amounts("\n".join(text_parts))
        return max(amounts) if amounts else None
    except Exception as exc:  # pragma: no cover - defensiv gegen kaputte PDFs
        log.warning("PDF-Betrag konnte nicht gelesen werden (%s): %s", path.name, exc)
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
    detected_amount = extract_pdf_amount(stored_path)

    return StoredFile(
        sha256=sha256,
        stored_path=stored_path,
        relative_path=relative_path,
        size=len(content),
        year=when.year,
        month=when.month,
        category=category,
        detected_amount=detected_amount,
    )
