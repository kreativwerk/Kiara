"""Gemeinsame Jinja2-Template-Konfiguration."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

_MONTHS_DE = [
    "",
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def euro(value: Decimal | float | None) -> str:
    if value is None:
        return "–"
    formatted = f"{float(value):,.2f}"
    # 1,234.56 -> 1.234,56
    formatted = formatted.replace(",", "#").replace(".", ",").replace("#", ".")
    return f"{formatted} €"


def datefmt(value: date | datetime | None) -> str:
    if value is None:
        return "–"
    return value.strftime("%d.%m.%Y")


def monthname(month: int | None) -> str:
    if not month or month < 1 or month > 12:
        return "–"
    return _MONTHS_DE[month]


def vendor(attachment) -> str:
    """Unternehmens-Name eines Belegs (aus Absender, Betreff oder Dateiname)."""
    from .services.text_utils import vendor_label

    return vendor_label(
        getattr(attachment, "sender_email", None),
        getattr(attachment, "subject", None),
        getattr(attachment, "filename", None),
    )


templates.env.filters["euro"] = euro
templates.env.filters["datefmt"] = datefmt
templates.env.filters["monthname"] = monthname
templates.env.filters["vendor"] = vendor
