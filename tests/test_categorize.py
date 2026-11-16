import json
from datetime import date

import httpx2

from steward.db.models import CategorySource, MerchantRule
from steward.services.categorize import Suggestion, rule_suggestion, suggest
from steward.services.categorizer_client import HttpModelClient, NullModelClient
from tests.factories import make_account


def test_merchant_rule_wins(db):
    a = make_account(db)
    db.add(MerchantRule(pattern="COSTCO WHSE", merchant="Costco", category="home", is_business=None,
                        source=CategorySource.correction))
    db.commit()
    s = suggest(db, "COSTCO WHSE #0482", -5000, a, None)
    assert s == Suggestion("Costco", "home", None, CategorySource.correction)


def test_merchant_rule_carries_is_business_and_rule_source(db):
    a = make_account(db)
    db.add(MerchantRule(pattern="ACME SUPPLY", merchant="Acme", category="business_expense", is_business=True,
                        source=CategorySource.rule))
    db.commit()
    assert suggest(db, "ACME SUPPLY 99", -100, a, None) == Suggestion(
        "Acme", "business_expense", True, CategorySource.rule)


def test_builtin_rules(db):
    a = make_account(db)
    assert suggest(db, "PAYROLL ACME CORP", 412000, a, None).category == "income"
    assert suggest(db, "MORTGAGE PMT HOMELOAN SVC", -268000, a, None).category == "housing"
    assert suggest(db, "PAYMENT THANK YOU", 50000, a, None).category == "transfer"
    z = suggest(db, "ZELLE PAYMENT TO JANE DOE 12345", -4000, a, None)
    assert z == Suggestion("Zelle", "uncategorized", None, CategorySource.none)
    assert suggest(db, "USTREAS IRS ESTIMATED TAX", -500000, a, None).category == "taxes"
    assert suggest(db, "NETFLIX.COM", -1599, a, None).category == "subscriptions"
    assert suggest(db, "COSTCO WHSE #0482", -5000, a, None) == Suggestion(
        None, "groceries", None, CategorySource.rule)


def test_other_builtin_rules(db):
    a = make_account(db)
    for raw, cat, merchant in [
        ("VENMO PAYMENT", "uncategorized", "Venmo"),
        ("CASH APP*SOMEONE", "uncategorized", "Cash App"),
        ("PAYPAL TRANSFER", "uncategorized", "PayPal"),
        ("INTEREST PAID", "interest", None),
        ("AMZN MKTP US", "shopping", "Amazon"),
        ("SHELL OIL 5744", "transport", None),
        ("DELTA AIR LINES", "travel", None),
        ("TRANSFER TO SAVINGS", "transfer", None),
    ]:
        s = suggest(db, raw, 100 if raw == "INTEREST PAID" else -100, a, None)   # interest earned is money in
        assert (s.category, s.merchant) == (cat, merchant), raw


def test_loan_payments_cash_and_atm_fees(db):
    """JR, Oct 28: a car or student loan payment is a Loan payment; a card payment stays a Transfer, since the card's
    purchases were already counted; an ATM withdrawal is Cash and ATM, its fee a Fee."""
    a = make_account(db)
    for raw, cat in [
        ("TOYOTA FINANCIAL SVCS PAYMENT", "loan_payments"),
        ("ALLY PAYMT 260215", "loan_payments"),
        ("NAVIENT STUDENT LOAN PMT", "loan_payments"),
        ("GM FINANCIAL AUTOPAY", "loan_payments"),
        ("PAYMENT THANK YOU", "transfer"),
        ("AUTOPAY PAYMENT - THANK YOU", "transfer"),
        ("ATM WITHDRAWAL 1234 MAIN ST", "cash_atm"),
        ("CASH WITHDRAWAL BRANCH 22", "cash_atm"),
        ("NON-NETWORK ATM FEE", "fees"),
        ("ATM FEE", "fees"),
        ("CAPITAL ONE AUTO FINANCE PMT", "loan_payments"),
    ]:
        assert suggest(db, raw, -10000, a, None).category == cat, raw


