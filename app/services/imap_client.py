"""IMAP-Anbindung: Verbindung testen und neue Nachrichten samt Anhängen abrufen."""
from __future__ import annotations

import base64
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


def decode_modified_utf7(value: str) -> str:
    """IMAP-Ordnernamen dekodieren: 'Entw&APw-rfe' -> 'Entwürfe'."""
    result: list[str] = []
    i = 0
    while i < len(value):
        char = value[i]
        if char != "&":
            result.append(char)
            i += 1
            continue
        end = value.find("-", i)
        if end == -1:
            result.append(value[i:])
            break
        chunk = value[i + 1:end]
        if not chunk:
            result.append("&")
        else:
            b64 = chunk.replace(",", "/")
            b64 += "=" * ((4 - len(b64) % 4) % 4)
            try:
                result.append(base64.b64decode(b64).decode("utf-16-be"))
            except Exception:
                result.append(value[i:end + 1])
        i = end + 1
    return "".join(result)


def encode_modified_utf7(value: str) -> str:
    """Lesbaren Ordnernamen für IMAP kodieren: 'Entwürfe' -> 'Entw&APw-rfe'."""
    result: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            b64 = (
                base64.b64encode("".join(buffer).encode("utf-16-be"))
                .decode()
                .rstrip("=")
                .replace("/", ",")
            )
            result.append(f"&{b64}-")
            buffer.clear()

    for char in value:
        if 0x20 <= ord(char) <= 0x7E:
            flush()
            result.append("&-" if char == "&" else char)
        else:
            buffer.append(char)
    flush()
    return "".join(result)


def error_text(exc: BaseException) -> str:
    """Lesbare Fehlermeldung: entfernt Python-Bytes-Artefakte wie b'...'."""
    message = exc.args[0] if getattr(exc, "args", None) else exc
    if isinstance(message, (bytes, bytearray)):
        return bytes(message).decode(errors="replace")
    text = str(message)
    match = re.fullmatch(r"b'(.*)'", text)
    return match.group(1) if match else text


def friendly_error(exc: BaseException) -> str:
    """Verständliche deutsche Fehlermeldung ohne Technik-Kauderwelsch.

    Die technischen Details landen im Server-Protokoll (Aufrufer loggt),
    der Nutzer bekommt eine Erklärung mit Handlungstipp.
    """
    raw = error_text(exc).lower()
    if any(k in raw for k in ("authentication", "login", "credential", "password", "anmeld")):
        return (
            "Anmeldung fehlgeschlagen – der Mailserver hat Benutzername oder "
            "Passwort abgelehnt. Tipp: das Postfach-Passwort verwenden (nicht das "
            "Kundenkonto-Passwort). Bei GMX zuerst IMAP in den Einstellungen "
            "erlauben; bei Zwei-Faktor-Anmeldung ein App-Passwort erstellen."
        )
    if "timed out" in raw or "timeout" in raw:
        return (
            "Der Mailserver hat nicht rechtzeitig geantwortet. "
            "Bitte in ein paar Minuten erneut versuchen."
        )
    if "ssl" in raw or "certificate" in raw or "tls" in raw:
        return (
            "Die sichere Verbindung kam nicht zustande. Bitte prüfen: "
            "SSL/TLS-Häkchen gesetzt und Port 993 eingetragen?"
        )
    if any(k in raw for k in ("getaddrinfo", "name or service", "nodename", "not known")):
        return (
            "Der Mailserver wurde nicht gefunden. "
            "Bitte die IMAP-Server-Adresse auf Tippfehler prüfen."
        )
    if "examine" in raw or "select" in raw:
        return (
            "Ein Postfach-Ordner konnte nicht geöffnet werden und wurde übersprungen. "
            "Die übrigen Ordner wurden normal verarbeitet."
        )
    return (
        "Die Synchronisierung ist an einer unerwarteten Server-Antwort gescheitert. "
        "Die technischen Details stehen im Protokoll – einfach erneut versuchen."
    )


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


@dataclass
class Folder:
    raw: str         # Name wie vom Server geliefert (für SELECT verwenden)
    display: str     # lesbarer Name (UTF-7 dekodiert), für Anzeige/Filter
    attributes: str  # z.B. "\\HasNoChildren \\Drafts"

    @property
    def selectable(self) -> bool:
        return "\\noselect" not in self.attributes.lower()

    @property
    def special_junk(self) -> bool:
        """Vom Server als Entwürfe/Gesendet/Spam/Papierkorb markiert."""
        attrs = self.attributes.lower()
        return any(
            flag in attrs
            for flag in ("\\drafts", "\\sent", "\\junk", "\\trash", "\\all", "\\flagged")
        )


# LIST-Antwort: (Attribute) "Trenner" Name  – Name in Anführungszeichen oder als Atom
_LIST_LINE = re.compile(
    r'^\((?P<attrs>[^)]*)\)\s+(?:"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.+)$'
)


def _unquote(name: str) -> str:
    name = name.strip()
    if name.startswith('"') and name.endswith('"') and len(name) >= 2:
        return name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return name


def list_folders(conn) -> list[Folder]:
    typ, data = conn.list()
    folders: list[Folder] = []
    if typ != "OK" or not data:
        return folders
    for raw in data:
        if not raw:
            continue
        if isinstance(raw, tuple):
            # Literal-Form: Name kommt separat als Bytes
            prefix = raw[0].decode(errors="replace") if isinstance(raw[0], bytes) else str(raw[0])
            name = raw[1].decode(errors="replace") if isinstance(raw[1], bytes) else str(raw[1])
            attrs_match = re.search(r"\(([^)]*)\)", prefix)
            attrs = attrs_match.group(1) if attrs_match else ""
        else:
            line = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
            match = _LIST_LINE.match(line.strip())
            if not match:
                log.warning("Ordner-Zeile nicht erkannt: %r", line)
                continue
            attrs = match.group("attrs")
            name = _unquote(match.group("name"))
        if not name:
            continue
        folders.append(Folder(raw=name, display=decode_modified_utf7(name), attributes=attrs))
    return folders


def _select_name(folder: str) -> str:
    """Ordnernamen sicher für SELECT quoten (inkl. Umlaut-Kodierung)."""
    if any(ord(ch) > 0x7E for ch in folder):
        folder = encode_modified_utf7(folder)
    escaped = folder.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def test_connection(
    host: str, port: int, use_ssl: bool, username: str, password: str
) -> tuple[bool, str, list[str]]:
    """Prüft Zugangsdaten und gibt (ok, meldung, ordnerliste) zurück."""
    try:
        with connection(host, port, use_ssl, username, password) as conn:
            folders = list_folders(conn)
        return True, f"Verbindung erfolgreich ({len(folders)} Ordner gefunden).", folders
    except Exception as exc:  # noqa: BLE001
        log.warning("Verbindungstest fehlgeschlagen (%s): %s", host, error_text(exc))
        return False, friendly_error(exc), []


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
    """Iteriert über Nachrichten in ``folder`` mit UID größer als ``since_uid``.

    Ein Ordner, der sich nicht öffnen lässt, wird übersprungen und bricht
    den Sync nicht ab.
    """
    try:
        typ, _ = conn.select(_select_name(folder), readonly=True)
    except imaplib.IMAP4.error as exc:
        log.warning("Ordner übersprungen (%s): %s", folder, error_text(exc))
        return
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
