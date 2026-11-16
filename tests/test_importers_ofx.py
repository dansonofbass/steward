from datetime import date
from pathlib import Path

import pytest

from steward.services.importers.base import ParseError, ParsedRow
from steward.services.importers.ofx import parse_ofx, statements
from tests.bank_files import text as bank_text

SAMPLE = Path(__file__).parent / "samples" / "sample.qfx"


def test_parse_sgml_qfx():
    rows = parse_ofx(SAMPLE.read_text())
    assert rows == [
        ParsedRow(date(2026, 10, 3), -5412, "GREENLEAF MARKET #12 — POS PURCHASE", "2026100300001"),
        ParsedRow(date(2026, 10, 1), 412000, "PAYROLL ACME CORP", "2026100100007"),
        ParsedRow(date(2026, 10, 5), -100000, "TRANSFER TO SAVINGS", "2026100500003"),
    ]


def test_parse_xml_ofx2():
    xml = """<?xml version="1.0"?><?OFX OFXHEADER="200" VERSION="220"?>
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260915</DTPOSTED><TRNAMT>-9.99</TRNAMT><FITID>X1</FITID><NAME>STREAMFLIX</NAME></STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"""
    assert parse_ofx(xml) == [ParsedRow(date(2026, 9, 15), -999, "STREAMFLIX", "X1")]


def test_memo_equal_to_name_not_repeated():
    rows = parse_ofx(SAMPLE.read_text())
    assert rows[2].raw_description == "TRANSFER TO SAVINGS"


def test_bad_amount_is_parse_error():
    bad = "<OFX><STMTTRN><DTPOSTED>20260915<TRNAMT>abc<FITID>1<NAME>X</STMTTRN></OFX>"
    with pytest.raises(ParseError) as e:
        parse_ofx(bad)
    assert e.value.row == 1


def test_missing_fitid_gives_none():
    rows = parse_ofx("<OFX><STMTTRN><DTPOSTED>20260915<TRNAMT>-1.00<NAME>X</STMTTRN></OFX>")
    assert rows[0].external_id is None


def test_bom_prefixed_file_parses():
    assert len(parse_ofx("﻿" + SAMPLE.read_text())) == 3


def test_memo_without_name_uses_memo():
    rows = parse_ofx("<OFX><STMTTRN><DTPOSTED>20260915<TRNAMT>-1.00<MEMO>JUST A MEMO</STMTTRN></OFX>")
    assert rows[0].raw_description == "JUST A MEMO"


def test_entities_are_unescaped():
    rows = parse_ofx("<OFX><STMTTRN><DTPOSTED>20260915<TRNAMT>-1.00<NAME>AT&amp;T</STMTTRN></OFX>")
    assert rows[0].raw_description == "AT&T"


def test_no_transactions_is_parse_error():
    with pytest.raises(ParseError) as e:
        parse_ofx("<OFX></OFX>")
    assert e.value.row == 0
    assert str(e.value) == "No transactions were found in this OFX/QFX file."


def test_missing_date_message_is_plain_words():
    with pytest.raises(ParseError) as e:
        parse_ofx("<OFX><STMTTRN><TRNAMT>-1.00<NAME>X</STMTTRN></OFX>")
    assert str(e.value) == "Transaction 1: this transaction is missing its date (DTPOSTED)."
    assert e.value.row == 1


def test_bad_amount_message_is_plain_words():
    with pytest.raises(ParseError) as e:
        parse_ofx("<OFX><STMTTRN><DTPOSTED>20260915<TRNAMT>abc<NAME>X</STMTTRN></OFX>")
    assert str(e.value) == "Transaction 1: the amount 'abc' isn't a dollar amount."



def test_one_statement_and_its_hint_key():
    [s] = statements(bank_text("bank.ofx"))
    assert (s.last4, s.hint_key, s.card, len(s.rows), s.errors) == ("6789", "ofx:121000000:6789", False, 3, ())
    assert s.rows[0] == ParsedRow(date(2024, 10, 14), -5412, "GREENLEAF MARKET — POS PURCHASE", "202410140001")


def test_a_qfx_card_statement_uses_the_fi_org():
    [s] = statements(bank_text("card.qfx"))
    assert (s.last4, s.hint_key, s.card, [r.amount_cents for r in s.rows]) == ("1234", "ofx:B1:1234", True, [-8412, 50000])


def test_two_accounts_become_two_statements():
    a, b = statements(bank_text("two-accounts.ofx"))
    assert (a.hint_key, b.hint_key) == ("ofx:HARBORCU:1111", "ofx:HARBORCU:2222")
    assert ([r.external_id for r in a.rows], [r.external_id for r in b.rows]) == (["A-1", "A-2"], ["B-1", "B-2"])


def test_a_bad_transaction_is_listed_and_the_rest_are_kept():
    text = bank_text("bank.ofx").replace("<TRNAMT>2100.00", "<TRNAMT>lots")
    [s] = statements(text)
    assert len(s.rows) == 2
    assert [e.text for e in s.errors] == ["Transaction 2: the amount 'lots' isn't a dollar amount."]


def test_the_full_account_number_is_never_kept():
    for name in ("bank.ofx", "card.qfx", "two-accounts.ofx"):
        kept = repr(statements(bank_text(name)))
        assert "0000456789" not in kept and "0000000000001234" not in kept and "0000001111" not in kept
