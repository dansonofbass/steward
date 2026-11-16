"""Layout detection (spec, Layout detection; P7-P9, P12, P17, P36, P37): every fixture's state, label, mapping, sign
and date format; the key; title lines never kept; P17's left-out counts and unreadable rows; P37's ids."""
from datetime import date
from pathlib import Path

import pytest

import steward.services.importers as importers_pkg
from steward.services.importers.decode import DECIMAL_COMMA, NO_ROWS, FileRefused, decode
from steward.services.importers.layouts import (CHOOSE_AMOUNT, NOT_UNDERSTOOD, account_digits, check_amounts,
                                                date_format_for, identify, layout_key, mapping_from, parse, read_table,
                                                remembered, sample)
from tests.bank_files import read

TODAY = date(2026, 10, 30)
MDY = "%m/%d/%Y"


def _table(name):
    return read_table(decode(read(name)))


def _layout(name, mine=None):
    t = _table(name)
    return t, identify(t, layout_key(t), mine)


DETECT = {
    "chase-card.csv": ("known", "Chase card", "chase_card", {"date": 0, "description": 2, "amount": 5}, False, MDY),
    "chase-checking.csv": ("known", "Chase checking", "chase_checking", {"date": 1, "description": 2, "amount": 3}, False, MDY),
    "paypal.csv": ("known", "PayPal", "paypal", {"date": 0, "description": 3, "status": 5, "amount": 9, "id": 12}, False, MDY),
    "venmo.csv": ("known", "Venmo", "venmo", {"id": 1, "date": 2, "status": 4, "memo": 5, "amount": 8}, False, "iso-datetime"),
    "amex-extended.csv": ("builtin", "Amex", "amex", {"date": 0, "description": 1, "amount": 4, "id": 11}, True, MDY),
    "discover.csv": ("builtin", "Discover", "discover", {"date": 0, "description": 2, "amount": 3}, True, MDY),
    "boa-card.csv": ("builtin", "Bank of America", "boa_card", {"date": 0, "id": 1, "description": 2, "amount": 4}, False, MDY),
    "citi.csv": ("builtin", "Citi", "citi", {"status": 0, "date": 1, "description": 2, "debit": 3, "credit": 4}, False, MDY),
    "capital-one-card.csv": ("builtin", "Capital One", "capital_one", {"date": 0, "description": 3, "debit": 5, "credit": 6},
                             False, "%Y-%m-%d"),
    "capital-one-360.csv": ("builtin", "Capital One 360", "capital_one_360",
                            {"description": 1, "date": 2, "direction": 3, "amount": 4}, False, "%m/%d/%y"),
    "amex-basic.csv": ("new", None, "layout", {"date": 0, "description": 1, "amount": 2}, None, MDY),
    "first-cu.csv": ("new", None, "layout", {"date": 1, "description": 3, "debit": 4, "credit": 5, "status": 6}, False, MDY),
    "boa-checking.csv": ("new", None, "layout", {"date": 0, "description": 1, "amount": 2}, None, MDY),
    "wells-fargo.csv": ("new", None, "layout", {"date": 0, "amount": 1, "description": 4}, None, MDY),
    "wise-dmy.csv": ("new", None, "layout", {"date": 1, "amount": 2, "description": 4}, None, "%d-%m-%Y"),
    "card-ambiguous.csv": ("new", None, "layout", {"date": 0, "description": 1, "amount": 2}, None, MDY),
    "semicolon.csv": ("new", None, "layout", {"date": 0, "description": 1, "amount": 2}, None, MDY),
    "tab.tsv": ("new", None, "layout", {"date": 0, "description": 1, "amount": 2}, None, MDY),
    "utf16-bom.csv": ("new", None, "layout", {"date": 0, "description": 1, "amount": 2}, None, MDY),
}


@pytest.mark.parametrize("name", list(DETECT))
def test_each_fixture_is_identified(name):
    _, lay = _layout(name)
    assert (lay.state, lay.label, lay.fmt, lay.mapping, lay.negate, lay.date_format) == DETECT[name]


def test_the_ambiguous_dates_are_asked_with_their_example():
    _, lay = _layout("wise-dmy-ambiguous.csv")
    assert (lay.date_format, lay.date_example, lay.date_options) == (None, "03-04-2024", ("%m-%d-%Y", "%d-%m-%Y"))


