"""Einfache regelbasierte Kategorisierung von Anhängen für die Buchhaltung."""
from __future__ import annotations

# Kategorie -> Stichwörter (in Dateiname oder Betreff, kleingeschrieben).
# Reihenfolge = Priorität: speziellere Kategorien stehen vor allgemeineren
# (z.B. gewinnt "fahrzeug" bei "TÜV-Rechnung" gegen "rechnung").
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fahrzeug": (
        "tüv", "tuev", "hauptuntersuchung", "hu-bericht", "hu_bericht",
        "abgasuntersuchung", "werkstatt", "inspektion", "kfz", "fahrzeug",
        "reifen", "leasing", "tachograph", "dekra",
    ),
    "versicherung": ("versicherung", "police", "versicherungsschein", "schadensmeldung"),
    "mahnung": ("mahnung", "zahlungserinnerung", "reminder"),
    "gutschrift": ("gutschrift", "credit note", "storno"),
    "rechnung": ("rechnung", "invoice", "faktura", "rechnungsnr", "re-nr", "re_nr"),
    "beleg": ("beleg", "quittung", "receipt", "kassenbon", "bon"),
    "vertrag": ("vertrag", "contract", "auftragsbestätigung", "bestellung", "order"),
    "lieferschein": ("lieferschein", "delivery note", "packing"),
    "gehalt": ("gehalt", "lohn", "payslip", "abrechnung", "entgelt"),
    "steuer": ("steuer", "finanzamt", "ustva", "umsatzsteuer", "elster"),
}

# Diese Dateiendungen kommen für Buchhaltungsbelege in Frage.
DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".xml",
    ".csv",
    ".xlsx",
    ".xls",
    ".docx",
    ".doc",
    ".odt",
    ".zip",
    ".heic",
    ".webp",
}


def categorize(filename: str, subject: str | None = None) -> str:
    """Ordnet einen Anhang anhand von Dateiname und Betreff einer Kategorie zu."""
    haystack = f"{filename} {subject or ''}".lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return category
    return "sonstiges"


def is_document(filename: str) -> bool:
    """True, wenn die Dateiendung nach einem Beleg/Dokument aussieht."""
    lower = filename.lower()
    return any(lower.endswith(ext) for ext in DOCUMENT_EXTENSIONS)
