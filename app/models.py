"""ORM-Modelle für Kiara."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class EmailAccount(Base):
    __tablename__ = "email_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(40), default="custom")
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=993)
    use_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    username: Mapped[str] = mapped_column(String(255))
    password_enc: Mapped[str] = mapped_column(Text)
    folders: Mapped[str] = mapped_column(String(255), default="INBOX")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    emails: Mapped[list["Email"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )

    @property
    def folder_list(self) -> list[str]:
        return [f.strip() for f in self.folders.split(",") if f.strip()]


class Email(Base):
    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("account_id", "folder", "uid", name="uq_email_uid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("email_accounts.id"))
    uid: Mapped[str] = mapped_column(String(40))
    folder: Mapped[str] = mapped_column(String(120), default="INBOX")
    message_id: Mapped[str | None] = mapped_column(String(998), nullable=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sender_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    account: Mapped[EmailAccount] = relationship(back_populates="emails")
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="email", cascade="all, delete-orphan"
    )


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        UniqueConstraint("account_id", "sha256", name="uq_attachment_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("email_accounts.id"))
    email_id: Mapped[int | None] = mapped_column(ForeignKey("emails.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    stored_path: Mapped[str] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    month: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(40), default="sonstiges", index=True)
    detected_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    sender_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    drive_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drive_synced: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Extrahierter Textinhalt (PDF), Grundlage für die Volltextsuche.
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    account: Mapped[EmailAccount] = relationship(back_populates="attachments")
    email: Mapped[Email | None] = relationship(back_populates="attachments")
    matches: Mapped[list["Match"]] = relationship(
        back_populates="attachment", cascade="all, delete-orphan"
    )


class BankStatement(Base):
    __tablename__ = "bank_statements"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    source_filename: Mapped[str] = mapped_column(String(500))
    file_format: Mapped[str] = mapped_column(String(20))
    account_iban: Mapped[str | None] = mapped_column(String(40), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    transactions: Mapped[list["BankTransaction"]] = relationship(
        back_populates="statement", cascade="all, delete-orphan"
    )


class BankTransaction(Base):
    __tablename__ = "bank_transactions"
    __table_args__ = (
        UniqueConstraint("statement_id", "dedupe_hash", name="uq_txn_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey("bank_statements.id"))
    booking_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    counterparty: Mapped[str | None] = mapped_column(String(500), nullable=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    dedupe_hash: Mapped[str] = mapped_column(String(64))

    statement: Mapped[BankStatement] = relationship(back_populates="transactions")
    matches: Mapped[list["Match"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan"
    )


class AppSetting(Base):
    """Einfacher Schlüssel-Wert-Speicher für App-Einstellungen (z.B. Drive)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)


class Match(Base):
    """Verknüpfung zwischen einem Anhang (Beleg) und einer Banktransaktion."""

    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("transaction_id", "attachment_id", name="uq_match"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("bank_transactions.id"))
    attachment_id: Mapped[int] = mapped_column(ForeignKey("attachments.id"))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    method: Mapped[str] = mapped_column(String(40), default="auto")
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    transaction: Mapped[BankTransaction] = relationship(back_populates="matches")
    attachment: Mapped[Attachment] = relationship(back_populates="matches")