def test_the_key_is_stable_and_a_reordered_header_is_another():
    assert layout_key(_table("amex-basic.csv")) == "h:9bcfe1f64b691063bb60a855d7736ffcdb199c0b3bd0bd6c782a805d1f4fc7d0"
    assert layout_key(read_table("Description,Date,Amount\nX,10/14/2024,1.00\n")) == \
        "h:d2266349673773d873439b2fc2de0c40b6f3ce6370ff4a430428dc7b44dbedf6"
    assert layout_key(read_table("Trans. Date,Description,Amount (total)\n10/14/2024,X,1\n")) == \
        layout_key(read_table("trans date,DESCRIPTION,amount total\n10/14/2024,X,1\n"))


def test_a_headerless_file_is_keyed_by_its_shapes():
    t = _table("wells-fargo.csv")
    assert t.headerless and t.header == ("Column 1", "Column 2", "Column 3", "Column 4", "Column 5")
    assert layout_key(t) == "n:5:daset"


@pytest.mark.parametrize("name,words", [("venmo.csv", ("@jane-doe", "Account Statement", "Account Activity")),
                                        ("boa-checking.csv", ("Summary Amt", "Total credits", "Ending balance"))])
def test_title_lines_are_never_kept(name, words):
    t, lay = _layout(name)
    kept = repr(t) + repr(lay) + repr(sample(t)) + repr(parse(t, lay, TODAY))
    assert [w for w in words if w in kept] == []


PARSE = {
    "chase-card.csv": (5, (date(2024, 10, 3), -6418, "TRADER JOE'S #552", None), {}),
    "chase-checking.csv": (4, (date(2024, 10, 14), -5412, "GREENLEAF MARKET 0412", None), {}),
    "amex-basic.csv": (10, (date(2024, 10, 2), 650, "BLUE BOTTLE COFFEE", None), {}),
    "amex-extended.csv": (3, (date(2024, 10, 2), -650, "BLUE BOTTLE COFFEE", "csv:320242760012345678"), {}),
    "citi.csv": (3, (date(2024, 10, 2), -8412, "HARBOR GROCERY", None), {"pending": 1}),
    "capital-one-card.csv": (3, (date(2024, 10, 2), -8412, "HARBOR GROCERY", None), {}),
    "capital-one-360.csv": (3, (date(2024, 10, 1), 210000, "Deposit from NORTHWIND PAYROLL", None), {}),
    "discover.csv": (3, (date(2024, 10, 2), -8412, "HARBOR GROCERY", None), {}),
    "wells-fargo.csv": (3, (date(2024, 10, 15), -5412,
                            "PURCHASE AUTHORIZED ON 10/14 GREENLEAF MARKET S000000000 CARD 0000", None), {}),
    "boa-checking.csv": (3, (date(2024, 10, 15), 210000, "NORTHWIND PAYROLL DES:PAYROLL", None), {"balance": 1}),
    "boa-card.csv": (3, (date(2024, 10, 2), -8412, "HARBOR GROCERY", "csv:24692164275100000000001"), {}),
    "first-cu.csv": (3, (date(2024, 10, 14), 210000, "DEPOSIT NORTHWIND PAYROLL", None), {"pending": 1}),
    "paypal.csv": (3, (date(2024, 10, 2), -2499, "Harbor Books", "csv:1AB23456CD789012E"), {"pending": 1, "currency": 1}),
    "venmo.csv": (3, (date(2024, 10, 3), -2500, "Sam Lee — Pizza night", "csv:4110000000000000001"), {"balance": 2}),
    "wise-dmy.csv": (3, (date(2024, 10, 15), -1250, "Card transaction at CAFE LUNE", None), {}),
    "card-ambiguous.csv": (9, (date(2024, 10, 14), 8412, "HARBOR GROCERY", None), {}),
    "utf16-bom.csv": (2, (date(2024, 10, 14), -450, "CAFÉ LUNE", None), {}),
}


@pytest.mark.parametrize("name", list(PARSE))
def test_each_fixture_parses(name):
    t, lay = _layout(name)
    p = parse(t, lay, TODAY)
    n, first, left = PARSE[name]
    r = p.rows[0]
    assert (len(p.rows), (r.posted_at, r.amount_cents, r.raw_description, r.external_id), p.left_out, p.errors) == \
        (n, first, left, ())


def test_split_columns_ignore_the_sign_they_carry_and_a_direction_column_gives_one():
    assert [r.amount_cents for r in parse(*_layout("citi.csv"), TODAY).rows] == [-8412, 50000, -1549]
    assert [r.amount_cents for r in parse(*_layout("first-cu.csv"), TODAY).rows] == [210000, -8412, -25000]
    assert [r.amount_cents for r in parse(*_layout("capital-one-360.csv"), TODAY).rows] == [210000, -8412, -50000]


