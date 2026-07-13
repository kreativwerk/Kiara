"""Spiegelt archivierte Anhänge nach Google Drive und pflegt den Sync-Status."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Attachment
from . import gdrive
from .gdrive import DriveMirror

log = logging.getLogger("kiara.mirror")


def mirror_attachment(db: Session, mirror: DriveMirror, attachment: Attachment) -> bool:
    """Lädt einen einzelnen Anhang nach Drive. Gibt Erfolg zurück."""
    settings = get_settings()
    local_path = settings.data_dir / attachment.stored_path
    if not local_path.exists():
        return False
    try:
        file_id = mirror.upload_relative(
            attachment.stored_path,
            str(local_path),
            attachment.content_type or "application/octet-stream",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Drive-Upload fehlgeschlagen (%s): %s", attachment.filename, exc)
        return False
    attachment.drive_file_id = file_id
    attachment.drive_synced = True
    db.commit()
    return True


def mirror_all(db: Session, mirror: DriveMirror | None = None) -> tuple[int, int]:
    """Spiegelt alle noch nicht gespiegelten Anhänge. Gibt (erfolg, fehler) zurück."""
    if mirror is None:
        mirror = gdrive.build_mirror(db)
    if mirror is None:
        return 0, 0

    pending = db.execute(
        select(Attachment).where(Attachment.drive_synced.is_(False))
    ).scalars().all()

    ok = 0
    failed = 0
    for attachment in pending:
        if mirror_attachment(db, mirror, attachment):
            ok += 1
        else:
            failed += 1
    return ok, failed
