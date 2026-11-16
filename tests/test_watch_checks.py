"""Spec 11: each check has fixtures that fire and near misses that don't. Spec 4.1's table, read with decisions 1-3
and rulings 1, 2, 12, 14-16. Dates are relative to Mon Oct 19, 2026."""
from datetime import date, timedelta

from steward.watch.payees import payee
from steward.watch.checks import History, Known, Rules, Txn, check, primary

TODAY = date(2026, 10, 19)


def d(n: int) -> date:
    return TODAY - timedelta(days=n)


OPEN = Txn(1, 1, d(400), 100_000, "OPENING DEPOSIT", category="income")   # 400 days of history: seasoned


def T(id, days_ago, cents, raw, **kw) -> Txn:
    return Txn(id, kw.pop("account_id", 1), d(days_ago), cents, raw, **kw)


def checks_of(t: Txn, *others: Txn, rules: Rules = Rules(), start: Txn = OPEN) -> list[str]:
    return sorted(h.check for h in check(History([start, *others, t]), t, rules))


# -- Scam pattern -------------------------------------------------------------------------------------------------
def test_a_gift_card_is_urgent_and_also_large():
    earlier = T(2, 30, -2347, "CVS/PHARMACY #04411 BREA CA", category="shopping")
    gift = T(3, 2, -50_000, "CVS/PHARMACY #09812 GIFT CARD FULLERTON CA", category="shopping")
    hits = check(History([OPEN, earlier, gift]), gift, Rules())
    main, also = primary(hits)
    assert (main.check, main.severity, main.summary) == ("scam", "urgent", "$500.00 gift card at CVS Pharmacy")
    assert [(h.check, h.detail) for h in also] == [("large", "$500.00 or more")]
    assert main.facts["kind"] == "gift_card" and main.facts["payee"] == "CVS Pharmacy"


def test_scam_near_misses():
    earlier = T(2, 30, -2347, "CVS/PHARMACY #04411 BREA CA")
    assert checks_of(T(3, 2, -1588, "CVS/PHARMACY #04411 BREA CA"), earlier) == []
    # a wire between the book's own accounts is not a scam payment; a wire filed as a transfer still is
    assert checks_of(T(4, 2, -30_000, "WIRE TRANSFER TO SAVINGS", paired=True)) == []
    assert "scam" in checks_of(T(5, 2, -30_000, "WIRE TRANSFER TO GLOBAL TRADING LTD", category="transfer"))


# -- New payee ----------------------------------------------------------------------------------------------------
def test_a_new_zelle_payee_over_200_is_urgent():
    t = T(2, 3, -120_000, "ZELLE PAYMENT TO J. SMITH CONF# QX81234")
    main, also = primary(check(History([OPEN, t]), t, Rules()))
    assert (main.check, main.severity, main.summary) == ("payee", "urgent", "$1,200.00 by Zelle to J. Smith")
    assert [h.check for h in also] == ["large"]


def severities(t: Txn) -> list[str]:
    return [h.severity for h in check(History([OPEN, t]), t, Rules())]


def test_new_payee_severity_and_the_card_minimum():
    assert severities(T(2, 3, -15_000, "ZELLE TO ROSA DELGADO ON 09/26")) == ["normal"]
    assert severities(T(3, 3, -20_000, "ZELLE TO K NGUYEN ON 10/16")) == ["normal"]    # urgent only over $200
    assert checks_of(T(4, 3, -6418, "RALPHS #0214 FULLERTON CA")) == ["payee"]
    assert checks_of(T(5, 3, -3000, "NEW CAFE 12 FULLERTON CA")) == []                                # ruling 1


def test_seen_within_18_months_is_not_new():
    assert checks_of(T(3, 3, -6418, "RALPHS #0214 FULLERTON CA"), T(2, 517, -5000, "RALPHS #0088 BREA CA")) == []
    assert checks_of(T(3, 3, -6418, "RALPHS #0214 FULLERTON CA"), T(2, 578, -5000, "RALPHS #0088 BREA CA"),
                     start=Txn(1, 1, d(700), 100, "OPENING DEPOSIT")) == ["payee"]


def test_a_young_book_calls_nobody_new_and_a_numbered_check_has_no_payee():
    young = Txn(1, 1, d(40), 100_000, "OPENING DEPOSIT", category="income")
    assert checks_of(T(2, 3, -15_000, "ZELLE TO ROSA DELGADO ON 09/26"), start=young) == []
    assert checks_of(T(3, 3, -30_000, "CHECK 1043")) == []


# -- Large amount -------------------------------------------------------------------------------------------------
def test_large_amount_threshold():
    seen = T(2, 100, -1000, "BREA FAMILY DENTAL", category="health")
    assert checks_of(T(3, 5, -49_999, "BREA FAMILY DENTAL", category="health"), seen) == []
    assert checks_of(T(4, 5, -50_000, "BREA FAMILY DENTAL", category="health"), seen) == ["large"]
    assert checks_of(T(5, 5, -60_000, "BREA FAMILY DENTAL", category="health"), seen, rules=Rules(large_cents=75_000)) == []
    assert checks_of(T(6, 5, -90_000, "CITI CARD ONLINE PAYMENT", category="transfer")) == []


