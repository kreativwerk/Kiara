"""Tests für Endbetrag-Erkennung, Download-Namensschema und manuellen Upload."""
from __future__ import annotations

from decimal import Decimal

from app.config import get_settings
from app.models import Attachment, EmailAccount
from app.security import encrypt
from app.services.text_utils import detect_total_amount


# ---------------------------------------------------------------------------
# Endbetrag statt größter Betrag
# ---------------------------------------------------------------------------

INVOICE_WITH_BIG_POSITION = """Rechnung Nr. 2026-100
Pos 1  Ersatzteil XYZ         15.000,00
Pos 2  Rabatt                 -3.500,00
Zwischensumme                 11.500,00
zzgl. 19% USt.                 1.345,56
Rechnungsbetrag               12.845,56 EUR
"""


def test_detect_total_prefers_keyword_over_max():
    # Größter Betrag ist die Position (15.000,00) - richtig ist der Rechnungsbetrag.
    assert detect_total_amount(INVOICE_WITH_BIG_POSITION) == Decimal("12845.56")


def test_detect_total_weak_keyword():
    text = "Pos 1 100,00\nPos 2 900,00\nGesamt 1.000,00"
    assert detect_total_amount(text) == Decimal("1000.00")


def test_detect_total_amount_on_next_line():
    text = "Zahlbetrag\n499,99 EUR\nPos 800,00"
    assert detect_total_amount(text) == Decimal("499.99")


def test_detect_total_fallback_max():
    text = "irgendwas 12,00 und 99,00 ohne Schlüsselwörter"
    assert detect_total_amount(text) == Decimal("99.00")


def test_detect_total_none():
    assert detect_total_amount("kein Geld weit und breit") is None


# ---------------------------------------------------------------------------
# Download-Namensschema BETRAG_Gläubiger
# ---------------------------------------------------------------------------


def test_download_filename_scheme(client, db, org_id):
    account = EmailAccount(
        org_id=org_id, name="T", host="imap.example.org", username="u@example.org",
        password_enc=encrypt("x"),
    )
    db.add(account)
    db.commit()

    settings = get_settings()
    rel = "attachments/t/2026/07/abc_tank.pdf"
    full = settings.data_dir / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(b"%PDF-1.4 test")

    att = Attachment(
        org_id=org_id,
        account_id=account.id,
        filename="tankrechnung.pdf",
        sha256="a1" * 32,
        stored_path=rel,
        year=2026, month=7,
        detected_amount=Decimal("12845.56"),
        sender_email="rechnung@aral.de",
    )
    db.add(att)
    db.commit()

    resp = client.get(f"/attachments/{att.id}/download")
    assert resp.status_code == 200
    disposition = resp.headers["content-disposition"]
    assert "12.845,56_Aral.pdf" in disposition.replace("%2C", ",").replace("%2E", ".")


def test_download_filename_fallback_without_amount(client, db, org_id):
    account = EmailAccount(
        org_id=org_id, name="T2", host="imap.example.org", username="u@example.org",
        password_enc=encrypt("x"),
    )
    db.add(account)
    db.commit()
    settings = get_settings()
    rel = "attachments/t/2026/07/xyz_foto.jpg"
    full = settings.data_dir / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(b"jpegdata")
    att = Attachment(
        org_id=org_id, account_id=account.id, filename="foto.jpg", sha256="b2" * 32,
        stored_path=rel, year=2026, month=7,
    )
    db.add(att)
    db.commit()

    resp = client.get(f"/attachments/{att.id}/download")
    assert resp.status_code == 200
    assert "foto.jpg" in resp.headers["content-disposition"]


# ---------------------------------------------------------------------------
# Manueller Upload
# ---------------------------------------------------------------------------


def test_manual_upload_creates_attachment(client, db):
    resp = client.post(
        "/attachments/upload",
        data={"period_month": "6", "period_year": "2026"},
        files={"files": ("TUEV_Bericht.pdf", b"%PDF-1.4 fake", "application/pdf")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "hochgeladen" in resp.headers["location"]

    db.expire_all()
    att = db.query(Attachment).one()
    assert att.filename == "TUEV_Bericht.pdf"
    assert att.year == 2026 and att.month == 6
    assert att.category == "fahrzeug"

    manual = db.query(EmailAccount).filter_by(provider="manuell").one()
    assert att.account_id == manual.id
    assert manual.active is False  # wird nie synchronisiert


def test_manual_upload_skips_duplicates(client, db):
    payload = {"period_month": "6", "period_year": "2026"}
    file_tuple = ("beleg.pdf", b"%PDF-1.4 gleicher inhalt", "application/pdf")
    client.post("/attachments/upload", data=payload, files={"files": file_tuple})
    resp = client.post(
        "/attachments/upload", data=payload, files={"files": file_tuple},
        follow_redirects=False,
    )
    assert "vorhanden" in resp.headers["location"]
    db.expire_all()
    assert db.query(Attachment).count() == 1


def test_manual_account_hidden_from_accounts_page(client):
    client.post(
        "/attachments/upload",
        data={"period_month": "6", "period_year": "2026"},
        files={"files": ("x.pdf", b"%PDF-1.4 x", "application/pdf")},
    )
    resp = client.get("/accounts")
    assert "Manuelle Uploads" not in resp.text


# ---------------------------------------------------------------------------
# Wartung: Beträge neu erkennen
# ---------------------------------------------------------------------------


def test_recalculate_amounts(client, db, org_id):
    account = EmailAccount(
        org_id=org_id, name="T3", host="imap.example.org", username="u@example.org",
        password_enc=encrypt("x"),
    )
    db.add(account)
    db.commit()
    att = Attachment(
        org_id=org_id, account_id=account.id, filename="alt.pdf", sha256="c3" * 32,
        stored_path="x/alt.pdf", year=2026, month=6,
        detected_amount=Decimal("15000.00"),  # alter, falscher Wert (Position)
        text_content=INVOICE_WITH_BIG_POSITION,
    )
    db.add(att)
    db.commit()

    resp = client.post("/settings/recalculate-amounts", follow_redirects=False)
    assert resp.status_code == 303
    db.expire_all()
    assert db.get(Attachment, att.id).detected_amount == Decimal("12845.56")
