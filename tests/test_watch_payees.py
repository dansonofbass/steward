"""Decision 2: card purchases are named by the cleaned-up merchant (store numbers and cities ignored); Zelle, checks,
wires and bill pay by the recipient as the bank gives it, normalised for case and spacing. The scam and cash word
lists live in a data file covered here, like the categorizer's rules."""
import json
import re

import pytest

from steward.watch import vocab as V
from steward.watch.payees import DATA, Payee, display, is_cash, known_label, payee, scam_kind


@pytest.mark.parametrize("raw, merchant, expected", [
    ("CVS/PHARMACY #09812 GIFT CARD FULLERTON CA", None, Payee("CVS PHARMACY", "CVS Pharmacy", "card")),
    ("CVS/PHARMACY #04411 BREA CA", None, Payee("CVS PHARMACY", "CVS Pharmacy", "card")),
    ("RALPHS #0214 FULLERTON CA", None, Payee("RALPHS", "Ralphs", "card")),
    ("TARGET BREA CA", None, Payee("TARGET", "Target", "card")),
    ("BREA FAMILY DENTAL", None, Payee("BREA FAMILY DENTAL", "Brea Family Dental", "card")),
    ("POS PURCHASE TRADER JOE'S 512", None, Payee("TRADER JOES", "Trader Joe's", "card")),
    ("STREAMBOX *MONTHLY", "StreamBox", Payee("STREAMBOX", "StreamBox", "card")),
    ("ZELLE PAYMENT TO J. SMITH CONF# QX81234", None, Payee("zelle:J SMITH", "J. Smith", "zelle")),
    ("Zelle payment to  j smith  on 10/16 REF # PP1", None, Payee("zelle:J SMITH", "J Smith", "zelle")),
    ("ZELLE TO ROSA DELGADO ON 09/26 REF # PP123", "Zelle", Payee("zelle:ROSA DELGADO", "Rosa Delgado", "zelle")),
    ("WIRE TRANSFER TO GLOBAL TRADING LTD REF 991", None, Payee("wire:GLOBAL TRADING LTD", "Global Trading Ltd", "wire")),
    ("ONLINE BILL PAYMENT TO PACIFIC SHIELD INS 4108", None, Payee("bill_pay:PACIFIC SHIELD INS", "Pacific Shield Ins", "bill_pay")),
    ("CHECK 1043", None, Payee("", "Check", "check")),
    ("CHECKCARD 1015 HOME DEPOT 6611", None, Payee("HOME DEPOT", "Home Depot", "card")),
])
def test_payee_names(raw, merchant, expected):
    assert payee(raw, merchant) == expected


@pytest.mark.parametrize("raw, merchant, expected", [
    ("PAYPAL *JOHNDOE", "PayPal", Payee("paypal:JOHNDOE", "PayPal to Johndoe", "card")),
    ("PAYPAL *JOHNDOE 4029357733 CA", None, Payee("paypal:JOHNDOE", "PayPal to Johndoe", "card")),
    ("PAYPAL *SCAMMERLLC", None, Payee("paypal:SCAMMERLLC", "PayPal to Scammerllc", "card")),
    ("VENMO *ALICE", "Venmo", Payee("venmo:ALICE", "Venmo to Alice", "card")),
    ("Venmo * alice 855-999-4410", None, Payee("venmo:ALICE", "Venmo to Alice", "card")),
])
def test_payment_app_lines_are_named_by_their_recipient(raw, merchant, expected):
    assert payee(raw, merchant) == expected
    assert known_label(expected) == expected.name


def test_two_recipients_through_one_app_are_two_payees():
    assert payee("PAYPAL *JOHNDOE").key != payee("PAYPAL *SCAMMERLLC").key
    assert payee("PAYPAL *JOHNDOE").key != payee("VENMO *JOHNDOE").key


