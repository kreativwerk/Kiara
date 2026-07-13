from decimal import Decimal

from app.services.text_utils import extract_amounts, parse_amount, safe_filename, slugify


def test_parse_amount_german():
    assert parse_amount("1.234,56") == Decimal("1234.56")
    assert parse_amount("99,90") == Decimal("99.90")
    assert parse_amount("-45,00") == Decimal("-45.00")


def test_parse_amount_english():
    assert parse_amount("1,234.56") == Decimal("1234.56")
    assert parse_amount("42.00") == Decimal("42.00")


def test_parse_amount_invalid():
    assert parse_amount("keine zahl") is None
    assert parse_amount("") is None


def test_extract_amounts_finds_largest():
    text = "Zwischensumme 100,00 EUR\nUSt 19,00 EUR\nGesamtbetrag 119,00 EUR"
    amounts = extract_amounts(text)
    assert Decimal("119.00") in amounts
    assert max(amounts) == Decimal("119.00")


def test_slugify():
    assert slugify("Buchhaltung IONOS") == "buchhaltung-ionos"
    assert slugify("Ärger & Co.") == "arger-co"
    assert slugify("") == "konto"


def test_safe_filename():
    assert safe_filename("Rechnung 2024/01.pdf") == "Rechnung_2024_01.pdf"
    assert safe_filename("../../etc/passwd") == "etc_passwd"
    assert safe_filename("") == "anhang.bin"
