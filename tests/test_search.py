"""Tests für die smarte Beleg-Suche."""
from decimal import Decimal

from app.models import Attachment, EmailAccount
from app.security import encrypt
from app.services.search import parse_query, search


def _seed(db) -> dict[str, Attachment]:
    account = EmailAccount(
        name="Test",
        host="imap.example.org",
        username="u@example.org",
        password_enc=encrypt("secret"),
    )
    db.add(account)
    db.commit()

    atts = {
        "rechnung": Attachment(
            account_id=account.id,
            filename="Rechnung_Telekom_2026.pdf",
            sha256="1" * 64,
            stored_path="a/1.pdf",
            year=2026,
            month=6,
            category="rechnung",
            detected_amount=Decimal("119.00"),
            sender_email="rechnung@telekom.de",
            subject="Ihre Telekom Rechnung Juni",
            text_content="Telekom Deutschland GmbH Rechnungsbetrag: 119,00 EUR Kundennummer 445566",
        ),
        "tuev": Attachment(
            account_id=account.id,
            filename="TÜV-Bericht_LKW.pdf",
            sha256="2" * 64,
            stored_path="a/2.pdf",
            year=2026,
            month=3,
            category="fahrzeug",
            subject="Hauptuntersuchung MAN TGX",
            text_content="Prüfbericht Hauptuntersuchung Kennzeichen AB-CD 123 ohne Mängel",
        ),
        "werkstatt": Attachment(
            account_id=account.id,
            filename="scan_0042.pdf",
            sha256="3" * 64,
            stored_path="a/3.pdf",
            year=2025,
            month=11,
            category="sonstiges",
            detected_amount=Decimal("842.50"),
            text_content="Werkstattrechnung Bremsen erneuert Gesamtbetrag 842,50 EUR",
        ),
    }
    db.add_all(atts.values())
    db.commit()
    return atts


def test_parse_query_extracts_parts():
    parsed = parse_query("werkstatt juni 2026 119,00")
    assert parsed.tokens == ["werkstatt"]
    assert parsed.month == 6
    assert parsed.year == 2026
    assert parsed.amounts == [Decimal("119.00")]


def test_exact_search(db):
    _seed(db)
    hits = search(db, "telekom")
    assert hits and hits[0].attachment.filename == "Rechnung_Telekom_2026.pdf"


def test_typo_tolerance(db):
    _seed(db)
    # "rechnng" (Tippfehler) findet die Rechnung trotzdem
    hits = search(db, "rechnng telekom")
    assert hits and hits[0].attachment.filename == "Rechnung_Telekom_2026.pdf"


def test_umlaut_normalization(db):
    _seed(db)
    hits = search(db, "tuv")
    assert hits and hits[0].attachment.filename == "TÜV-Bericht_LKW.pdf"


def test_amount_search(db):
    _seed(db)
    hits = search(db, "119,00")
    assert hits and hits[0].attachment.detected_amount == Decimal("119.00")
    # Auch als ganze Zahl:
    hits = search(db, "119")
    assert hits and hits[0].attachment.detected_amount == Decimal("119.00")


def test_fulltext_search_with_snippet(db):
    _seed(db)
    # "bremsen" steht nur IM PDF-Text, nicht in Dateiname/Betreff
    hits = search(db, "bremsen")
    assert hits and hits[0].attachment.filename == "scan_0042.pdf"
    assert "Bremsen" in hits[0].snippet


def test_period_filter(db):
    _seed(db)
    hits = search(db, "juni 2026")
    assert len(hits) == 1
    assert hits[0].attachment.month == 6
    # Zeitraum kombiniert mit Begriff schließt andere Jahre aus
    hits = search(db, "rechnung 2025")
    assert all(h.attachment.year == 2025 for h in hits)


def test_no_results_for_garbage(db):
    _seed(db)
    assert search(db, "zzzzqqqqxxxx") == []


def test_empty_query(db):
    _seed(db)
    assert search(db, "") == []
    assert search(db, "   ") == []


def test_search_page_and_api(client):
    resp = client.get("/search?q=telekom")
    assert resp.status_code == 200
    assert "Suche" in resp.text

    resp = client.get("/api/search", params={"q": "telekom"})
    assert resp.status_code == 200
    assert resp.json() == []