def test_the_new_rules_leave_autopays_and_money_coming_in_alone(db):
    """Final review: "AUTO PMT" is any automatic payment and CAPITAL ONE AUTOPAY is its card's payment, not a car loan;
    a loan's funding or refund and an ATM deposit are money in, which would net against spending as a refund."""
    a = make_account(db)
    for raw in ["CAPITAL ONE AUTOPAY PYMT", "XFINITY AUTO PMT", "VERIZON AUTO PMT", "SOFI PERSONAL LOAN FUNDING",
                "NELNET STUDENT LOAN REFUND", "ATM DEPOSIT", "ATM CHECK DEPOSIT 4471", "ATMOS ENERGY BILL"]:
        assert suggest(db, raw, -10000, a, None).category not in ("loan_payments", "cash_atm"), raw


def test_model_then_uncategorized(db):
    a = make_account(db)

    class Fake:
        last_error = None

        def categorize(self, d, c):
            return ("dining", "Noodle House") if "NOODLE" in d else None
    s = suggest(db, "NOODLE HOUSE 221", -1800, a, Fake())
    assert s == Suggestion("Noodle House", "dining", None, CategorySource.model)
    assert suggest(db, "SQ *MYSTERY", -100, a, Fake()) == Suggestion(None, "uncategorized", None, CategorySource.none)
    assert suggest(db, "SQ *MYSTERY", -100, a, NullModelClient()).category == "uncategorized"


def test_model_not_asked_when_a_rule_matches(db):
    a = make_account(db)

    class Boom:
        last_error = None

        def categorize(self, d, c):
            raise AssertionError("should not be asked")
    assert suggest(db, "NETFLIX.COM", -1599, a, Boom()).category == "subscriptions"


def _client(handler, **kw):
    kw.setdefault("cooldown_s", 0)
    return HttpModelClient("http://categorizer.test/categorize", timeout_s=0.2,
                           transport=httpx2.MockTransport(handler), **kw)


def test_http_client_sends_payload_and_reads_reply():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json={"category": "dining", "merchant": "Noodle House"})
    c = _client(handler)
    c.last_error = "stale"
    assert c.categorize("NOODLE HOUSE", -1800) == ("dining", "Noodle House")
    assert seen["body"] == {"description": "NOODLE HOUSE", "amount_cents": -1800}
    assert c.last_error is None


def test_http_client_null_merchant_and_unknown_category():
    c = _client(lambda r: httpx2.Response(200, json={"category": "dining", "merchant": None}))
    assert c.categorize("X", -1) == ("dining", None)
    c = _client(lambda r: httpx2.Response(200, json={"category": "lambos", "merchant": "x"}))
    assert c.categorize("X", -1) is None
    c = _client(lambda r: httpx2.Response(200, json={"category": None, "merchant": None}))
    assert c.categorize("X", -1) is None and c.last_error is None


def test_http_client_failures_return_none_with_plain_reason():
    def refused(request):
        raise httpx2.ConnectError("refused")

    def slow(request):
        raise httpx2.ReadTimeout("slow")
    for handler, words in [
        (refused, "could not reach"),
        (slow, "too long"),
        (lambda r: httpx2.Response(500), "HTTP 500"),
        (lambda r: httpx2.Response(200, content=b"not json"), "could not be read"),
        (lambda r: httpx2.Response(200, json=["a list"]), "could not be read"),
    ]:
        c = _client(handler)
        assert c.categorize("X", -1) is None
        assert c.last_error and words in c.last_error


def test_http_client_real_connection_refused():
    c = HttpModelClient("http://127.0.0.1:9/categorize", timeout_s=0.2)  # nothing listens on port 9
    assert c.categorize("X", -1) is None and c.last_error


