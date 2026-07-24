"""Authentifizierung: Benutzerkonten, Passwort-Hashing und Session-Tokens.

Kiara verwendet echte Benutzerkonten (Name, E-Mail, Passwort), aber ohne
öffentliche Registrierung: Der erste Benutzer entsteht bei der Einrichtung
und ist Administrator; weitere Benutzer legen nur Administratoren an.

Bestehende Installationen mit dem alten Einzel-App-Passwort werden
automatisch migriert: Das alte Passwort wird zum Benutzer "admin".
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import settings_store as store
from .models import User
from .security import decrypt, encrypt

AUTH_PASSWORD_KEY = "auth_password_hash"  # Altbestand (Einzel-Passwort)

COOKIE_NAME = "kiara_session"
SESSION_MAX_AGE = 7 * 24 * 3600  # 7 Tage

PBKDF2_ITERATIONS = 240_000
MIN_PASSWORD_LENGTH = 8

LEGACY_ADMIN_EMAIL = "admin"


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
# Benutzerkonten
# ---------------------------------------------------------------------------


def users_exist(db: Session) -> bool:
    return db.execute(select(User.id).limit(1)).first() is not None


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_user(
    db: Session,
    email: str,
    name: str,
    password: str,
    is_admin: bool = False,
) -> User:
    email = normalize_email(email)
    if not email:
        raise ValueError("E-Mail-Adresse fehlt.")
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing is not None:
        raise ValueError("Für diese E-Mail-Adresse gibt es schon ein Konto.")
    user = User(
        email=email,
        name=name.strip() or email,
        password_hash=hash_password(password),
        is_admin=is_admin,
        active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.execute(
        select(User).where(User.email == normalize_email(email))
    ).scalar_one_or_none()
    if user is None or not user.active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def set_password_for(db: Session, user: User, password: str) -> None:
    user.password_hash = hash_password(password)
    db.commit()


def migrate_legacy_password(db: Session) -> None:
    """Altes Einzel-App-Passwort in den Benutzer 'admin' überführen."""
    if users_exist(db):
        return
    legacy_hash = store.get(db, AUTH_PASSWORD_KEY)
    if not legacy_hash:
        return
    user = User(
        email=LEGACY_ADMIN_EMAIL,
        name="Admin",
        password_hash=legacy_hash,  # gleiches Hash-Format, Passwort bleibt gültig
        is_admin=True,
        active=True,
    )
    db.add(user)
    db.commit()


# ---------------------------------------------------------------------------
# Session-Tokens (verschlüsseltes Cookie mit Benutzer-ID)
# ---------------------------------------------------------------------------


def create_session_token(user_id: int) -> str:
    payload = {"uid": user_id, "exp": int(time.time()) + SESSION_MAX_AGE}
    return encrypt(json.dumps(payload))


def verify_session_token(token: str) -> int | None:
    """Gibt die Benutzer-ID zurück, wenn das Token gültig und frisch ist."""
    try:
        payload = json.loads(decrypt(token))
        if int(payload.get("exp", 0)) <= time.time():
            return None
        uid = payload.get("uid")
        return int(uid) if uid is not None else None
    except Exception:
        return None
