from app.categorize import categorize, is_document


def test_categorize_rechnung():
    assert categorize("Rechnung_2026_042.pdf") == "rechnung"
    assert categorize("invoice-123.pdf") == "rechnung"


def test_categorize_by_subject():
    assert categorize("dokument.pdf", "Ihre Mahnung vom 01.06.") == "mahnung"


def test_categorize_default():
    assert categorize("foto.pdf", "Urlaubsgrüße") == "sonstiges"


def test_is_document():
    assert is_document("beleg.PDF")
    assert is_document("scan.jpg")
    assert not is_document("signature.p7s")
    assert not is_document("logo.gif")
