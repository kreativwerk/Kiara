"""Tests: eigene Sortier-Regeln, Kategorie ändern und Steuerberater-Mappe."""
from __future__ import annotations

import io
import zipfile
from decimal import Decimal

from app.config import get_settings
from app.models import AdvisorItem, Attachment, CategoryRule, EmailAccount
from app.security import encrypt


def _account(db, org_id, name="K"):
    account = EmailAccount(
        org_id=org_id, name=name, host="imap.example.org", username="u@example.org",
        password_enc=encrypt("x"),
    )
    db.add(account)
    db.commit()
    return account


def _attachment(db, org_id, account, *, sha, filename="rechnung.pdf",
                sender="rechnung@aral.de", category="sonstiges",
                amount=None, with_file=False):
    rel = f"attachments/k/2026/07/{sha[:8]}_{filename}"
    if with_file:
        full = get_settings().data_dir / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(b"%PDF-1.4 inhalt " + sha.encode())
    att = Attachment(
        org_id=org_id, account_id=account.id, filename=filename, sha256=sha,
        stored_path=rel, year=2026, month=7, category=category,
        sender_email=sender, detected_amount=amount,
    )
    db.add(att)
    db.commit()
    return att


# ---------------------------------------------------------------------------
# Sortier-Regeln
# ---------------------------------------------------------------------------


