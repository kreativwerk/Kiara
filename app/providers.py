"""IMAP/SMTP-Voreinstellungen für gängige Anbieter (IONOS, GMX, ...)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    host: str
    port: int = 993
    use_ssl: bool = True
    # SMTP (Versand von System-E-Mails, z.B. Passwort zurücksetzen).
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_ssl: bool = True  # True = SSL (465), False = STARTTLS (587)


PROVIDERS: dict[str, Provider] = {
    "ionos": Provider("ionos", "IONOS", "imap.ionos.de", 993, True, "smtp.ionos.de", 465, True),
    "gmx": Provider("gmx", "GMX", "imap.gmx.net", 993, True, "mail.gmx.net", 465, True),
    "webde": Provider("webde", "WEB.DE", "imap.web.de", 993, True, "smtp.web.de", 587, False),
    "gmail": Provider("gmail", "Gmail", "imap.gmail.com", 993, True, "smtp.gmail.com", 465, True),
    "outlook": Provider(
        "outlook", "Outlook / Office 365", "outlook.office365.com", 993, True,
        "smtp.office365.com", 587, False,
    ),
    "hotmail": Provider(
        "hotmail", "Hotmail / Live", "outlook.office365.com", 993, True,
        "smtp.office365.com", 587, False,
    ),
    "strato": Provider("strato", "STRATO", "imap.strato.de", 993, True, "smtp.strato.de", 465, True),
    "custom": Provider("custom", "Anderer Anbieter", "", 993, True),
}


def get_provider(key: str) -> Provider:
    return PROVIDERS.get(key, PROVIDERS["custom"])
