"""Google-Drive-Spiegelung des Belegarchivs (optionales Feature).

Der Kern (Ordner-Auflösung, Pfad-Zerlegung, Spiegel-Logik) ist frei von
Google-Abhängigkeiten und damit unabhängig testbar. Die tatsächlichen
Google-API-Aufrufe stecken in ``GoogleDriveBackend`` und werden nur bei
Bedarf (lazy) importiert – so bleibt Kiara auch ohne installierte
Google-Bibliotheken voll lauffähig.
"""
from __future__ import annotations

import json
import logging
from pathlib import PurePosixPath
from typing import Protocol

from sqlalchemy.orm import Session

from .. import settings_store as store
from ..config import get_settings

log = logging.getLogger("kiara.gdrive")

# Minimaler Scope: Kiara sieht/verwaltet nur die von ihm selbst erstellten Dateien.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

FOLDER_MIME = "application/vnd.google-apps.folder"


# ---------------------------------------------------------------------------
# Backend-Schnittstelle (für echte Google-API und Tests)
# ---------------------------------------------------------------------------


class DriveBackend(Protocol):
    def find_folder(self, name: str, parent_id: str) -> str | None: ...
    def create_folder(self, name: str, parent_id: str) -> str: ...
    def upload(self, local_path: str, filename: str, parent_id: str, mimetype: str) -> str: ...


# ---------------------------------------------------------------------------
# Reine, testbare Logik
# ---------------------------------------------------------------------------


def split_relative(relative_path: str) -> tuple[list[str], str]:
    """Zerlegt ``konto/2026/06/datei.pdf`` in (Ordnerteile, Dateiname)."""
    normalized = relative_path.replace("\\", "/")
    pure = PurePosixPath(normalized)
    parts = [p for p in pure.parts if p not in ("", "/")]
    if not parts:
        return [], normalized
    return parts[:-1], parts[-1]


class FolderResolver:
    """Legt geschachtelte Ordner an (mit Cache) und liefert die Ziel-Ordner-ID."""

    def __init__(self, backend: DriveBackend, root_id: str) -> None:
        self.backend = backend
        self.root_id = root_id
        self._cache: dict[tuple[str, ...], str] = {}

    def ensure_path(self, parts: list[str]) -> str:
        parent = self.root_id
        key: tuple[str, ...] = ()
        for part in parts:
            key = key + (part,)
            cached = self._cache.get(key)
            if cached is not None:
                parent = cached
                continue
            folder_id = self.backend.find_folder(part, parent) or self.backend.create_folder(
                part, parent
            )
            self._cache[key] = folder_id
            parent = folder_id
        return parent


class DriveMirror:
    """Spiegelt Dateien anhand ihres relativen Pfades nach Google Drive."""

    def __init__(self, backend: DriveBackend, root_id: str) -> None:
        self.backend = backend
        self.resolver = FolderResolver(backend, root_id)

    def upload_relative(self, relative_path: str, local_path: str, mimetype: str) -> str:
        parts, filename = split_relative(relative_path)
        folder_id = self.resolver.ensure_path(parts)
        return self.backend.upload(local_path, filename, folder_id, mimetype)


# ---------------------------------------------------------------------------
# Echter Google-Drive-Backend (lazy imports)
# ---------------------------------------------------------------------------


class GoogleDriveBackend:
    def __init__(self, service) -> None:
        self._service = service

    @staticmethod
    def _escape(name: str) -> str:
        return name.replace("\\", "\\\\").replace("'", "\\'")

    def find_folder(self, name: str, parent_id: str) -> str | None:
        query = (
            f"name = '{self._escape(name)}' and mimeType = '{FOLDER_MIME}' "
            f"and '{parent_id}' in parents and trashed = false"
        )
        result = (
            self._service.files()
            .list(q=query, spaces="drive", fields="files(id, name)")
            .execute()
        )
        files = result.get("files", [])
        return files[0]["id"] if files else None

    def create_folder(self, name: str, parent_id: str) -> str:
        metadata = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        folder = self._service.files().create(body=metadata, fields="id").execute()
        return folder["id"]

    def upload(self, local_path: str, filename: str, parent_id: str, mimetype: str) -> str:
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(local_path, mimetype=mimetype, resumable=False)
        metadata = {"name": filename, "parents": [parent_id]}
        created = (
            self._service.files()
            .create(body=metadata, media_body=media, fields="id")
            .execute()
        )
        return created["id"]