# -- Unusual for Margaret -----------------------------------------------------------------------------------------
def _health(*amounts: int) -> list[Txn]:
    return [T(10 + i, 40 + 30 * i, -a, "BREA FAMILY DENTAL", category="health") for i, a in enumerate(amounts)]


def test_unusual_for_the_category():
    t = T(2, 5, -20_000, "BREA FAMILY DENTAL", category="health")
    hits = check(History([OPEN, *_health(4000, 5000, 6000), t]), t, Rules())
    assert [(h.check, h.summary) for h in hits] == [
        ("unusual", "$200.00 to Brea Family Dental, more than 3 times the usual for health")]


def test_a_trade_inside_an_investment_account_is_not_watched():
    """Roadmap 12 final review: Investment activity is money moving, like a transfer: a $20,000 rebalance after three
    $500 buys is neither unusual for its category nor a large payment to a new payee."""
    buys = [T(10 + i, 40 + 30 * i, -50_000, "BUY VTI", category="investment") for i in range(3)]
    assert checks_of(T(2, 5, -2_000_000, "BUY VXUS REBALANCE", category="investment"), *buys) == []


def test_unusual_near_misses():
    assert checks_of(T(2, 5, -14_000, "BREA FAMILY DENTAL", category="health"), *_health(4000, 5000, 6000)) == []
    assert checks_of(T(3, 5, -20_000, "BREA FAMILY DENTAL", category="health"), *_health(4000, 5000)) == []
    assert checks_of(T(4, 5, -9000, "BREA FAMILY DENTAL", category="health"), *_health(2000, 2500, 3000)) == []


# -- Cash ---------------------------------------------------------------------------------------------------------
def test_cash_fires_once_when_the_month_passes_the_usual():
    start = Txn(1, 1, d(120), 100_000, "OPENING DEPOSIT", category="income")
    past = [T(2, 35, -10_000, "ATM WITHDRAWAL 1200 MAIN ST"), T(3, 65, -10_000, "ATM WITHDRAWAL 1200 MAIN ST"),
            T(4, 95, -10_000, "ATM WITHDRAWAL 1200 MAIN ST")]
    first, crossing, after = (T(5, 10, -6000, "ATM WITHDRAWAL 88 ELM"), T(6, 5, -8000, "ATM WITHDRAWAL 88 ELM"),
                              T(7, 2, -2000, "ATM WITHDRAWAL 88 ELM"))
    h = History([start, *past, first, crossing, after])
    assert [x.check for x in check(h, first, Rules())] == []
    hits = check(h, crossing, Rules())
    assert [(x.check, x.summary) for x in hits] == [
        ("cash", "$80.00 cash withdrawal brings this month to $140.00, over the usual $100.00")]
    assert check(h, after, Rules()) == []


def _no_cash_before():
    return [OPEN, T(2, 35, -10_000, "GROCERY MARKET", category="groceries"), T(3, 65, -10_000, "GROCERY MARKET", category="groceries")]


def test_cash_when_the_usual_is_nothing_fires_only_from_the_floor():
    small = T(10, 3, -15_000, "ATM WITHDRAWAL 88 ELM")
    big = T(11, 2, -20_000, "ATM WITHDRAWAL 88 ELM")
    later = T(12, 1, -30_000, "ATM WITHDRAWAL 88 ELM")
    h = History([*_no_cash_before(), small, big, later])
    assert check(h, small, Rules()) == []
    hits = check(h, big, Rules())
    assert [(x.check, x.summary) for x in hits] == [("cash", "A $200.00 cash withdrawal. Usually there's none.")]
    assert check(h, later, Rules()) == []             # one alert a month
    assert [x.check for x in check(h, small, Rules(cash_floor_cents=10_000))] == ["cash"]


# -- New monthly charge -------------------------------------------------------------------------------------------
def test_a_new_monthly_charge():
    first = T(2, 31, -1599, "STREAMBOX *MONTHLY", merchant="StreamBox", category="subscriptions")
    second = T(3, 1, -1599, "STREAMBOX *MONTHLY", merchant="StreamBox", category="subscriptions")
    h = History([OPEN, first, second])
    assert check(h, first, Rules()) == []
    hits = check(h, second, Rules())
    assert [(x.check, x.summary) for x in hits] == [("monthly", "StreamBox, $15.99 on Sep 18 and Oct 18")]


def test_new_monthly_near_misses():
    sb = dict(merchant="StreamBox", category="subscriptions")
    assert checks_of(T(3, 1, -1999, "STREAMBOX", **sb), T(2, 31, -1599, "STREAMBOX", **sb)) == []    # not similar
    assert checks_of(T(3, 1, -1599, "STREAMBOX", **sb), T(2, 41, -1599, "STREAMBOX", **sb)) == []    # 40 days apart
    assert checks_of(T(4, 1, -1599, "STREAMBOX", **sb), T(3, 31, -1599, "STREAMBOX", **sb),
                     T(2, 200, -1599, "STREAMBOX", **sb)) == []                                       # was charging before


