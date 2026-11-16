from datetime import date

import pytest

from steward.inventory.suggester import Form, ItemFact, Txn, cadence, candidates, payer, read_inputs, steady

TODAY = date(2026, 10, 18)


@pytest.mark.parametrize("raw,key,name", [
    ("WESTMARK LIFE ANN PMT 5521", ("WESTMARK", "LIFE"), "Westmark Life"),
    ("HARBOR SAVINGS BK INT XFER", ("HARBOR", "SAVINGS", "BANK"), "Harbor Savings Bank"),
    ("GLOBE MUTUAL MEDSUPP PREM", ("GLOBE", "MUTUAL"), "Globe Mutual"),
    ("SSA TREAS 310 XXSOC SEC", ("SOCIAL", "SECURITY"), "Social Security"),
    ("PACIFIC WESTERN CU INT", ("PACIFIC", "WESTERN", "CREDIT", "UNION"), "Pacific Western Credit Union"),
    ("Harbor Savings Bank", ("HARBOR", "SAVINGS", "BANK"), "Harbor Savings Bank"),
])
def test_payer_keys(raw, key, name):
    assert payer(raw) == (key, name)


@pytest.mark.parametrize("raw", ["INTEREST PAYMENT", "ONLINE TRANSFER TO 4425", "CHECK 1043", "BANK"])
def test_descriptions_with_no_payer(raw):
    assert payer(raw) is None


def test_cadence_and_steady():
    monthly = [date(2026, m, 15) for m in (7, 8, 9, 10)]
    assert cadence(monthly) == "monthly" and cadence(monthly[:2]) is None
    assert cadence([date(2026, 6, 30), date(2026, 9, 30)]) == "quarterly"
    assert cadence([date(2025, 3, 1), date(2026, 3, 1)]) == "yearly"
    assert cadence([date(2026, 1, 1), date(2026, 1, 9), date(2026, 1, 20)]) is None
    assert steady([41000, 41000, 41000, 40900]) and not steady([9000, 11311, 13622, 15933])


def _monthly(start_id, raw, cents, months=(7, 8, 9, 10), day=15, account=1):
    return [Txn(start_id + i, account, date(2026, m, day), cents, raw) for i, m in enumerate(months)]


def test_recurring_deposits_and_premiums_become_income_and_insurance():
    txns = _monthly(1, "WESTMARK LIFE ANN PMT 5521", 41000) + _monthly(10, "GLOBE MUTUAL MEDSUPP PREM", -18620)
    items = [ItemFact(5, "account", "needs_checking", ("WESTMARK", "LIFE"), None, "annuity", "5521", 9)]
    inc, ins = candidates(txns, [], items)
    assert (inc.kind, inc.payer_name, inc.guess, inc.amount_cents, inc.frequency, inc.usual_day, inc.count) == (
        "income", "Westmark Life", "annuity", 41000, "monthly", 15, 4)
    assert inc.related_item_id == 5 and inc.txn_ids == [4, 3, 2, 1] and inc.match_text == "WESTMARK LIFE ANN PMT"
    assert (ins.kind, ins.payer_name, ins.guess, ins.hint_word, ins.amount_cents) == (
        "insurance", "Globe Mutual", "supplement", "MEDSUPP", 18620)


def test_interest_from_another_bank_suggests_an_account():
    txns = [Txn(1, 2, date(2026, 6, 30), 1461, "HARBOR SAVINGS BK INT XFER"),
            Txn(2, 2, date(2026, 9, 30), 1482, "HARBOR SAVINGS BK INT XFER")]
    (acct,) = candidates(txns, [], [])
    assert (acct.kind, acct.signal, acct.guess, acct.payer_key, acct.count) == (
        "account", "interest", "savings", "HARBOR SAVINGS BANK", 2)


def test_near_misses_suggest_nothing():
    one_deposit = [Txn(1, 1, date(2026, 10, 15), 41000, "WESTMARK LIFE ANN PMT 5521")]
    varying = [Txn(i, 1, date(2026, m, 15), -(9000 + i * 2311), "AETNA PREMIUM") for i, m in enumerate((7, 8, 9, 10))]
    payroll = _monthly(20, "ACME CORP PAYROLL", 300000)
    own_interest = [Txn(30, 1, date(2026, 9, 30), 120, "WELLS FARGO INT")]
    wells = [ItemFact(1, "account", "confirmed", ("WELLS", "FARGO"), None, "checking", "4417", 1)]
    assert candidates(one_deposit + varying + payroll + own_interest, [], wells) == []


def test_listed_items_and_matched_text_keep_suggestions_away():
    txns = _monthly(1, "SSA TREAS 310 XXSOC SEC", 214000, day=3) + _monthly(10, "COUNTY SCHOOLS RET PENSION", 138500, day=1)
    items = [ItemFact(1, "income", "confirmed", ("SOCIAL", "SECURITY"), None, "social_security", None, None),
             ItemFact(2, "income", "confirmed", ("COUNTY", "SCHOOLS", "RETIREMENT"), "COUNTY SCHOOLS RET", "pension", None, None)]
    assert candidates(txns, [], items) == []


def test_tax_forms_join_or_start_suggestions():
    txns = [Txn(1, 2, date(2026, 6, 30), 1461, "HARBOR SAVINGS BK INT XFER")]
    harbor = Form(7, "1099-INT", 2025, "Harbor Savings Bank", "HARBOR SAVINGS BANK", "2207", {"box_1": 5890})
    rollover = Form(8, "1099-R", 2025, "Lakeside Brokerage", "LAKESIDE BROKERAGE", None, {"box_1": 100000, "box_7": "G"})
    annuity = Form(9, "1099-R", 2025, "Westmark Life", "WESTMARK LIFE", "5521", {"box_1": 492000, "box_7": "7"})
    ssa = Form(10, "SSA-1099", 2025, "Social Security Administration", "SOCIAL SECURITY", None, {"box_5": 2568000})
    ss_item = ItemFact(1, "income", "confirmed", ("SOCIAL", "SECURITY"), None, "social_security", None, None)
    got = {(c.kind, c.payer_key): c for c in candidates(txns, [harbor, rollover, annuity, ssa], [ss_item])}
    assert got[("account", "HARBOR SAVINGS BANK")].form_ids == [7] and got[("account", "HARBOR SAVINGS BANK")].count == 1
    assert ("income", "LAKESIDE BROKERAGE") not in got and got[("account", "LAKESIDE BROKERAGE")].guess == "ira"
    assert got[("income", "WESTMARK LIFE")].guess == "annuity" and got[("income", "WESTMARK LIFE")].amount_cents == 41000
    assert got[("account", "WESTMARK LIFE")].guess == "annuity"
    assert ("income", "SOCIAL SECURITY") not in got


def test_margaret_gets_exactly_three_suggestions(margaret, mdb):
    from steward.demo_parent import seed_parent
    seed_parent(mdb, TODAY)
    found = candidates(*read_inputs(mdb))
    assert [(c.kind, c.payer_name, c.signal) for c in found] == [
        ("income", "Westmark Life", "income"), ("insurance", "Globe Mutual", "insurance"),
        ("account", "Harbor Savings Bank", "interest")]
