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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kiara", description="Kiara Belegarchiv CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sync", help="Alle aktiven Konten synchronisieren").set_defaults(func=cmd_sync)
    sub.add_parser("reconcile", help="Gegenkontrolle neu berechnen").set_defaults(func=cmd_reconcile)

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
