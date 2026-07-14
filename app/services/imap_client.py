"""IMAP-Anbindung: Verbindung testen und neue Nachrichten samt Anhängen abrufen."""
from __future__ import annotations

import email
import imaplib
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime

log = logging.getLogger("kiara.imap")

IMAP_TIMEOUT = 30


@dataclass
class FetchedAttachment:
    filename: str
    content_type: str
    content: bytes


@dataclass
class FetchedMessage:
    uid: str
    message_id: str | None
    subject: str | None
    sender: str | None
    sender_email: str | None
    sent_at: datetime | None
    attachments: list[FetchedAttachment] = field(default_factory=list)


def error_text(exc: BaseException) -> str:
    """Lesbare Fehlermeldung: entfernt Python-Bytes-Artefakte wie b'...'."""
    message = exc.args[0] if getattr(exc, "args", None) else exc
    if isinstance(message, (bytes, bytearray)):
        return bytes(message).decode(errors="replace")
    text = str(message)
    match = re.fullmatch(r"b'(.*)'", text)
    return match.group(1) if match else text


def _decode(value: str | None) -> str | None:
    if not value:
        return value
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _connect(host: str, port: int, use_ssl: bool, username: str, password: str):
    if use_ssl:
        conn = imaplib.IMAP4_SSL(host, port, timeout=IMAP_TIMEOUT)
    else:
        conn = imaplib.IMAP4(host, port, timeout=IMAP_TIMEOUT)
    conn.login(username, password)
    return conn


@contextmanager
def connection(host: str, port: int, use_ssl: bool, username: str, password: str):
    conn = _connect(host, port, use_ssl, username, password)
    try:
        yield conn
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def list_folders(conn) -> list[str]:
    typ, data = conn.list()
    folders: list[str] = []
    if typ != "OK" or not data:
        return folders
    for raw in data:
        if not raw:
            continue
        line = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
        # Format: (\HasNoChildren) "/" "INBOX"
        parts = line.split(' "')
        name = parts[-1].strip().strip('"')
        if name:
            folders.append(name)
    return folders


def test_connection(
    host: str, port: int, use_ssl: bool, username: str, password: str
) -> tuple[bool, str, list[str]]:
    """Prüft Zugangsdaten und gibt (ok, meldung, ordnerliste) zurück."""
    try:
        with connection(host, port, use_ssl, username, password) as conn:
            folders = list_folders(conn)
        return True, f"Verbindung erfolgreich ({len(folders)} Ordner gefunden).", folders
    except imaplib.IMAP4.error as exc:
        return False, f"IMAP-Fehler: {error_text(exc)}", []
    except Exception as exc:  # noqa: BLE001
        return False, f"Verbindung fehlgeschlagen: {error_text(exc)}", []


def _extract_attachments(msg: Message) -> list[FetchedAttachment]:
    attachments: list[FetchedAttachment] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        if disposition != "attachment" and not filename:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        name = _decode(filename) or "anhang.bin"
        attachments.append(
            FetchedAttachment(
                filename=name,
                content_type=part.get_content_type(),
                content=payload,
            )
        )
    return attachments


def _parse_sender(msg: Message) -> tuple[str | None, str | None]:
    raw = msg.get("From")
    if not raw:
        return None, None
    display = _decode(raw)
    addresses = getaddresses([raw])
    email_addr = addresses[0][1] if addresses else None
    return display, (email_addr or None)


def _parse_date(msg: Message) -> datetime | None:
    raw = msg.get("Date")
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def fetch_messages(
    conn,
    folder: str,
    since_uid: int = 0,
    limit: int = 0,
) -> Iterator[FetchedMessage]:
    """Iteriert über Nachrichten in ``folder`` mit UID größer als ``since_uid``."""
    typ, _ = conn.select(f'"{folder}"', readonly=True)
    if typ != "OK":
        log.warning("Ordner konnte nicht geöffnet werden: %s", folder)
        return

    typ, data = conn.uid("search", None, "ALL")
    if typ != "OK" or not data or not data[0]:
        return

    uids = [int(u) for u in data[0].split()]
    uids = [u for u in uids if u > since_uid]
    uids.sort()
    if limit and limit > 0:
        uids = uids[:limit]

    for uid in uids:
        typ, msg_data = conn.uid("fetch", str(uid), "(RFC822)")
        if typ != "OK" or not msg_data or not msg_data[0]:
            continue
        raw_bytes = msg_data[0][1]
        if not isinstance(raw_bytes, (bytes, bytearray)):
            continue
        msg = email.message_from_bytes(raw_bytes)
        sender, sender_email = _parse_sender(msg)
        yield FetchedMessage(
            uid=str(uid),
            message_id=(msg.get("Message-ID") or None),
            subject=_decode(msg.get("Subject")),
            sender=sender,
            sender_email=sender_email,
            sent_at=_parse_date(msg),
            attachments=_extract_attachments(msg),
        )
