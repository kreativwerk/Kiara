"""Persistenter Schlüssel-Wert-Speicher für App-Einstellungen."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import AppSetting
from .security import decrypt, encrypt

# Bekannte Schlüssel
DRIVE_ENABLED = "drive_mirror_enabled"
DRIVE_ROOT_FOLDER = "drive_root_folder"
DRIVE_ROOT_FOLDER_ID = "drive_root_folder_id"
DRIVE_TOKEN = "drive_oauth_token"  # verschlüsselt gespeichert
DRIVE_OAUTH_STATE = "drive_oauth_state"

DEFAULT_ROOT_FOLDER = "Kiara"


def get(db: Session, key: str, default: str | None = None) -> str | None:
    row = db.get(AppSetting, key)
    return row.value if row and row.value is not None else default


def set_value(db: Session, key: str, value: str | None) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()


def delete(db: Session, key: str) -> None:
    row = db.get(AppSetting, key)
    if row is not None:
        db.delete(row)
        db.commit()


def get_bool(db: Session, key: str, default: bool = False) -> bool:
    value = get(db, key)
    if value is None:
        return default
    return value in ("1", "true", "True", "yes", "on")


def set_bool(db: Session, key: str, value: bool) -> None:
    set_value(db, key, "1" if value else "0")


def get_secret(db: Session, key: str) -> str | None:
    value = get(db, key)
    if not value:
        return None
    try:
        return decrypt(value)
    except Exception:
        return None


def set_secret(db: Session, key: str, value: str | None) -> None:
    if value is None:
        delete(db, key)
    else:
        set_value(db, key, encrypt(value))