def test_contribution_only_transfers_for_accounts_like_ira(db):
    a = make_account(db)
    assert suggest(db, "CHURCH CONTRIBUTION", -5000, a, None).category == "uncategorized"
    assert suggest(db, "IRA CONTRIBUTION", -50000, a, None).category == "transfer"
    assert suggest(db, "ROTH CONTRIBUTION", -50000, a, None).category == "transfer"


def test_zelle_beats_transfer(db):
    a = make_account(db)
    s = suggest(db, "ONLINE TRANSFER TO JANE DOE ZELLE", -4000, a, None)
    assert (s.merchant, s.category) == ("Zelle", "uncategorized")


def test_travel_needs_an_airline_word(db):
    a = make_account(db)
    for raw in ["UNITED HEALTHCARE", "DELTA DENTAL", "SOUTHWEST GAS"]:
        assert suggest(db, raw, -100, a, None).category != "travel", raw
    assert suggest(db, "UNITED AIRLINES 0162345678", -30000, a, None).category == "travel"


def test_http_client_cooldown_after_failure():
    calls, clock, fail = [], [100.0], [True]

    def handler(request):
        calls.append(1)
        if fail[0]:
            return httpx2.Response(500)
        return httpx2.Response(200, json={"category": "dining", "merchant": None})
    c = _client(handler, cooldown_s=60, now=lambda: clock[0])
    assert c.categorize("X", -1) is None
    reason = c.last_error
    assert reason and len(calls) == 1
    clock[0] = 130.0
    assert c.categorize("X", -1) is None and len(calls) == 1 and c.last_error == reason
    clock[0] = 161.0
    fail[0] = False
    assert c.categorize("X", -1) == ("dining", None)
    assert len(calls) == 2 and c.last_error is None
    c.close()


def test_rule_suggestion_is_none_only_when_nothing_matches(db):
    from steward.services.categorize import NO_MATCH, rule_suggestion
    assert rule_suggestion(db, "NETFLIX.COM").category == "subscriptions"
    assert rule_suggestion(db, "ZELLE TO SAM").merchant == "Zelle"       # a built-in that leaves the row for Review
    assert rule_suggestion(db, "SQ *MYSTERY") is None
    assert NO_MATCH == Suggestion(None, "uncategorized", None, CategorySource.none)


def test_investment_accounts_sort_their_own_rows_and_never_ask_the_model(db):
    """Roadmap 12: in an investment account a trade, fee or reinvestment is Investment activity, a dividend Interest, a
    contribution still a transfer; a store rule (AMZN) never fires on a trade; the household's own rule still wins."""
    from steward.db.models import AccountType
    brk = make_account(db, "Taxable", type="brokerage_taxable")

    class Boom:
        def categorize(self, *a):
            raise AssertionError("the model was asked about an investment account's row")

    for raw, cat in [("BUY VTI 10 SHS", "investment"), ("SELL VXUS", "investment"), ("BUY AMZN 2 SHS", "investment"),
                     ("REINVEST DIVIDEND VTI", "investment"), ("ADVISORY FEE Q3", "investment"),
                     ("DIVIDEND RECEIVED VTI", "interest"), ("INTEREST PAID", "interest"),
                     ("LONG TERM CAP GAIN VFIAX", "interest"), ("IRA CONTRIBUTION", "transfer")]:
        assert suggest(db, raw, -100, brk, Boom()).category == cat, raw
    db.add(MerchantRule(pattern="BUY VTI 10 SHS", category="gifts", merchant="VTI", is_business=False,
                        source=CategorySource.correction))
    db.commit()
    assert suggest(db, "BUY VTI 10 SHS", -100, brk, Boom()).category == "gifts"
    assert rule_suggestion(db, "BUY AMZN 2 SHS", AccountType.checking).category == "shopping"   # elsewhere, as before