def test_rule_applies_retroactively(client, db, org_id):
    account = _account(db, org_id)
    att = _attachment(db, org_id, account, sha="a1" * 32)
    assert att.category == "sonstiges"

    resp = client.post(
        "/settings/rules",
        data={"field": "absender", "pattern": "aral.de", "category": "fahrzeug"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "angewendet" in resp.headers["location"].replace("%20", " ")
    db.expire_all()
    assert db.get(Attachment, att.id).category == "fahrzeug"


def test_first_rule_wins(client, db, org_id):
    account = _account(db, org_id)
    att = _attachment(db, org_id, account, sha="b2" * 32)
    client.post(
        "/settings/rules",
        data={"field": "absender", "pattern": "aral", "category": "fahrzeug"},
    )
    client.post(
        "/settings/rules",
        data={"field": "absender", "pattern": "aral.de", "category": "steuer"},
    )
    db.expire_all()
    # Erste Regel gewinnt, auch nachdem die zweite rückwirkend angewendet wurde.
    assert db.get(Attachment, att.id).category == "fahrzeug"


def test_rule_applies_to_manual_upload(client, db, org_id):
    client.post(
        "/settings/rules",
        data={"field": "datei", "pattern": "sonder", "category": "steuer"},
    )
    client.post(
        "/attachments/upload",
        data={"period_month": "6", "period_year": "2026"},
        files={"files": ("sonderbeleg.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    db.expire_all()
    att = db.query(Attachment).filter(Attachment.filename == "sonderbeleg.pdf").one()
    assert att.category == "steuer"


def test_rule_requires_admin(client, db, org_id):
    client.post(
        "/settings/users",
        data={"name": "Normal", "email": "normal@example.org", "password": "start-passwort-1"},
    )
    client.cookies.clear()
    client.post("/login", data={"email": "normal@example.org", "password": "start-passwort-1"})
    resp = client.post(
        "/settings/rules",
        data={"field": "absender", "pattern": "x", "category": "steuer"},
        follow_redirects=False,
    )
    assert "Administratoren" in resp.headers["location"].replace("%20", " ")
    assert db.query(CategoryRule).count() == 0


def test_delete_rule(client, db, org_id):
    client.post(
        "/settings/rules",
        data={"field": "betreff", "pattern": "police", "category": "versicherung"},
    )
    rule = db.query(CategoryRule).one()
    client.post(f"/settings/rules/{rule.id}/delete", follow_redirects=False)
    db.expire_all()
    assert db.query(CategoryRule).count() == 0


def test_rule_rejects_bad_input(client, db, org_id):
    resp = client.post(
        "/settings/rules",
        data={"field": "absender", "pattern": "x", "category": "gibtsnicht"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert db.query(CategoryRule).count() == 0


# ---------------------------------------------------------------------------
# Kategorie von Hand ändern
# ---------------------------------------------------------------------------


def test_change_category(client, db, org_id):
    account = _account(db, org_id)
    att = _attachment(db, org_id, account, sha="c3" * 32)
    resp = client.post(
        f"/attachments/{att.id}/category", data={"category": "vertrag"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.expire_all()
    assert db.get(Attachment, att.id).category == "vertrag"


def test_change_category_blocks_other_org_and_bad_category(client, db, org_id):
    account = _account(db, org_id)
    att = _attachment(db, org_id, account, sha="d4" * 32)
    client.post(f"/attachments/{att.id}/category", data={"category": "quatschkategorie"})
    db.expire_all()
    assert db.get(Attachment, att.id).category == "sonstiges"

    att.org_id = org_id + 999
    db.commit()
    client.post(f"/attachments/{att.id}/category", data={"category": "vertrag"})
    db.expire_all()
    assert db.get(Attachment, att.id).category == "sonstiges"


# ---------------------------------------------------------------------------
# Steuerberater-Mappe
# ---------------------------------------------------------------------------


def test_advisor_add_page_remove_clear(client, db, org_id):
    account = _account(db, org_id)
    att = _attachment(db, org_id, account, sha="e5" * 32, amount=Decimal("99.90"))

    resp = client.post(f"/steuerberater/add/{att.id}", follow_redirects=False)
    assert resp.status_code == 303
    assert db.query(AdvisorItem).count() == 1

    # Doppelt hineinlegen bleibt bei einem Eintrag.
    client.post(f"/steuerberater/add/{att.id}", follow_redirects=False)
    assert db.query(AdvisorItem).count() == 1

    page = client.get("/steuerberater")
    assert page.status_code == 200
    assert "Aral" in page.text
    assert "ZIP herunterladen" in page.text

    client.post(f"/steuerberater/remove/{att.id}", follow_redirects=False)
    assert db.query(AdvisorItem).count() == 0

    client.post(f"/steuerberater/add/{att.id}", follow_redirects=False)
    client.post("/steuerberater/clear", follow_redirects=False)
    assert db.query(AdvisorItem).count() == 0


def test_advisor_zip_download(client, db, org_id):
    account = _account(db, org_id)
    a1 = _attachment(db, org_id, account, sha="f6" * 32, amount=Decimal("12845.56"), with_file=True)
    a2 = _attachment(
        db, org_id, account, sha="a7" * 32, filename="telekom.pdf",
        sender="billing@telekom.de", amount=Decimal("89.99"), with_file=True,
    )
    client.post(f"/steuerberater/add/{a1.id}")
    client.post(f"/steuerberater/add/{a2.id}")

    resp = client.get("/steuerberater/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "Steuerberater-Belege_" in resp.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
    assert "12.845,56_Aral.pdf" in names
    assert "89,99_Telekom.pdf" in names


def test_advisor_zip_empty_redirects(client, db, org_id):
    resp = client.get("/steuerberater/download", follow_redirects=False)
    assert resp.status_code == 303
    assert "leer" in resp.headers["location"].replace("%20", " ")


def test_advisor_blocks_other_org(client, db, org_id):
    account = _account(db, org_id)
    att = _attachment(db, org_id, account, sha="b8" * 32)
    att.org_id = org_id + 999
    db.commit()
    resp = client.post(f"/steuerberater/add/{att.id}", follow_redirects=False)
    assert "nicht%20gefunden" in resp.headers["location"].replace("+", "%20")
    assert db.query(AdvisorItem).count() == 0


def test_attachments_page_shows_mappe_button(client, db, org_id):
    account = _account(db, org_id)
    _attachment(db, org_id, account, sha="c9" * 32)
    page = client.get("/attachments")
    assert "Steuerberater-Mappe (0)" in page.text
    assert "/steuerberater/add/" in page.text
    assert "cat-select" in page.text  # Kategorie direkt umstellbar
