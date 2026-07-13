"""Pydantic-Schemas für die JSON-API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AccountCreate(BaseModel):
    name: str
    provider: str = "custom"
    host: str | None = None
    port: int = 993
    use_ssl: bool = True
    username: str
    password: str
    folders: str = "INBOX"


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider: str
    host: str
    port: int
    use_ssl: bool
    username: str
    folders: str
    active: bool
    last_synced_at: datetime | None = None
    last_error: str | None = None


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    filename: str
    content_type: str | None = None
    size: int
    category: str
    year: int | None = None
    month: int | None = None
    detected_amount: float | None = None
    sender_email: str | None = None
    subject: str | None = None


class SyncResultOut(BaseModel):
    account_id: int
    account_name: str
    new_emails: int
    new_attachments: int
    skipped_duplicates: int
    ok: bool
    message: str


class Stats(BaseModel):
    accounts: int
    emails: int
    attachments: int
    transactions: int
    matches: int


class MessageOut(BaseModel):
    message: str = Field(..., description="Statusmeldung")
