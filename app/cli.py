"""Kommandozeilen-Werkzeug für Kiara (Sync/Reconcile per Terminal oder Cron)."""
from __future__ import annotations

import argparse
import sys

from .database import SessionLocal, init_db
from .security import encrypt
from .services import matching
from .services.sync import sync_account, sync_all


def cmd_sync(args: argparse.Namespace) -> int:
    init_db()
    with SessionLocal() as db:
        results = sync_all(db)
        if not results:
            print("Keine aktiven Konten.")
            return 0
        for r in results:
            status = "OK" if r.ok else "FEHLER"
            print(f"[{status}] {r.account_name}: {r.message}")
        created = matching.reconcile(db)
        print(f"Gegenkontrolle: {created} Zuordnungen.")
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    init_db()
    with SessionLocal() as db:
        created = matching.reconcile(db)
        print(f"{created} Zuordnungen gefunden.")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    """Nachindexierung: Volltext (inkl. OCR für Scans) für alte Belege extrahieren."""
    from sqlalchemy import select

    from .config import get_settings
    from .models import Attachment
    from .services import ocr
    from .services.attachments import extract_text
    from .services.text_utils import detect_total_amount

    init_db()
    settings = get_settings()
    if not ocr.ocr_available():
        print(
            "Hinweis: Tesseract-OCR ist nicht installiert – Scans/Fotos werden "
            "übersprungen (nur PDFs mit echtem Text werden indexiert)."
        )
    indexed = 0
    skipped = 0
    with SessionLocal() as db:
        pending = db.execute(
            select(Attachment).where(Attachment.text_content.is_(None))
        ).scalars().all()
        total = len(pending)
        for i, att in enumerate(pending, start=1):
            path = settings.data_dir / att.stored_path
            text = extract_text(path) if path.exists() else None
            if not text:
                skipped += 1
                continue
            att.text_content = text
            if att.detected_amount is None:
                att.detected_amount = detect_total_amount(text)
            indexed += 1
            if i % 25 == 0:
                db.commit()
                print(f"... {i}/{total}")
        db.commit()
    print(f"{indexed} Belege indexiert, {skipped} übersprungen (kein Text erkennbar).")
    return 0


def cmd_add_account(args: argparse.Namespace) -> int:
    from .models import EmailAccount
    from .providers import get_provider

    init_db()
    preset = get_provider(args.provider)
    host = args.host or preset.host
    if not host:
        print("Fehler: --host angeben oder bekannten --provider wählen.", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        account = EmailAccount(
            name=args.name,
            provider=args.provider,
            host=host,
            port=args.port or preset.port,
            use_ssl=not args.no_ssl,
            username=args.username,
            password_enc=encrypt(args.password),
            folders=args.folders,
        )
        db.add(account)
        db.commit()
        print(f"Konto '{account.name}' angelegt (id={account.id}).")
    return 0


def cmd_list_users(args: argparse.Namespace) -> int:
    """Alle Benutzer anzeigen (Anmeldename, Rolle, Organisation) – Rettungsanker,
    wenn jemand seinen Anmeldenamen vergessen hat."""
    from .models import Organization, User

    init_db()
    with SessionLocal() as db:
        orgs = {o.id: o.name for o in db.query(Organization).all()}
        users = db.query(User).order_by(User.id).all()
        if not users:
            print("Keine Benutzer vorhanden.")
            return 0
        for u in users:
            role = "Betreiber" if u.is_owner else ("Administrator" if u.is_admin else "Benutzer")
            status = "aktiv" if u.active else "deaktiviert"
            org = orgs.get(u.org_id, "-")
            print(f"{u.email}  ({u.name} | {role} | {status} | Organisation: {org})")
    return 0


def cmd_reset_password(args: argparse.Namespace) -> int:
    """Passwort eines Benutzers neu setzen – Rettungsanker bei Aussperrung."""
    from . import auth
    from .models import User

    if len(args.password) < auth.MIN_PASSWORD_LENGTH:
        print(
            f"Fehler: Passwort braucht mindestens {auth.MIN_PASSWORD_LENGTH} Zeichen.",
            file=sys.stderr,
        )
        return 1
    init_db()
    with SessionLocal() as db:
        user = db.query(User).filter(
            User.email == auth.normalize_email(args.email)
        ).one_or_none()
        if user is None:
            print(f"Fehler: Kein Benutzer mit der E-Mail '{args.email}'.", file=sys.stderr)
            print("Vorhandene Benutzer zeigt: python -m app.cli list-users", file=sys.stderr)
            return 1
        auth.set_password_for(db, user, args.password)
        if not user.active:
            user.active = True
            db.commit()
            print(f"Benutzer '{user.email}' war deaktiviert und wurde wieder aktiviert.")
        print(f"Neues Passwort für '{user.email}' gesetzt – Anmeldung sofort möglich.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kiara", description="Kiara Belegarchiv CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sync", help="Alle aktiven Konten synchronisieren").set_defaults(func=cmd_sync)
    sub.add_parser("reconcile", help="Gegenkontrolle neu berechnen").set_defaults(func=cmd_reconcile)
    sub.add_parser(
        "index", help="PDF-Volltext für ältere Belege nachindexieren (für die Suche)"
    ).set_defaults(func=cmd_index)

    sub.add_parser(
        "list-users", help="Alle Benutzer anzeigen (Anmeldename/Rolle/Organisation)"
    ).set_defaults(func=cmd_list_users)

    reset = sub.add_parser("reset-password", help="Passwort eines Benutzers neu setzen")
    reset.add_argument("email", help="Anmelde-E-Mail des Benutzers")
    reset.add_argument("password", help="Neues Passwort (mind. 8 Zeichen)")
    reset.set_defaults(func=cmd_reset_password)

    add = sub.add_parser("add-account", help="Konto anlegen")
    add.add_argument("--name", required=True)
    add.add_argument("--provider", default="custom")
    add.add_argument("--host", default="")
    add.add_argument("--port", type=int, default=0)
    add.add_argument("--username", required=True)
    add.add_argument("--password", required=True)
    add.add_argument("--folders", default="INBOX")
    add.add_argument("--no-ssl", action="store_true")
    add.set_defaults(func=cmd_add_account)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
