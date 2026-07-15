"""HTML-Oberfläche von Kiara."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import (
    Attachment,
    BankStatement,
    BankTransaction,
    Email,
    EmailAccount,
    Match,
)
from .. import settings_store as store
from ..providers import PROVIDERS, get_provider
from ..security import encrypt
from ..services import bank_import, gdrive, imap_client, matching, mirror, ocr, search as search_service
from ..services.sync import sync_account, sync_all
from ..templating import templates

router = APIRouter()


def _redirect(path: str, msg: str | None = None, error: bool = False) -> RedirectResponse:
    if msg:
        key = "error" if error else "msg"
        sep = "&" if "?" in path else "?"
        path = f"{path}{sep}{key}={msg}"
    return RedirectResponse(path, status_code=303)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    account_count = db.scalar(select(func.count()).select_from(EmailAccount)) or 0
    attachment_count = db.scalar(select(func.count()).select_from(Attachment)) or 0
    email_count = db.scalar(select(func.count()).select_from(Email)) or 0
    txn_count = db.scalar(select(func.count()).select_from(BankTransaction)) or 0
    matched = db.scalar(select(func.count()).select_from(Match)) or 0
    match_pct = round(matched / txn_count * 100) if txn_count else 0

    by_category = db.execute(
        select(Attachment.category, func.count())
        .group_by(Attachment.category)
        .order_by(func.count().desc())
    ).all()

    recent = db.execute(
        select(Attachment).order_by(Attachment.created_at.desc()).limit(10)
    ).scalars().all()

    accounts = db.execute(select(EmailAccount).order_by(EmailAccount.name)).scalars().all()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "account_count": account_count,
            "attachment_count": attachment_count,
            "email_count": email_count,
            "txn_count": txn_count,
            "matched": matched,
            "match_pct": match_pct,
            "by_category": by_category,
            "recent": recent,
            "accounts": accounts,
            "msg": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
        },
    )


# ---------------------------------------------------------------------------
# Konten
# ---------------------------------------------------------------------------


@router.get("/accounts")
def accounts_page(request: Request, db: Session = Depends(get_db)):
    accounts = db.execute(select(EmailAccount).order_by(EmailAccount.name)).scalars().all()
    return templates.TemplateResponse(
        request,
        "accounts.html",
        {
            "accounts": accounts,
            "providers": PROVIDERS,
            "msg": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/accounts")
def create_account(
    db: Session = Depends(get_db),
    name: str = Form(...),
    provider: str = Form("custom"),
    host: str = Form(""),
    port: int = Form(993),
    use_ssl: bool = Form(False),
    username: str = Form(...),
    password: str = Form(...),
    folders: str = Form("INBOX"),
):
    preset = get_provider(provider)
    resolved_host = host.strip() or preset.host
    if not resolved_host:
        return _redirect("/accounts", "Bitte einen IMAP-Server angeben.", error=True)

    account = EmailAccount(
        name=name.strip(),
        provider=provider,
        host=resolved_host,
        port=port or preset.port,
        use_ssl=bool(use_ssl),
        username=username.strip(),
        password_enc=encrypt(password),
        folders=folders.strip() or "INBOX",
        active=True,
    )
    db.add(account)
    db.commit()
    return _redirect("/accounts", f"Konto '{account.name}' angelegt.")


@router.post("/accounts/{account_id}/test")
def test_account(account_id: int, db: Session = Depends(get_db)):
    account = db.get(EmailAccount, account_id)
    if not account:
        return _redirect("/accounts", "Konto nicht gefunden.", error=True)
    from ..security import decrypt

    ok, message, _ = imap_client.test_connection(
        account.host, account.port, account.use_ssl, account.username, decrypt(account.password_enc)
    )
    return _redirect("/accounts", message, error=not ok)


def _run_sync_account(account_id: int) -> None:
    """Hintergrund-Sync für ein Konto (eigene DB-Session)."""
    from ..database import SessionLocal

    with SessionLocal() as session:
        account = session.get(EmailAccount, account_id)
        if account:
            sync_account(session, account)
            matching.reconcile(session)


def _run_sync_all() -> None:
    from ..database import SessionLocal

    with SessionLocal() as session:
        results = sync_all(session)
        if results:
            matching.reconcile(session)


@router.post("/accounts/{account_id}/sync")
def sync_one(
    account_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    account = db.get(EmailAccount, account_id)
    if not account:
        return _redirect("/accounts", "Konto nicht gefunden.", error=True)
    background_tasks.add_task(_run_sync_account, account_id)
    return _redirect(
        "/accounts",
        f"Synchronisierung für '{account.name}' gestartet – läuft im Hintergrund. "
        "Der Stand erscheint beim Konto, Seite einfach später neu laden.",
    )


@router.post("/accounts/{account_id}/delete")
def delete_account(account_id: int, db: Session = Depends(get_db)):
    account = db.get(EmailAccount, account_id)
    if account:
        db.delete(account)
        db.commit()
    return _redirect("/accounts", "Konto gelöscht.")


@router.get("/accounts/{account_id}/edit")
def edit_account_page(account_id: int, request: Request, db: Session = Depends(get_db)):
    account = db.get(EmailAccount, account_id)
    if not account:
        return _redirect("/accounts", "Konto nicht gefunden.", error=True)
    return templates.TemplateResponse(
        request,
        "account_edit.html",
        {
            "account": account,
            "msg": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/accounts/{account_id}/edit")
def update_account(
    account_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    host: str = Form(...),
    port: int = Form(993),
    use_ssl: bool = Form(False),
    username: str = Form(...),
    password: str = Form(""),
    folders: str = Form("INBOX"),
    active: bool = Form(False),
):
    account = db.get(EmailAccount, account_id)
    if not account:
        return _redirect("/accounts", "Konto nicht gefunden.", error=True)
    account.name = name.strip()
    account.host = host.strip()
    account.port = port
    account.use_ssl = bool(use_ssl)
    account.username = username.strip()
    account.folders = folders.strip() or "INBOX"
    account.active = bool(active)
    if password.strip():
        account.password_enc = encrypt(password)
        account.last_error = None
    db.commit()
    return _redirect("/accounts", f"Konto '{account.name}' aktualisiert.")


@router.post("/sync")
def sync_everything(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    background_tasks.add_task(_run_sync_all)
    return _redirect(
        "/",
        "Synchronisierung aller Konten gestartet – läuft im Hintergrund.",
    )


# ---------------------------------------------------------------------------
# Smarte Suche
# ---------------------------------------------------------------------------


@router.get("/search")
def search_page(request: Request, db: Session = Depends(get_db), q: str = ""):
    q = q.strip()
    hits = search_service.search(db, q) if q else []
    return templates.TemplateResponse(
        request,
        "search.html",
        {"q": q, "hits": hits},
    )


# ---------------------------------------------------------------------------
# Anhänge / Belege
# ---------------------------------------------------------------------------


@router.get("/attachments")
def attachments_page(
    request: Request,
    db: Session = Depends(get_db),
    # Als Strings entgegennehmen: das Filter-Formular schickt leere Werte
    # (""), die als "kein Filter" gelten müssen statt einen Fehler auszulösen.
    account_id: str = "",
    category: str = "",
    year: str = "",
    q: str = "",
):
    account_filter = int(account_id) if account_id.strip().isdigit() else None
    year_filter = int(year) if year.strip().isdigit() else None
    category = category.strip()
    q = q.strip()

    stmt = select(Attachment).order_by(Attachment.year.desc(), Attachment.month.desc())
    if account_filter:
        stmt = stmt.where(Attachment.account_id == account_filter)
    if category:
        stmt = stmt.where(Attachment.category == category)
    if year_filter:
        stmt = stmt.where(Attachment.year == year_filter)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            Attachment.filename.ilike(like) | Attachment.subject.ilike(like)
        )
    attachments = db.execute(stmt.limit(500)).scalars().all()

    accounts = db.execute(select(EmailAccount).order_by(EmailAccount.name)).scalars().all()
    categories = db.execute(
        select(Attachment.category).distinct().order_by(Attachment.category)
    ).scalars().all()
    years = db.execute(
        select(Attachment.year).distinct().order_by(Attachment.year.desc())
    ).scalars().all()

    return templates.TemplateResponse(
        request,
        "attachments.html",
        {
            "attachments": attachments,
            "accounts": accounts,
            "categories": categories,
            "years": [y for y in years if y],
            "f_account": account_filter,
            "f_category": category,
            "f_year": year_filter,
            "f_q": q or "",
        },
    )


@router.get("/attachments/{attachment_id}/download")
def download_attachment(attachment_id: int, db: Session = Depends(get_db)):
    attachment = db.get(Attachment, attachment_id)
    if not attachment:
        return _redirect("/attachments", "Anhang nicht gefunden.", error=True)
    settings = get_settings()
    full_path = settings.data_dir / attachment.stored_path
    if not full_path.exists():
        return _redirect("/attachments", "Datei nicht mehr vorhanden.", error=True)
    return FileResponse(
        str(full_path),
        filename=attachment.filename,
        media_type=attachment.content_type or "application/octet-stream",
    )


# ---------------------------------------------------------------------------
# Bank / Gegenkontrolle
# ---------------------------------------------------------------------------


@router.get("/bank")
def bank_page(request: Request, db: Session = Depends(get_db)):
    from datetime import date as _date

    statements = db.execute(
        select(BankStatement).order_by(
            BankStatement.period_year.desc(), BankStatement.period_month.desc()
        )
    ).scalars().all()
    today = _date.today()
    year_options = list(range(today.year, today.year - 8, -1))

    transactions = db.execute(
        select(BankTransaction).order_by(BankTransaction.booking_date.desc()).limit(500)
    ).scalars().all()

    # Zuordnungen vorbereiten: transaction_id -> Match
    matches = db.execute(select(Match)).scalars().all()
    match_by_txn = {m.transaction_id: m for m in matches}

    total = len(transactions)
    matched = sum(1 for t in transactions if t.id in match_by_txn)

    return templates.TemplateResponse(
        request,
        "bank.html",
        {
            "statements": statements,
            "year_options": year_options,
            "current_month": today.month,
            "transactions": transactions,
            "match_by_txn": match_by_txn,
            "total": total,
            "matched": matched,
            "unmatched": total - matched,
            "msg": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/bank/upload")
async def upload_statement(
    db: Session = Depends(get_db),
    name: str = Form(""),
    period_month: int = Form(...),
    period_year: int = Form(...),
    file: UploadFile = Form(...),
):
    if not (1 <= period_month <= 12) or not (2000 <= period_year <= 2100):
        return _redirect("/bank", "Bitte Monat und Jahr des Auszugs wählen.", error=True)

    content = await file.read()
    if not content:
        return _redirect("/bank", "Leere Datei.", error=True)

    filename = file.filename or "kontoauszug"
    try:
        parsed = bank_import.parse_statement(filename, content)
    except Exception as exc:  # noqa: BLE001
        return _redirect("/bank", f"Datei konnte nicht gelesen werden: {exc}", error=True)

    if not parsed.transactions:
        return _redirect("/bank", "Keine Transaktionen erkannt.", error=True)

    settings = get_settings()
    saved_path = settings.statements_dir / Path(filename).name
    saved_path.write_bytes(content)

    month_names = [
        "", "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
    ]
    statement = BankStatement(
        name=name.strip() or f"Kontoauszug {month_names[period_month]} {period_year}",
        source_filename=filename,
        file_format=parsed.file_format,
        account_iban=parsed.account_iban,
        period_year=period_year,
        period_month=period_month,
    )
    db.add(statement)
    db.flush()

    seen: set[str] = set()
    imported = 0
    for txn in parsed.transactions:
        h = txn.dedupe_hash
        if h in seen:
            continue
        seen.add(h)
        db.add(
            BankTransaction(
                statement_id=statement.id,
                booking_date=txn.booking_date,
                value_date=txn.value_date,
                amount=txn.amount,
                currency=txn.currency,
                counterparty=txn.counterparty,
                purpose=txn.purpose,
                reference=txn.reference,
                dedupe_hash=h,
            )
        )
        imported += 1
    db.commit()

    created = matching.reconcile(db)
    return _redirect(
        "/bank",
        f"{imported} Transaktionen importiert, {created} Belege automatisch zugeordnet.",
    )


@router.post("/bank/statements/{statement_id}/delete")
def delete_statement(statement_id: int, db: Session = Depends(get_db)):
    statement = db.get(BankStatement, statement_id)
    if not statement:
        return _redirect("/bank", "Auszug nicht gefunden.", error=True)
    name = statement.name
    db.delete(statement)  # löscht Transaktionen + Zuordnungen mit (Cascade)
    db.commit()
    return _redirect("/bank", f"Auszug '{name}' samt Transaktionen gelöscht.")


@router.post("/bank/reconcile")
def run_reconcile(db: Session = Depends(get_db)):
    created = matching.reconcile(db)
    return _redirect("/bank", f"Gegenkontrolle aktualisiert: {created} Zuordnungen gefunden.")


@router.get("/bank/assign/{txn_id}")
def assign_page(
    txn_id: int,
    request: Request,
    db: Session = Depends(get_db),
    q: str = "",
):
    txn = db.get(BankTransaction, txn_id)
    if not txn:
        return _redirect("/bank", "Transaktion nicht gefunden.", error=True)

    q = q.strip()
    if q:
        candidates = [hit.attachment for hit in search_service.search(db, q, limit=25)]
    else:
        candidates = matching.suggestions(db, txn)

    return templates.TemplateResponse(
        request,
        "bank_assign.html",
        {
            "txn": txn,
            "candidates": candidates,
            "q": q,
            "msg": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/bank/assign/{txn_id}/{attachment_id}")
def assign_attachment(txn_id: int, attachment_id: int, db: Session = Depends(get_db)):
    txn = db.get(BankTransaction, txn_id)
    attachment = db.get(Attachment, attachment_id)
    if not txn or not attachment:
        return _redirect("/bank", "Transaktion oder Beleg nicht gefunden.", error=True)
    # Bestehende Zuordnung dieser Transaktion ersetzen.
    db.query(Match).filter(Match.transaction_id == txn_id).delete(synchronize_session=False)
    db.add(
        Match(
            transaction_id=txn_id,
            attachment_id=attachment_id,
            score=1.0,
            method="manuell",
            confirmed=True,
        )
    )
    db.commit()
    return _redirect("/bank", f"Beleg '{attachment.filename}' manuell zugeordnet.")


@router.post("/matches/{match_id}/confirm")
def confirm_match(match_id: int, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if match:
        match.confirmed = True
        db.commit()
    return _redirect("/bank", "Zuordnung bestätigt.")


@router.post("/matches/{match_id}/delete")
def delete_match(match_id: int, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if match:
        db.delete(match)
        db.commit()
    return _redirect("/bank", "Zuordnung entfernt.")


# ---------------------------------------------------------------------------
# Einstellungen / Google Drive
# ---------------------------------------------------------------------------


def _drive_redirect_uri(request: Request) -> str:
    return str(request.url_for("google_callback"))


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    unsynced = db.scalar(
        select(func.count()).select_from(Attachment).where(Attachment.drive_synced.is_(False))
    ) or 0
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "drive": gdrive.status(db),
            "ocr_available": ocr.ocr_available(),
            "unsynced": unsynced,
            "msg": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/settings/drive/client-secret")
async def upload_client_secret(db: Session = Depends(get_db), file: UploadFile = Form(...)):
    content = await file.read()
    if not content:
        return _redirect("/settings", "Leere Datei.", error=True)
    try:
        import json

        json.loads(content)  # Validierung: gültiges JSON?
    except Exception:
        return _redirect("/settings", "Keine gültige JSON-Datei.", error=True)
    settings = get_settings()
    (settings.data_dir / "google_client_secret.json").write_bytes(content)
    return _redirect("/settings", "OAuth-Zugangsdaten gespeichert. Jetzt Konto verbinden.")


@router.get("/settings/drive/connect")
def google_connect(request: Request, db: Session = Depends(get_db)):
    if not gdrive.google_libs_available():
        return _redirect("/settings", "Google-Bibliotheken sind nicht installiert.", error=True)
    if not gdrive.has_client_secret():
        return _redirect("/settings", "Bitte zuerst die OAuth-Zugangsdaten hochladen.", error=True)
    try:
        auth_url = gdrive.start_oauth(db, _drive_redirect_uri(request))
    except Exception as exc:  # noqa: BLE001
        return _redirect("/settings", f"OAuth-Start fehlgeschlagen: {exc}", error=True)
    return RedirectResponse(auth_url, status_code=303)


@router.get("/settings/drive/callback", name="google_callback")
def google_callback(request: Request, db: Session = Depends(get_db)):
    try:
        gdrive.finish_oauth(db, _drive_redirect_uri(request), str(request.url))
    except Exception as exc:  # noqa: BLE001
        return _redirect("/settings", f"Verbindung fehlgeschlagen: {exc}", error=True)
    return _redirect("/settings", "Google Drive erfolgreich verbunden.")


@router.post("/settings/drive/toggle")
def toggle_drive(db: Session = Depends(get_db), enabled: bool = Form(False)):
    if enabled and not gdrive.is_connected(db):
        return _redirect("/settings", "Erst Google Drive verbinden.", error=True)
    store.set_bool(db, store.DRIVE_ENABLED, bool(enabled))
    state = "aktiviert" if enabled else "deaktiviert"
    return _redirect("/settings", f"Drive-Spiegelung {state}.")


@router.post("/settings/drive/mirror-now")
def mirror_now(db: Session = Depends(get_db)):
    if not gdrive.is_connected(db):
        return _redirect("/settings", "Google Drive ist nicht verbunden.", error=True)
    drive = gdrive.build_mirror(db)
    if drive is None:
        return _redirect("/settings", "Drive-Verbindung nicht verfügbar.", error=True)
    ok, failed = mirror.mirror_all(db, drive)
    msg = f"{ok} Belege nach Drive gespiegelt."
    if failed:
        msg += f" {failed} fehlgeschlagen."
    return _redirect("/settings", msg, error=failed > 0)


@router.post("/settings/drive/disconnect")
def google_disconnect(db: Session = Depends(get_db)):
    gdrive.disconnect(db)
    return _redirect("/settings", "Google Drive getrennt.")