# ---------------------------------------------------------------------------
# High-Level: Status, Verbindung, Aufbau der Spiegelung
# ---------------------------------------------------------------------------


def _client_secret_path():
    return get_settings().data_dir / "google_client_secret.json"


def has_client_secret() -> bool:
    return _client_secret_path().exists()


def is_connected(db: Session) -> bool:
    return bool(store.get_secret(db, store.DRIVE_TOKEN))


def is_enabled(db: Session) -> bool:
    return store.get_bool(db, store.DRIVE_ENABLED, default=False)


def status(db: Session) -> dict:
    return {
        "client_secret": has_client_secret(),
        "connected": is_connected(db),
        "enabled": is_enabled(db),
        "root_folder": store.get(db, store.DRIVE_ROOT_FOLDER, store.DEFAULT_ROOT_FOLDER),
        "google_libs": google_libs_available(),
    }


def google_libs_available() -> bool:
    try:
        import google.oauth2.credentials  # noqa: F401
        import googleapiclient.discovery  # noqa: F401
        import google_auth_oauthlib.flow  # noqa: F401

        return True
    except Exception:
        return False


def _load_credentials(db: Session):
    """Lädt und erneuert bei Bedarf die gespeicherten OAuth-Zugangsdaten."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_json = store.get_secret(db, store.DRIVE_TOKEN)
    if not token_json:
        return None
    creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        store.set_secret(db, store.DRIVE_TOKEN, creds.to_json())
    return creds


def build_service(db: Session):
    """Erzeugt einen authentifizierten Drive-Service oder ``None``."""
    if not google_libs_available():
        return None
    creds = _load_credentials(db)
    if creds is None:
        return None
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _ensure_root_folder(db: Session, backend: DriveBackend) -> str:
    """Ermittelt (oder erstellt) den Wurzelordner und merkt sich seine ID."""
    root_id = store.get(db, store.DRIVE_ROOT_FOLDER_ID)
    if root_id:
        return root_id
    name = store.get(db, store.DRIVE_ROOT_FOLDER, store.DEFAULT_ROOT_FOLDER)
    root_id = backend.find_folder(name, "root") or backend.create_folder(name, "root")
    store.set_value(db, store.DRIVE_ROOT_FOLDER_ID, root_id)
    return root_id


def build_mirror(db: Session) -> DriveMirror | None:
    """Baut eine einsatzbereite ``DriveMirror`` oder ``None`` (nicht verbunden)."""
    service = build_service(db)
    if service is None:
        return None
    backend = GoogleDriveBackend(service)
    root_id = _ensure_root_folder(db, backend)
    return DriveMirror(backend, root_id)


# ---------------------------------------------------------------------------
# OAuth-Flow (Web)
# ---------------------------------------------------------------------------


def _build_flow(redirect_uri: str):
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_secrets_file(
        str(_client_secret_path()), scopes=SCOPES, redirect_uri=redirect_uri
    )


def start_oauth(db: Session, redirect_uri: str) -> str:
    """Startet den OAuth-Flow und gibt die Google-Zustimmungs-URL zurück."""
    flow = _build_flow(redirect_uri)
    auth_url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    store.set_value(db, store.DRIVE_OAUTH_STATE, state)
    return auth_url


def finish_oauth(db: Session, redirect_uri: str, full_callback_url: str) -> None:
    """Schließt den OAuth-Flow ab und speichert das (verschlüsselte) Token."""
    flow = _build_flow(redirect_uri)
    flow.fetch_token(authorization_response=full_callback_url)
    creds = flow.credentials
    store.set_secret(db, store.DRIVE_TOKEN, creds.to_json())
    store.delete(db, store.DRIVE_OAUTH_STATE)


def disconnect(db: Session) -> None:
    """Trennt die Drive-Verbindung (Token + gemerkte Ordner-ID entfernen)."""
    store.delete(db, store.DRIVE_TOKEN)
    store.delete(db, store.DRIVE_ROOT_FOLDER_ID)
    store.set_bool(db, store.DRIVE_ENABLED, False)