def test_rows_sorted_as_investments_lose_the_models_guess(db):
    from steward.db.models import AccountType
    from steward.services.categorize import sort_investment_rows
    from tests.factories import make_txn
    acct = make_account(db, "Acct 4471", type="unknown")
    buy = make_txn(db, acct, date(2026, 10, 1), -50000, "BUY VTI 10 SHS")
    buy.guess_category, buy.guess_pct = "shopping", 40
    db.flush()
    acct.type = AccountType.brokerage_taxable
    assert sort_investment_rows(db, acct) == 1
    assert (buy.category, buy.guess_category, buy.guess_pct) == ("investment", None, None)


def test_an_account_typed_as_investments_has_its_rows_sorted(client, db):
    """SimpleFIN accounts arrive with no type: rows the model or nobody sorted move once a person sets the type."""
    from tests.factories import make_txn, make_user
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})
    acct = make_account(db, "Acct 4471", type="unknown")
    buy = make_txn(db, acct, date(2026, 10, 1), -50000, "BUY VTI 10 SHS")
    div = make_txn(db, acct, date(2026, 10, 2), 1200, "DIVIDEND RECEIVED", category="income", category_source=CategorySource.model)
    mine = make_txn(db, acct, date(2026, 10, 3), -900, "SOMETHING", category="gifts", category_source=CategorySource.correction)
    db.commit()
    assert client.patch(f"/api/b/ours/accounts/{acct.id}", json={"type": "brokerage_taxable"}).status_code == 200
    db.commit()
    for t in (buy, div, mine):
        db.refresh(t)
    assert (buy.category, div.category, mine.category) == ("investment", "interest", "gifts")
    # Final review 3: typed wrongly and corrected, its Investment activity goes back to Review.
    assert client.patch(f"/api/b/ours/accounts/{acct.id}", json={"type": "checking"}).status_code == 200
    db.commit()
    for t in (buy, div, mine):
        db.refresh(t)
    assert (buy.category, buy.category_source, div.category, mine.category) == ("uncategorized", CategorySource.none, "interest", "gifts")


def test_the_card_payment_wordings_are_transfers(db):
    """Phase 12 decision 9: the issuers' checking-side wording for a card payment."""
    a = make_account(db)
    for raw in ("CHASE CREDIT CRD AUTOPAY 123456", "CAPITAL ONE CRD EPAY", "BARCLAYS CRD AUTOPAY", "SYNCHRONY EPAYMENT",
                "WELLS FARGO CARD E-PAYMENT", "BANK OF AMERICA CRCARDPMT", "US BANK CARD PMT", "CITI CARD PAYMENT",
                "CITI AUTOPAY PAYMENT", "AMEX EPAYMENT ACH PMT", "DISCOVER E-PAYMENT", "APPLECARD GSBANK PAYMENT"):
        s = suggest(db, raw, -25000, a, None)
        assert (s.category, s.source) == ("transfer", CategorySource.rule), raw
    assert suggest(db, "CARDIO CLASS PMT", -2000, a, None).category == "uncategorized"   # no "CARD PMT" in CARDIO


def test_interest_a_card_charges_is_a_fee_and_interest_earned_stays(db):
    """Phase 12 decision 10: the built-in Interest rule on money out is a Fee; on money in, Interest; a household
    rule for interest is left as the person made it."""
    a = make_account(db, "Card", type="credit")
    out = suggest(db, "INTEREST CHARGED ON PURCHASES", -1234, a, None)
    assert (out.category, out.source) == ("fees", CategorySource.rule)
    assert suggest(db, "INTEREST PAID", 312, a, None).category == "interest"
    db.add(MerchantRule(pattern="INTEREST CHARGED ON PURCHASES", merchant="Card", category="interest",
                        is_business=None, source=CategorySource.correction))
    db.commit()
    assert suggest(db, "INTEREST CHARGED ON PURCHASES", -1234, a, None).category == "interest"
    assert rule_suggestion(db, "INTEREST CHARGE").category == "interest"                  # no amount: as before
