"""Verschlüsselung der IMAP-Zugangsdaten (ruhende Daten)."""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet

from .config import get_settings


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.secret_key.strip()
    if not key:
        # Schlüssel dauerhaft im Datenverzeichnis ablegen, damit verschlüsselte
        # Passwörter nach einem Neustart weiterhin entschlüsselt werden können.
        key_file = settings.key_file
        if key_file.exists():
            key = key_file.read_text(encoding="utf-8").strip()
        else:
            key = Fernet.generate_key().decode()
            key_file.write_text(key, encoding="utf-8")
            key_file.chmod(0o600)
    return Fernet(key.encode())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
