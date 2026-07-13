"""IMAP-Voreinstellungen für gängige Anbieter (IONOS, GMX, ...)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    host: str
    port: int = 993
    use_ssl: bool = True


PROVIDERS: dict[str, Provider] = {
    "ionos": Provider("ionos", "IONOS", "imap.ionos.de", 993, True),
    "gmx": Provider("gmx", "GMX", "imap.gmx.net", 993, True),
    "webde": Provider("webde", "WEB.DE", "imap.web.de", 993, True),
    "gmail": Provider("gmail", "Gmail", "imap.gmail.com", 993, True),
    "outlook": Provider("outlook", "Outlook / Office 365", "outlook.office365.com", 993, True),
    "custom": Provider("custom", "Anderer Anbieter", "", 993, True),
}


def get_provider(key: str) -> Provider:
    return PROVIDERS.get(key, PROVIDERS["custom"])
