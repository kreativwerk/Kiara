"""System-E-Mails (z.B. Passwort zurücksetzen) über ein verbundenes E-Mail-Konto.

Kiara braucht dafür keine eigenen SMTP-Zugangsdaten: Der Betreiber wählt in den
Einstellungen eines der ohnehin verbundenen Konten als Absender; Benutzername
und Passwort sind dort bereits (verschlüsselt) hinterlegt, der SMTP-Server
ergibt sich aus dem Anbieter-Preset.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy.orm import Session

from .. import settings_store as store
from ..models import EmailAccount
from ..providers import get_provider
from ..security import decrypt

log = logging.getLogger("kiara.mailer")

MAIL_ACCOUNT_KEY = "mail_account_id"

SMTP_TIMEOUT = 20


def get_mail_account(db: Session) -> EmailAccount | None:
    """Das als Absender gewählte E-Mail-Konto (oder None)."""
    raw = store.get(db, MAIL_ACCOUNT_KEY)
    if not raw or not raw.isdigit():
        return None
    account = db.get(EmailAccount, int(raw))
    if account is None or account.provider == "manuell":
        return None
    return account


def is_configured(db: Session) -> bool:
    return get_mail_account(db) is not None


def smtp_settings(account: EmailAccount) -> tuple[str, int, bool]:
    """SMTP-Server für ein Konto: Anbieter-Preset, sonst aus dem IMAP-Host geraten."""
    preset = get_provider(account.provider)
    if preset.smtp_host:
        return preset.smtp_host, preset.smtp_port, preset.smtp_ssl
    host = account.host
    if host.startswith("imap"):
        host = "smtp" + host[len("imap"):]
    return host, 465, True


def send_mail(db: Session, to: str, subject: str, body: str) -> None:
    """Verschickt eine System-E-Mail. Wirft RuntimeError mit deutscher Meldung."""
    account = get_mail_account(db)
    if account is None:
        raise RuntimeError(
            "Es ist kein Absender-Konto für System-E-Mails eingerichtet "
            "(Einstellungen → System-E-Mails)."
        )
    host, port, use_ssl = smtp_settings(account)
    try:
        password = decrypt(account.password_enc)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Das Passwort des Absender-Kontos konnte nicht gelesen werden.") from exc

    message = EmailMessage()
    message["From"] = formataddr(("Kiara", account.username))
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT) as smtp:
                smtp.login(account.username, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT) as smtp:
                smtp.starttls()
                smtp.login(account.username, password)
                smtp.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError(
            f"Der E-Mail-Anbieter hat die Anmeldung des Absender-Kontos '{account.name}' "
            "abgelehnt. Prüfe Benutzername/Passwort des Kontos – bei Gmail/Outlook "
            "wird ein App-Passwort benötigt."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        log.warning("E-Mail-Versand über %s fehlgeschlagen: %s", host, exc)
        raise RuntimeError(
            f"Die E-Mail konnte nicht über {host} versendet werden. "
            "Bitte später erneut versuchen oder ein anderes Absender-Konto wählen."
        ) from exc
