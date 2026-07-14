"""JSON-API von Kiara (für Automatisierung / Integrationen)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Attachment, BankTransaction, Email, EmailAccount, Match
from ..providers import get_provider
from ..schemas import (
    AccountCreate,
    AccountOut,
    AttachmentOut,
    MessageOut,
    Stats,
    SyncResultOut,
)
from ..security import encrypt
from ..services import matching
from ..services import search as search_service
from ..services.sync import sync_account, sync_all

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/stats", response_model=Stats)
def stats(db: Session = Depends(get_db)) -> Stats:
    return Stats(
        accounts=db.scalar(select(func.count()).select_from(EmailAccount)) or 0,
        emails=db.scalar(select(func.count()).select_from(Email)) or 0,
        attachments=db.scalar(select(func.count()).select_from(Attachment)) or 0,
        transactions=db.scalar(select(func.count()).select_from(BankTransaction)) or 0,
        matches=db.scalar(select(func.count()).select_from(Match)) or 0,
    )


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db)):
    return db.execute(select(EmailAccount).order_by(EmailAccount.name)).scalars().all()


@router.post("/accounts", response_model=AccountOut, status_code=201)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
    preset = get_provider(payload.provider)
    host = (payload.host or "").strip() or preset.host
    if not host:
        raise HTTPException(status_code=422, detail="IMAP-Host fehlt.")
    account = EmailAccount(
        name=payload.name,
        provider=payload.provider,
        host=host,
        port=payload.port or preset.port,
        use_ssl=payload.use_ssl,
        username=payload.username,
        password_enc=encrypt(payload.password),
        folders=payload.folders or "INBOX",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.post("/accounts/{account_id}/sync", response_model=SyncResultOut)
def sync_one(account_id: int, db: Session = Depends(get_db)):
    account = db.get(EmailAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Konto nicht gefunden.")
    result = sync_account(db, account)
    return SyncResultOut(**result.__dict__)


@router.post("/sync", response_model=list[SyncResultOut])
def sync_all_accounts(db: Session = Depends(get_db)):
    results = sync_all(db)
    if results:
        matching.reconcile(db)
    return [SyncResultOut(**r.__dict__) for r in results]


@router.post("/reconcile", response_model=MessageOut)
def reconcile(db: Session = Depends(get_db)):
    created = matching.reconcile(db)
    return MessageOut(message=f"{created} Zuordnungen gefunden.")


@router.get("/search")
def search_attachments(q: str, db: Session = Depends(get_db), limit: int = 50):
    hits = search_service.search(db, q, limit=min(limit, 200))
    return [
        {
            "id": h.attachment.id,
            "filename": h.attachment.filename,
            "category": h.attachment.category,
            "year": h.attachment.year,
            "month": h.attachment.month,
            "detected_amount": float(h.attachment.detected_amount)
            if h.attachment.detected_amount is not None
            else None,
            "score": h.score,
            "snippet": h.snippet,
        }
        for h in hits
    ]


@router.get("/attachments", response_model=list[AttachmentOut])
def list_attachments(
    db: Session = Depends(get_db),
    account_id: int | None = None,
    category: str | None = None,
    year: int | None = None,
    limit: int = 200,
):
    stmt = select(Attachment).order_by(Attachment.created_at.desc())
    if account_id:
        stmt = stmt.where(Attachment.account_id == account_id)
    if category:
        stmt = stmt.where(Attachment.category == category)
    if year:
        stmt = stmt.where(Attachment.year == year)
    return db.execute(stmt.limit(min(limit, 1000))).scalars().all()
