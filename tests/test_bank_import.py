from decimal import Decimal

from app.services import bank_import

CSV_SAMPLE = (
    "Buchungstag;Valuta;Beguenstigter/Zahlungspflichtiger;Verwendungszweck;Betrag;Waehrung\n"
    "01.06.2026;01.06.2026;Muster GmbH;Rechnung 2026-042;-119,00;EUR\n"
    "03.06.2026;03.06.2026;Kunde AG;Zahlung Eingang;1.500,00;EUR\n"
)

CAMT_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
 <BkToCstmrStmt><Stmt>
  <Acct><Id><IBAN>DE02120300000000202051</IBAN></Id></Acct>
  <Ntry>
   <Amt Ccy="EUR">119.00</Amt>
   <CdtDbtInd>DBIT</CdtDbtInd>
   <BookgDt><Dt>2026-06-01</Dt></BookgDt>
   <NtryDtls><TxDtls>
     <RltdPties><Cdtr><Nm>Muster GmbH</Nm></Cdtr></RltdPties>
     <RmtInf><Ustrd>Rechnung 2026-042</Ustrd></RmtInf>
   </TxDtls></NtryDtls>
  </Ntry>
 </Stmt></BkToCstmrStmt>
</Document>
"""

MT940_SAMPLE = (
    ":20:STARTUMSATZ\n"
    ":25:DE02120300000000202051\n"
    ":28C:00001/001\n"
    ":60F:C260601EUR1000,00\n"
    ":61:2606010601DR119,00NTRFNONREF\n"
    ":86:Rechnung 2026-042 Muster GmbH\n"
    ":62F:C260630EUR881,00\n"
)


def test_parse_csv():
    stmt = bank_import.parse_statement("umsatz.csv", CSV_SAMPLE.encode("utf-8"))
    assert stmt.file_format == "csv"
    assert len(stmt.transactions) == 2
    first = stmt.transactions[0]
    assert first.amount == Decimal("-119.00")
    assert first.counterparty == "Muster GmbH"
    assert first.purpose == "Rechnung 2026-042"
    assert stmt.transactions[1].amount == Decimal("1500.00")


def test_parse_camt():
    stmt = bank_import.parse_statement("statement.xml", CAMT_SAMPLE.encode("utf-8"))
    assert stmt.file_format == "camt"
    assert stmt.account_iban == "DE02120300000000202051"
    assert len(stmt.transactions) == 1
    txn = stmt.transactions[0]
    assert txn.amount == Decimal("-119.00")  # DBIT -> negativ
    assert txn.counterparty == "Muster GmbH"
    assert "Rechnung 2026-042" in txn.purpose


def test_parse_mt940():
    stmt = bank_import.parse_statement("auszug.sta", MT940_SAMPLE.encode("utf-8"))
    assert stmt.file_format == "mt940"
    assert len(stmt.transactions) == 1
    txn = stmt.transactions[0]
    assert txn.amount == Decimal("-119.00")
    assert "Rechnung 2026-042" in txn.purpose


def test_dedupe_hash_stable():
    stmt = bank_import.parse_statement("umsatz.csv", CSV_SAMPLE.encode("utf-8"))
    hashes = {t.dedupe_hash for t in stmt.transactions}
    assert len(hashes) == 2