def test_a_channel_is_part_of_a_payees_identity():
    keys = {payee("ALICE").key, payee("PAYPAL *ALICE").key, payee("VENMO *ALICE").key,
            payee("ZELLE PAYMENT TO ALICE").key, payee("WIRE TRANSFER TO ALICE").key}
    assert len(keys) == 5
    # a name cannot spell another channel's prefix
    assert payee("ZELLE:ALICE").key != payee("ZELLE PAYMENT TO ALICE").key
    assert payee("PAYPAL:ALICE", "PAYPAL:ALICE").key != payee("PAYPAL *ALICE").key


def test_the_same_store_in_another_city_is_the_same_payee():
    assert payee("RALPHS #0214 FULLERTON CA").key == payee("RALPHS #0088 BREA CA").key


def test_display_keeps_acronyms_and_initials():
    assert display("CVS PHARMACY") == "CVS Pharmacy"
    assert display("J. SMITH") == "J. Smith"
    assert display("CLEARPATH RX") == "Clearpath Rx"


@pytest.mark.parametrize("raw, kind", [
    ("CVS/PHARMACY #09812 GIFT CARD FULLERTON CA", "gift_card"),
    ("WIRE TRANSFER TO GLOBAL TRADING LTD", "wire"),
    ("COINBASE.COM 8889087930", "crypto"),
    ("WESTERN UNION 1234 ONLINE", "money_transfer"),
    ("REMOTE SUPPORT SVCS 800-555-0100", "remote_support"),
])
def test_scam_kinds(raw, kind):
    assert scam_kind(raw)["kind"] == kind


@pytest.mark.parametrize("raw", ["CVS/PHARMACY #04411 BREA CA", "GIFT SHOP AT THE ZOO", "CARDINAL HEALTH",
                                 "WIRELESS ONE 445", "STEAMBOAT CAFE"])
def test_near_misses_are_not_scams(raw):
    assert scam_kind(raw) is None


def test_cash_words():
    assert is_cash("ATM WITHDRAWAL 1200 MAIN ST")
    assert is_cash("CASH WITHDRAWAL BRANCH 12")
    assert not is_cash("ATM FEE")
    assert not is_cash("CASHMERE BOUTIQUE")


def test_known_labels():
    assert known_label(Payee("BREA FAMILY DENTAL", "Brea Family Dental", "card")) == "Brea Family Dental"
    assert known_label(Payee("zelle:J SMITH", "J. Smith", "zelle")) == "Zelle to J. Smith"


def test_the_data_file_is_complete():
    raw = json.loads(DATA.read_text())
    for entry in raw["scam"]:
        assert set(entry) == {"kind", "word", "title", "words"}
        assert "{amount}" in entry["title"] and "{payee}" in entry["title"] and entry["words"]
    assert {m["method"] for m in raw["methods"]} == {"zelle", "wire", "bill_pay", "check"}
    for m in raw["methods"]:
        re.compile(m["pattern"])
    assert set(raw["recipient"]) == {"to", "name", "end"}
    for part in raw["recipient"].values():
        re.compile(part)
    assert len(raw["states"]) == 51 and all(len(s) == 2 for s in raw["states"])
    assert set(raw["payment_apps"]) == {"Zelle", "Venmo", "PayPal", "Cash App"}


def test_every_check_has_its_words():
    for table in (V.CHECK_LABELS, V.CHECK_ICONS, V.WHY):
        assert set(table) == set(V.RANK)
    assert V.check_label("unusual", "Margaret") == "Unusual for Margaret"
    assert V.why("large", 75_000).startswith("This check flags any payment of $750.00 or more")
    for check in V.RANK:
        line = V.why(check, 50_000)
        assert line.startswith("This check flags") and not re.search(r"\b(her|hers|she)\b", line)


@pytest.mark.parametrize("raw", ["SHOP ¹²³⁴⁵⁶⁷ STORE", "SHOP ①②③④⑤⑥⑦ STORE", "SHOP ¹²³⁴⁵⁶⁷", "¹²³⁴⁵⁶⁷ SHOP"])
def test_card_payee_names_never_show_more_than_four_digits(raw):
    for p in (payee(raw), payee("X", raw)):
        assert sum(c.isdigit() for c in p.name) <= 4
        assert sum(c.isdigit() for c in known_label(p)) <= 4
