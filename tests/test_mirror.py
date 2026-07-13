"""Tests für die DB-nahe Drive-Spiegelung mit einem Fake-Backend."""
from __future__ import annotations

from app.config import get_settings
from app.models import Attachment, EmailAccount
from app.security import encrypt
from app.services import mirror
from app.services.gdrive import DriveMirror

from tests.test_gdrive import FakeBackend


def _account(db) -> EmailAccount:
    account = EmailAccount(
        name="Test",
        host="imap.example.org",
        username="u@example.org",
        password_enc=encrypt("secret"),
    )
    db.add(account)
    db.commit()
    return account


def _real_attachment(db, account_id: int) -> Attachment:
    settings = get_settings()
    rel = "test/2026/06/abc_rechnung.pdf"
    target = settings.attachments_dir / "test" / "2026" / "06"
    target.mkdir(parents=True, exist_ok=True)
    (target / "abc_rechnung.pdf").write_bytes(b"%PDF-1.4 test")

    att = Attachment(
        account_id=account_id,
        filename="rechnung.pdf",
        content_type="application/pdf",
        sha256="c" * 64,
        stored_path="attachments/" + rel,
        year=2026,
        month=6,
        category="rechnung",
        drive_synced=False,
    )
    db.add(att)
    db.commit()
    return att


def test_mirror_all_uploads_and_marks(db):
    account = _account(db)
    att = _real_attachment(db, account.id)

    backend = FakeBackend()
    drive = DriveMirror(backend, root_id="root")

    ok, failed = mirror.mirror_all(db, drive)
    assert ok == 1
    assert failed == 0
    assert len(backend.uploads) == 1

    db.refresh(att)
    assert att.drive_synced is True
    assert att.drive_file_id is not None


def test_mirror_all_skips_already_synced(db):
    account = _account(db)
    att = _real_attachment(db, account.id)
    att.drive_synced = True
    db.commit()

    backend = FakeBackend()
    drive = DriveMirror(backend, root_id="root")

    ok, failed = mirror.mirror_all(db, drive)
    assert ok == 0
    assert len(backend.uploads) == 0


def test_mirror_missing_file_counts_as_failure(db):
    account = _account(db)
    att = Attachment(
        account_id=account.id,
        filename="weg.pdf",
        content_type="application/pdf",
        sha256="d" * 64,
        stored_path="attachments/test/2026/06/does_not_exist.pdf",
        drive_synced=False,
    )
    db.add(att)
    db.commit()

    backend = FakeBackend()
    drive = DriveMirror(backend, root_id="root")
    ok, failed = mirror.mirror_all(db, drive)
    assert ok == 0
    assert failed == 1
