"""Tests für die kompakte Beleg-Übersicht: Rechnungsnummer, Unternehmen, Vorschau."""
from __future__ import annotations

from decimal import Decimal

from app.config import get_settings
from app.models import Attachment, EmailAccount
from app.security import encrypt
from app.services.text_utils import detect_invoice_number, vendor_label


# ---------------------------------------------------------------------------
# Rechnungsnummer-Erkennung
# ---------------------------------------------------------------------------


def test_invoice_number_german_variants():
    assert detect_invoice_number("Rechnungsnummer: RE-2026-0815") == "RE-2026-0815"
    assert detect_invoice_number("Rechnungs-Nr. 4711/2026") == "4711/2026"
    assert detect_invoice_number("Rechnung Nr. 2026-100\nPos 1 ...") == "2026-100"
    assert detect_invoice_number("Beleg-Nr.: B12345") == "B12345"
    assert detect_invoice_number("Rg-Nr. 998877") == "998877"


def test_invoice_number_english_variants():
    assert detect_invoice_number("Invoice No. INV-123") == "INV-123"
    assert detect_invoice_number("Invoice Number: 555001") == "555001"
    assert detect_invoice_number("Invoice # 12-99") == "12-99"


def test_invoice_number_requires_digit():
    # Füllwörter ohne Ziffer werden übersprungen.
    assert detect_invoice_number("Rechnungsnummer: siehe oben") is None
    text = "Rechnungsnummer: siehe unten\nRechnungs-Nr. 2026-42"
    assert detect_invoice_number(text) == "2026-42"


def test_invoice_number_none_without_keyword():
    assert detect_invoice_number("Bestellung 4711 vom 01.02.2026") is None
    assert detect_invoice_number("") is None


def test_invoice_number_strips_trailing_punctuation():
    assert detect_invoice_number("Rechnungsnr. 2026-100.") == "2026-100"


# ---------------------------------------------------------------------------
# Unternehmens-Name (vendor_label)
# ---------------------------------------------------------------------------


def test_vendor_label_from_domain():
    assert vendor_label("rechnung@aral.de", None, "x.pdf") == "Aral"


def test_vendor_label_freemail_falls_back_to_subject():
    assert vendor_label("max@gmx.de", "Rechnung Telekom Mai", "scan.pdf") == "Telekom"


def test_vendor_label_default():
    assert vendor_label(None, None, None) == "Beleg"


# ---------------------------------------------------------------------------
# Vorschau-Route (inline statt Download)
# ---------------------------------------------------------------------------


def _make_attachment(db, org_id, *, sha="d4" * 32, rel="attachments/t/2026/07/pv_test.pdf"):
    account = EmailAccount(
        org_id=org_id, name="V", host="imap.example.org", username="u@example.org",
        password_enc=encrypt("x"),
    )
    db.add(account)
    db.commit()
    settings = get_settings()
    full = settings.data_dir / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(b"%PDF-1.4 vorschau")
    att = Attachment(
        org_id=org_id, account_id=account.id, filename="rechnung.pdf",
        content_type="application/octet-stream",  # typisch für E-Mail-Anhänge
        sha256=sha, stored_path=rel, year=2026, month=7,
        detected_amount=Decimal("99.90"), sender_email="rechnung@aral.de",
        invoice_number="RE-2026-0815",
    )
    db.add(att)
    db.commit()
    return att


def test_view_route_serves_inline_pdf(client, db, org_id):
    att = _make_attachment(db, org_id)
    resp = client.get(f"/attachments/{att.id}/view")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("inline")
    # Trotz octet-stream in der DB wird der echte Typ am Dateinamen erkannt.
    assert resp.headers["content-type"] == "application/pdf"


def test_view_route_blocks_other_org(client, db, org_id):
    att = _make_attachment(db, org_id, sha="e5" * 32, rel="attachments/t/2026/07/fremd.pdf")
    att.org_id = org_id + 999  # gehört einer anderen Organisation
    db.commit()
    resp = client.get(f"/attachments/{att.id}/view", follow_redirects=False)
    assert resp.status_code == 303  # kein Zugriff, zurück zur Liste


# ---------------------------------------------------------------------------
# Kompakte Übersicht
# ---------------------------------------------------------------------------


def test_attachments_page_shows_compact_columns(client, db, org_id):
    att = _make_attachment(db, org_id, sha="f6" * 32, rel="attachments/t/2026/07/liste.pdf")
    resp = client.get("/attachments")
    assert resp.status_code == 200
    assert "Unternehmen" in resp.text
    assert "Rechnungsnr." in resp.text
    assert "Aral" in resp.text  # Unternehmens-Name statt Dateiname
    assert "RE-2026-0815" in resp.text
    assert f"/attachments/{att.id}/view" in resp.text  # Vorschau ist primäre Aktion


def test_recalculate_fills_invoice_number(client, db, org_id):
    account = EmailAccount(
        org_id=org_id, name="R", host="imap.example.org", username="u@example.org",
        password_enc=encrypt("x"),
    )
    db.add(account)
    db.commit()
    att = Attachment(
        org_id=org_id, account_id=account.id, filename="alt.pdf", sha256="a7" * 32,
        stored_path="x/alt.pdf", year=2026, month=6,
        text_content="Rechnung Nr. 2026-100\nRechnungsbetrag 12.845,56 EUR",
    )
    db.add(att)
    db.commit()

    resp = client.post("/settings/recalculate-amounts", follow_redirects=False)
    assert resp.status_code == 303
    db.expire_all()
    refreshed = db.get(Attachment, att.id)
    assert refreshed.invoice_number == "2026-100"
    assert refreshed.detected_amount == Decimal("12845.56")
