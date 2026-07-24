"""Synchronisierung: E-Mails abrufen und Anhänge archivieren."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..categorize import is_document
from ..config import get_settings
from ..models import Attachment, Email, EmailAccount
from ..security import decrypt
from . import gdrive, imap_client, mirror
from .attachments import store_attachment

log = logging.getLogger("kiara.sync")

# Bei Ordner-Angabe "*" (alle Ordner) werden diese ausgelassen:
JUNK_FOLDER_KEYWORDS = (
    "spam", "junk", "trash", "papierkorb", "deleted", "gelöscht", "geloescht",
    "entwürfe", "entwuerfe", "draft", "gesendet", "sent", "outbox",
)


def filter_sync_folders(folders: list[str]) -> list[str]:
    """Filtert Spam/Papierkorb/Entwürfe/Gesendet aus einer Ordnerliste."""
    kept = [
        f for f in folders
        if not any(keyword in f.lower() for keyword in JUNK_FOLDER_KEYWORDS)
    ]
    return kept or ["INBOX"]


def _resolve_folders(conn, account: EmailAccount) -> list[str]:
    """Ordnerliste des Kontos; "*" bedeutet: alle Ordner (ohne Junk).

    Junk wird doppelt erkannt: über Server-Markierungen (\\Drafts, \\Sent,
    \\Junk, \\Trash, ...) und über Namens-Stichwörter (dekodiert, damit
    auch "Entwürfe" in IMAP-UTF-7-Schreibweise erkannt wird).
    """
    wanted = account.folder_list
    if "*" not in wanted:
        return wanted
    kept: list[str] = []
    for folder in imap_client.list_folders(conn):
        if not folder.selectable or folder.special_junk:
            continue
        display = folder.display.lower()
        if any(keyword in display for keyword in JUNK_FOLDER_KEYWORDS):
            continue
        kept.append(folder.raw)
    return kept or ["INBOX"]


@dataclass
class SyncResult:
    account_id: int
    account_name: str
    new_emails: int = 0
    new_attachments: int = 0
    skipped_duplicates: int = 0
    ok: bool = True
    message: str = ""
    errors: list[str] = field(default_factory=list)


# Es läuft immer nur EIN Sync gleichzeitig (SQLite hat einen Schreiber) –
# weitere Sync-Anfragen warten hier, statt sich gegenseitig zu stören.
_sync_serializer = threading.Lock()
_pending_lock = threading.Lock()
_pending_accounts: set[int] = set()


def _known_uids(db: Session, account_id: int, folder: str) -> set[int]:
    """Bereits verarbeitete Nachrichten-UIDs eines Ordners."""
    uids = db.execute(
        select(Email.uid).where(
            Email.account_id == account_id, Email.folder == folder
        )
    ).scalars()
    known: set[int] = set()
    for value in uids:
        try:
            known.add(int(value))
        except (TypeError, ValueError):
            continue
    return known


def _known_hashes(db: Session, account_id: int) -> set[str]:
    rows = db.execute(
        select(Attachment.sha256).where(Attachment.account_id == account_id)
    ).scalars()
    return set(rows)


def sync_account(db: Session, account: EmailAccount, max_fetch: int | None = None) -> SyncResult:
    """Ruft neue Nachrichten eines Kontos ab und archiviert deren Anhänge.

    Doppelstart-Schutz: Läuft für dieses Konto bereits ein Sync, wird die
    Anfrage übersprungen; Syncs verschiedener Konten laufen nacheinander.
    """
    with _pending_lock:
        if account.id in _pending_accounts:
            return SyncResult(
                account_id=account.id,
                account_name=account.name,
                message="Synchronisierung läuft bereits – Anfrage übersprungen.",
            )
        _pending_accounts.add(account.id)
    try:
        with _sync_serializer:
            return _do_sync(db, account, max_fetch)
    finally:
        with _pending_lock:
            _pending_accounts.discard(account.id)


def _do_sync(db: Session, account: EmailAccount, max_fetch: int | None = None) -> SyncResult:
    settings = get_settings()
    if max_fetch is None:
        max_fetch = settings.max_fetch

    result = SyncResult(account_id=account.id, account_name=account.name)
    try:
        password = decrypt(account.password_enc)
    except Exception as exc:  # noqa: BLE001
        result.ok = False
        result.message = f"Passwort konnte nicht entschlüsselt werden: {exc}"
        account.last_error = result.message
        account.last_sync_result = result.message
        db.commit()
        return result

    known = _known_hashes(db, account.id)

    try:
        with imap_client.connection(
            account.host, account.port, account.use_ssl, account.username, password
        ) as conn:
            for folder in _resolve_folders(conn, account):
                known_uids = _known_uids(db, account.id, folder)
                since_uid = max(known_uids) if known_uids else 0
                for msg in imap_client.fetch_messages(conn, folder, since_uid, max_fetch):
                    try:
                        uid_int = int(msg.uid)
                    except (TypeError, ValueError):
                        uid_int = None
                    if uid_int is not None and uid_int in known_uids:
                        result.skipped_duplicates += 1
                        continue

                    when = msg.sent_at or datetime.utcnow()
                    try:
                        email_row = Email(
                            account_id=account.id,
                            uid=msg.uid,
                            folder=folder,
                            message_id=msg.message_id,
                            subject=msg.subject,
                            sender=msg.sender,
                            sender_email=msg.sender_email,
                            sent_at=msg.sent_at,
                        )
                        db.add(email_row)
                        db.flush()

                        for att in msg.attachments:
                            if not is_document(att.filename):
                                continue
                            stored = store_attachment(
                                account_name=account.name,
                                filename=att.filename,
                                content=att.content,
                                when=when,
                                subject=msg.subject,
                            )
                            if stored.sha256 in known:
                                result.skipped_duplicates += 1
                                continue
                            known.add(stored.sha256)
                            db.add(
                                Attachment(
                                    org_id=account.org_id,
                                    account_id=account.id,
                                    email_id=email_row.id,
                                    filename=att.filename,
                                    content_type=att.content_type,
                                    size=stored.size,
                                    sha256=stored.sha256,
                                    stored_path=stored.relative_path,
                                    year=stored.year,
                                    month=stored.month,
                                    category=stored.category,
                                    detected_amount=stored.detected_amount,
                                    text_content=stored.text_content,
                                    sender_email=msg.sender_email,
                                    subject=msg.subject,
                                )
                            )
                            result.new_attachments += 1
                        db.commit()
                    except IntegrityError:
                        # Nachricht wurde parallel bereits eingetragen -> überspringen.
                        db.rollback()
                        result.skipped_duplicates += 1
                        continue
                    result.new_emails += 1
                    if uid_int is not None:
                        known_uids.add(uid_int)
        account.last_synced_at = datetime.utcnow()
        account.last_error = None
        result.message = (
            f"{result.new_emails} neue E-Mails, {result.new_attachments} Anhänge archiviert."
        )
        # Optional: neue (und ggf. liegengebliebene) Belege nach Google Drive spiegeln.
        if result.new_attachments and gdrive.is_enabled(db):
            drive = gdrive.build_mirror(db)
            if drive is not None:
                mirrored, _failed = mirror.mirror_all(db, drive)
                if mirrored:
                    result.message += f" {mirrored} nach Drive gespiegelt."
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        result.ok = False
        result.message = imap_client.friendly_error(exc)
        result.errors.append(str(exc))
        account.last_error = result.message
        log.exception("Sync für Konto %s fehlgeschlagen", account.name)
    finally:
        account.last_sync_result = result.message
        db.commit()
    return result


def sync_all(
    db: Session, max_fetch: int | None = None, org_id: int | None = None
) -> list[SyncResult]:
    stmt = select(EmailAccount).where(EmailAccount.active.is_(True))
    if org_id is not None:
        stmt = stmt.where(EmailAccount.org_id == org_id)
    accounts = db.execute(stmt).scalars().all()
    return [sync_account(db, account, max_fetch) for account in accounts]
