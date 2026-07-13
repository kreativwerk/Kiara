"""Synchronisierung: E-Mails abrufen und Anhänge archivieren."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..categorize import is_document
from ..config import get_settings
from ..models import Attachment, Email, EmailAccount
from ..security import decrypt
from . import imap_client
from .attachments import store_attachment

log = logging.getLogger("kiara.sync")


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


def _last_uid(db: Session, account_id: int, folder: str) -> int:
    uids = db.execute(
        select(Email.uid).where(
            Email.account_id == account_id, Email.folder == folder
        )
    ).scalars()
    highest = 0
    for value in uids:
        try:
            highest = max(highest, int(value))
        except (TypeError, ValueError):
            continue
    return highest


def _known_hashes(db: Session, account_id: int) -> set[str]:
    rows = db.execute(
        select(Attachment.sha256).where(Attachment.account_id == account_id)
    ).scalars()
    return set(rows)


def sync_account(db: Session, account: EmailAccount, max_fetch: int | None = None) -> SyncResult:
    """Ruft neue Nachrichten eines Kontos ab und archiviert deren Anhänge."""
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
        db.commit()
        return result

    known = _known_hashes(db, account.id)

    try:
        with imap_client.connection(
            account.host, account.port, account.use_ssl, account.username, password
        ) as conn:
            for folder in account.folder_list:
                since_uid = _last_uid(db, account.id, folder)
                for msg in imap_client.fetch_messages(conn, folder, since_uid, max_fetch):
                    when = msg.sent_at or datetime.utcnow()
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
                    result.new_emails += 1

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
                                sender_email=msg.sender_email,
                                subject=msg.subject,
                            )
                        )
                        result.new_attachments += 1
                    db.commit()
        account.last_synced_at = datetime.utcnow()
        account.last_error = None
        result.message = (
            f"{result.new_emails} neue E-Mails, {result.new_attachments} Anhänge archiviert."
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        result.ok = False
        result.message = f"Synchronisierung fehlgeschlagen: {exc}"
        result.errors.append(str(exc))
        account.last_error = result.message
        log.exception("Sync für Konto %s fehlgeschlagen", account.name)
    finally:
        db.commit()
    return result


def sync_all(db: Session, max_fetch: int | None = None) -> list[SyncResult]:
    accounts = db.execute(
        select(EmailAccount).where(EmailAccount.active.is_(True))
    ).scalars().all()
    return [sync_account(db, account, max_fetch) for account in accounts]