def test_paypal_falls_back_to_type_and_venmo_names_who_from_the_sign():
    assert parse(*_layout("paypal.csv"), TODAY).rows[1].raw_description == "General Card Deposit"
    assert parse(*_layout("venmo.csv"), TODAY).rows[1].raw_description == "Alex Kim — Rent share"


def test_the_running_balance_is_read_beside_each_row():
    p = parse(*_layout("boa-checking.csv"), TODAY)
    assert (p.balances, p.raw) == ((360000, 354588, 342748), (210000, -5412, -11840))


def test_a_negated_layout_flips_every_amount_and_keeps_the_raw_ones():
    t, lay = _layout("amex-basic.csv")
    p = parse(t, remembered(lay.key, t.header, 4, "Amex", lay.mapping, True, MDY), TODAY)
    assert (p.rows[0].amount_cents, p.rows[1].amount_cents, p.raw[:2]) == (-650, 82000, (650, -82000))


def test_ten_bad_rows_in_two_hundred_import_and_thirty_hold_the_file():
    ok = parse(*_layout("bad-rows.csv"), TODAY)
    assert (len(ok.rows), len(ok.errors), ok.held) == (197, 3, False)
    assert ok.errors[0].text == 'Row 2: the date "13/45/2024" isn\'t a date.'
    held = parse(*_layout("mostly-bad.csv"), TODAY)
    assert (len(held.rows), len(held.errors), held.held) == (170, 30, True)
    assert held.held_text == "30 rows can't be read. Check the columns."


@pytest.mark.parametrize("good,bad,held", [(190, 10, False), (209, 11, True), (189, 10, True)])
def test_the_10_row_and_5_percent_edges(good, bad, held):
    lines = ["Date,Description,Amount"] + [f"10/{(i % 28) + 1:02d}/2024,SHOP {i},-1.00" for i in range(good)]
    lines += ["10/14/2024,BROKEN,abc"] * bad
    t = read_table("\n".join(lines) + "\n")
    p = parse(t, identify(t, layout_key(t)), TODAY)
    assert (len(p.errors), p.held) == (bad, held)
    assert p.errors[0].text.endswith('the amount "abc" isn\'t a dollar amount.')


def test_a_date_after_tomorrow_is_an_unreadable_row():
    p = parse(*_layout("future-date.csv"), TODAY)
    assert [r.posted_at for r in p.rows] == [date(2026, 10, 14), date(2026, 10, 31)]
    assert [e.text for e in p.errors] == ["Row 4: the date is in the future."]


def test_a_row_with_no_amount_says_so():
    t = read_table("Date,Description,Debit,Credit\n10/14/2024,NOTHING,,\n10/15/2024,SHOP,1.00,\n")
    assert [e.text for e in parse(t, identify(t, layout_key(t)), TODAY).errors] == ["Row 2: this row has no amount."]


def test_totals_rows_are_left_out_and_counted_but_a_store_named_total_isnt():
    t = read_table("Date,Description,Amount\n10/14/2024,TOTAL WINE & MORE,-30.00\n,Total,-30.00\n,Total debits,-30.00\n")
    p = parse(t, identify(t, layout_key(t)), TODAY)
    assert ([r.raw_description for r in p.rows], p.left_out) == (["TOTAL WINE & MORE"], {"totals": 2})


def test_an_id_column_is_used_only_when_every_row_has_a_different_one():
    def ids(body):
        t = read_table("Date,Description,Amount,Reference\n" + body)
        return [r.external_id for r in parse(t, identify(t, layout_key(t)), TODAY).rows]
    assert ids("10/14/2024,A,-1.00,R1\n10/15/2024,B,-2.00,R2\n") == ["csv:R1", "csv:R2"]
    assert ids("10/14/2024,A,-1.00,R1\n10/15/2024,B,-2.00,R1\n") == [None, None]
    assert ids("10/14/2024,A,-1.00,R1\n10/15/2024,B,-2.00,\n") == [None, None]


def test_a_direction_column_with_an_unknown_word_is_ignored():
    t = read_table("Date,Description,Amount,Type\n10/14/2024,A,1.00,Debit\n10/15/2024,B,2.00,Adjustment\n")
    lay = identify(t, layout_key(t))
    assert "direction" not in lay.mapping and lay.negate is None