def test_money_in_from_a_payee_is_not_history_for_new_payee_or_new_monthly():
    # a refund from Ralphs is not "paid in the last 18 months"
    refund = T(2, 100, 5000, "RALPHS #0214 FULLERTON CA REFUND", category="shopping")
    assert "payee" in checks_of(T(3, 3, -6418, "RALPHS #0214 FULLERTON CA"), refund)
    # a refund before the pair is not "was charging before"; a refund between them does not hide the pair
    sb = dict(merchant="StreamBox", category="subscriptions")
    old_refund = T(5, 200, 1599, "STREAMBOX REFUND", **sb)
    assert "monthly" in checks_of(T(4, 1, -1599, "STREAMBOX *MONTHLY", **sb), T(3, 31, -1599, "STREAMBOX *MONTHLY", **sb),
                                  old_refund)
    between = T(6, 15, 1599, "STREAMBOX REFUND", **sb)
    assert "monthly" in checks_of(T(4, 1, -1599, "STREAMBOX *MONTHLY", **sb), T(3, 31, -1599, "STREAMBOX *MONTHLY", **sb),
                                  between)


# -- Duplicate ----------------------------------------------------------------------------------------------------
def test_a_duplicate():
    seen = T(2, 100, -5210, "RALPHS #0214 FULLERTON CA")
    a, b = T(3, 6, -6418, "RALPHS #0214 FULLERTON CA"), T(4, 5, -6418, "RALPHS #0214 FULLERTON CA")
    h = History([OPEN, seen, a, b])
    assert check(h, a, Rules()) == []
    hits = check(h, b, Rules())
    assert [(x.check, x.summary, x.title) for x in hits] == [
        ("duplicate", "$64.18 at Ralphs on Oct 13 and again on Oct 14", "$64.18 at Ralphs, twice")]
    assert hits[0].facts["other_id"] == 3


def test_duplicate_near_misses():
    seen = T(2, 100, -5210, "RALPHS #0214 FULLERTON CA")
    a = T(3, 9, -6418, "RALPHS #0214 FULLERTON CA")
    assert checks_of(T(4, 5, -6418, "RALPHS #0214 FULLERTON CA"), seen, a) == []                       # 4 days apart
    assert checks_of(T(4, 8, -6419, "RALPHS #0214 FULLERTON CA"), seen, a) == []                       # another amount
    kept = Rules(kept_pairs=frozenset({(3, 4)}))
    assert checks_of(T(4, 8, -6418, "RALPHS #0214 FULLERTON CA"), seen, a, rules=kept) == []           # Keep both


# -- Known payees (decision 1) -----------------------------------------------------------------------------------
def test_a_known_payee_quiets_four_checks_within_its_band():
    seen = T(2, 100, -1000, "BREA FAMILY DENTAL", category="health")
    band = Rules(known=(Known("BREA FAMILY DENTAL", 48_000, 80_000),))
    assert checks_of(T(3, 5, -64_000, "BREA FAMILY DENTAL", category="health"), seen, rules=band) == []
    assert checks_of(T(4, 5, -90_000, "BREA FAMILY DENTAL", category="health"), seen, rules=band) == ["large"]
    anyamount = Rules(known=(Known("BREA FAMILY DENTAL"),))
    assert checks_of(T(5, 5, -90_000, "BREA FAMILY DENTAL", category="health"), seen, rules=anyamount) == []


def test_a_known_payment_app_recipient_does_not_quiet_another_recipient():
    rules = Rules(known=(Known("paypal:JOHNDOE"),))
    assert checks_of(T(2, 5, -90_000, "PAYPAL *JOHNDOE 4029357733 CA"), rules=rules) == []
    assert "large" in checks_of(T(3, 5, -90_000, "PAYPAL *SCAMMERLLC"), rules=rules)


def test_expected_for_one_channel_does_not_quiet_the_same_name_in_another():
    rules = Rules(known=(Known(payee("PAYPAL *ALICE").key),))
    assert checks_of(T(2, 5, -90_000, "PAYPAL *ALICE"), rules=rules) == []
    for raw in ("ALICE", "VENMO *ALICE", "ZELLE PAYMENT TO ALICE", "WIRE TRANSFER TO ALICE"):
        assert "large" in checks_of(T(3, 5, -90_000, raw), rules=rules), raw


def test_a_known_payee_never_quiets_a_scam_or_a_duplicate():
    known = Rules(known=(Known("CVS PHARMACY"),))
    assert checks_of(T(3, 2, -50_000, "CVS/PHARMACY #09812 GIFT CARD FULLERTON CA"),
                     T(2, 30, -2347, "CVS/PHARMACY #04411 BREA CA"), rules=known) == ["scam"]
    a = T(4, 6, -2347, "CVS/PHARMACY #04411 BREA CA")
    assert checks_of(T(5, 5, -2347, "CVS/PHARMACY #04411 BREA CA"), T(2, 30, -2347, "CVS/PHARMACY #04411 BREA CA"),
                     a, rules=known) == ["duplicate"]


def test_money_in_is_never_checked():
    assert checks_of(T(2, 3, 500_000, "WIRE TRANSFER FROM ESTATE OF A RELATIVE")) == []
