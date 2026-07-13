"""Authentifizierung: Passwort-Hashing und Session-Tokens.

Kiara schützt die Oberfläche mit einem einzelnen App-Passwort, das beim
ersten Start festgelegt wird. Das Passwort wird mit PBKDF2 gehasht, die
Session läuft über ein verschlüsseltes Cookie (Fernet) mit Ablaufzeit –
ohne zusätzliche Abhängigkeiten.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time

from sqlalchemy.orm import Session

from . import settings_store as store
from .security import decrypt, encrypt

AUTH_PASSWORD_KEY = "auth_password_hash"

COOKIE_NAME = "kiara_session"
SESSION_MAX_AGE = 7 * 24 * 3600  # 7 Tage

PBKDF2_ITERATIONS = 240_000
MIN_PASSWORD_LENGTH = 8


# ---------------------------------------------------------------------------
# Passwort-Hashing
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, iterations, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(iterations)
        ).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# App-Passwort (Setup / Prüfung)
# ---------------------------------------------------------------------------


def password_is_set(db: Session) -> bool:
    return bool(store.get(db, AUTH_PASSWORD_KEY))


def set_password(db: Session, password: str) -> None:
    store.set_value(db, AUTH_PASSWORD_KEY, hash_password(password))


def check_password(db: Session, password: str) -> bool:
    stored = store.get(db, AUTH_PASSWORD_KEY)
    if not stored:
        return False
    return verify_password(password, stored)


# ---------------------------------------------------------------------------
# Session-Tokens (verschlüsseltes Cookie)
# ---------------------------------------------------------------------------


def create_session_token() -> str:
    payload = {"exp": int(time.time()) + SESSION_MAX_AGE}
    return encrypt(json.dumps(payload))


def verify_session_token(token: str) -> bool:
    try:
        payload = json.loads(decrypt(token))
        return int(payload.get("exp", 0)) > time.time()
    except Exception:
        return False