def test_account_numbers_are_masked_in_the_sample_and_their_digits_found():
    t = _table("amex-extended.csv")
    assert [row[3] for row in sample(t)] == ["••••0001"] * 3
    assert account_digits(t) == "0001"
    assert account_digits(_table("amex-basic.csv")) is None


def test_decimal_comma_amounts_are_refused_in_plain_words():
    t, lay = _layout("decimal-comma.csv")
    with pytest.raises(FileRefused) as e:
        check_amounts(t, lay)
    assert e.value.message == DECIMAL_COMMA


@pytest.mark.parametrize("name", ["empty.csv", "header-only.csv"])
def test_a_file_with_no_rows_says_so(name):
    with pytest.raises(FileRefused) as e:
        _table(name)
    assert e.value.message == NO_ROWS


@pytest.mark.parametrize("text,header,mapping", [
    ("Run Date,Payee Name,Amount\n10/14/2024,BLUE BOTTLE,6.50\n10/15/2024,PAYROLL,-2100.00\n",
     ("Run Date", "Payee Name", "Amount"), {"amount": 2}),
    ("Account Activity\n\nDate,Details,Amount,Balance\n10/14/2024,BLUE BOTTLE,-6.50,100.00\n",
     ("Date", "Details", "Amount", "Balance"), {"date": 0, "amount": 2}),
])
def test_a_header_whose_names_guess_too_little_reaches_the_confirm(text, header, mapping):
    """P1, P12: odd header names are mapped once in the confirm, never refused as unreadable."""
    t = read_table(text)
    assert (t.header, t.headerless) == (header, False)
    assert t.rows[0][1][1] == "BLUE BOTTLE"
    lay = identify(t, layout_key(t))
    assert (lay.state, lay.mapping) == ("new", mapping)
    assert parse(t, lay, TODAY).held == ("date" not in mapping)  # held until the confirm maps a date column


def test_a_headerless_file_is_still_read_by_its_shapes_not_its_first_row():
    t = read_table("10/14/2024,BLUE BOTTLE,6.50\n10/15/2024,PAYROLL,-2100.00\n")
    assert t.headerless and len(t.rows) == 2


def test_the_date_format_of_a_column_chosen_in_the_confirm():
    t = read_table("Posted On,Description,Amount\n10/14/2024,A,1.00\n10/21/2024,B,2.00\n")
    assert date_format_for(t, 0) == MDY
    both = read_table("Posted On,Description,Amount\n03/04/2024,A,1.00\n03/04/2024,B,2.00\n")
    assert date_format_for(both, 0) == MDY                      # month first where both read (today's reading)
    assert date_format_for(t, 1) is None


def test_a_remembered_split_column_layout_never_keeps_negate():
    """Edit can't leave negate on a mapping whose columns say the sign: the next file would import backwards."""
    lay = remembered("h:x", ("Date", "Description", "Debit", "Credit"), 1, "First CU",
                     {"date": 0, "description": 1, "debit": 2, "credit": 3}, True, MDY)
    assert lay.negate is False and lay.sign_fixed
    t = read_table("Date,Description,Debit,Credit\n10/14/2024,COFFEE,45.67,\n10/15/2024,PAYROLL,,2100.00\n")
    assert [r.amount_cents for r in parse(t, lay, TODAY).rows] == [-4567, 210000]


def test_a_client_mapping_is_checked_against_the_header():
    assert mapping_from({"date": 0, "description": 1, "amount": 2}, 3) == {"date": 0, "description": 1, "amount": 2}
    assert mapping_from({"date": 0, "description": 1, "debit": 2, "credit": 3}, 4)["credit"] == 3
    with pytest.raises(ValueError, match=CHOOSE_AMOUNT):
        mapping_from({"date": 0, "description": 1, "debit": 2}, 3)
    for bad in ({"date": 0, "description": 0, "amount": 2}, {"date": 0, "description": 1, "amount": 3},
                {"date": 0, "description": 1, "amount": True}, {"day": 0, "description": 1, "amount": 2}, [0, 1, 2],
                {"description": 1, "amount": 2}):
        with pytest.raises(ValueError, match=NOT_UNDERSTOOD):
            mapping_from(bad, 3)


def test_the_importers_never_reach_a_model():
    """P1: no model sees layouts or cells this round."""
    root = Path(importers_pkg.__file__).parent
    words = ("categorizer_client", "steward.advisor", "gateway", "httpx", "ModelClient")
    assert [(p.name, w) for p in root.glob("*.py") for w in words if w in p.read_text()] == []
