from datetime import date

from steward.db.models import CategorySource, MerchantRule, Owner
from steward.deps import now
from steward.services.ingest import ingest_rows
from steward.services.importers.base import ParsedRow
from tests.factories import make_account, make_txn


def test_ingest_categorizes_and_pairs(db):
    chk = make_account(db, "Checking")
    sav = make_account(db, "Savings", type="savings", institution_name="Other")
    make_txn(db, sav, date(2026, 10, 5), 100000, "TRANSFER FROM CHECKING")
    db.add(MerchantRule(pattern="GREENLEAF MARKET", merchant="Greenleaf", category="groceries",
                        is_business=None, source=CategorySource.correction)); db.commit()
    rows = [
        ParsedRow(date(2026, 10, 3), -5412, "GREENLEAF MARKET #12", "a"),
        ParsedRow(date(2026, 10, 1), 412000, "PAYROLL ACME CORP", "b"),
        ParsedRow(date(2026, 10, 5), -100000, "ONLINE TRANSFER TO SAV ...1234", "c"),
        ParsedRow(date(2026, 10, 6), -1234, "SQ *MYSTERY SHOP", "d"),
    ]
    new = ingest_rows(db, chk, rows, batch=None, now=now(), model=None)
    db.commit()
    by = {t.raw_description: t for t in new}
    g = by["GREENLEAF MARKET #12"]
    assert (g.merchant, g.category, g.category_source) == ("Greenleaf", "groceries", CategorySource.correction)
    assert by["PAYROLL ACME CORP"].category == "income" and by["PAYROLL ACME CORP"].category_source == CategorySource.rule
    x = by["ONLINE TRANSFER TO SAV ...1234"]
    assert x.is_transfer and x.category == "transfer" and x.transfer_peer_id is not None
    m = by["SQ *MYSTERY SHOP"]
    assert m.category == "uncategorized" and m.category_source == CategorySource.none and m.reviewed_at is None


def test_business_account_defaults_is_business(db):
    biz = make_account(db, "Biz", type="business_checking", owner=Owner.business)
    new = ingest_rows(db, biz, [ParsedRow(date(2026, 10, 1), -100, "CLOUDHOST INC", None)], batch=None, now=now(), model=None)
    assert new[0].is_business is True


class _SaysTransfer:
    last_error = None

    def categorize(self, description, amount_cents):
        return ("transfer", None)


def test_model_transfer_suggestion_is_rule_sourced(db):
    a = make_account(db, "Checking")
    (t,) = ingest_rows(db, a, [ParsedRow(date(2026, 10, 1), -100, "ODD WORDING", None)],
                       batch=None, now=now(), model=_SaysTransfer())
    assert t.is_transfer and t.category == "transfer" and t.category_source == CategorySource.rule


class _Batches:
    """A categorizer with categorize_batch: dining for any CAFE, nothing otherwise. Records each batch."""

    def __init__(self, fail=False):
        self.calls, self.fail, self.missed, self.last_error = [], fail, False, None

    def categorize(self, d, c):
        raise AssertionError("ingest must use categorize_batch when the client has it")

    def categorize_batch(self, rows, examples=()):
        self.calls.append(list(rows))
        if self.fail:
            self.missed = True
            return None
        return [("dining", None) if "CAFE" in d else None for d, _ in rows]


def test_rows_no_rule_matches_go_to_the_model_in_one_batch(db):
    chk = make_account(db, "Checking")
    model = _Batches()
    rows = [ParsedRow(date(2026, 10, 1), 412000, "PAYROLL ACME CORP", "p")] + \
           [ParsedRow(date(2026, 10, 2), -900 - i, f"HARBOR CAFE {chr(65 + i % 26)}", f"r{i}") for i in range(30)]
    new = ingest_rows(db, chk, rows, batch=None, now=now(), model=model)
    assert len(model.calls) == 1 and len(model.calls[0]) == 30
    assert all(d.startswith("HARBOR CAFE") for d, _ in model.calls[0])     # the payroll row matched a rule
    cafes = [t for t in new if t.raw_description.startswith("HARBOR CAFE")]
    assert all((t.category, t.category_source) == ("dining", CategorySource.model) for t in cafes)
    assert model.missed is False


def test_past_one_batch_the_rest_wait_for_the_catch_up(db):
    chk = make_account(db, "Checking")
    model = _Batches()
    rows = [ParsedRow(date(2026, 10, 2), -900, f"BEAN CAFE {i:03d}", f"r{i}") for i in range(120)]
    new = ingest_rows(db, chk, rows, batch=None, now=now(), model=model)
    assert [len(c) for c in model.calls] == [50]
    assert sum(t.category_source == CategorySource.model for t in new) == 50
    assert sum(t.category_source == CategorySource.none for t in new) == 70
    assert model.missed is True


def test_a_failed_batch_leaves_rows_for_review(db):
    chk = make_account(db, "Checking")
    model = _Batches(fail=True)
    new = ingest_rows(db, chk, [ParsedRow(date(2026, 10, 2), -900, "BEAN CAFE", "r")], batch=None, now=now(),
                      model=model)
    assert (new[0].category, new[0].category_source) == ("uncategorized", CategorySource.none) and model.missed


def test_a_client_without_batches_is_asked_row_by_row(db):
    chk = make_account(db, "Checking")

    class OneAtATime:
        last_error = None

        def categorize(self, d, c):
            return ("dining", "Bean Cafe") if "CAFE" in d else None
    new = ingest_rows(db, chk, [ParsedRow(date(2026, 10, 2), -900, "BEAN CAFE", "r"),
                                ParsedRow(date(2026, 10, 2), -900, "MYSTERY", "s")], batch=None, now=now(),
                      model=OneAtATime())
    assert [(t.category, t.merchant) for t in new] == [("dining", "Bean Cafe"), ("uncategorized", None)]


def test_the_models_business_hint_is_kept_for_money_out_only(db):
    chk = make_account(db, "Checking")

    class Hints:
        last_error, missed = None, False

        def categorize_batch(self, rows, examples=()):
            return [("subscriptions", "Noteflow", 87) for _ in rows]

    rows = [ParsedRow(date(2026, 10, 3), -2_900, "NOTEFLOW PRO", "h1"),
            ParsedRow(date(2026, 10, 4), 2_900, "NOTEFLOW PRO REFUND", "h2")]
    new = ingest_rows(db, chk, rows, batch=None, now=now(), model=Hints())
    assert [(t.category, t.business_hint, t.business_pct) for t in new] == [
        ("subscriptions", 87, 0), ("subscriptions", None, 0)]


def test_transaction_text_reaches_only_the_categorizer_and_never_with_more_than_4_digits(db):
    import json
    import re

    import httpx2

    from steward.services.categorizer_client import HttpModelClient
    chk = make_account(db, "Checking")
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append((request.url.host, body))
        return httpx2.Response(200, json={"rows": [{"category": "subscriptions", "merchant": None, "business": 90}
                                                   for _ in body["rows"]]})
    client = HttpModelClient("http://gateway-box:8430/v1/categorize", transport=httpx2.MockTransport(handler))
    rows = [ParsedRow(date(2026, 10, 3), -2_900, "NOTEFLOW PRO 4417002918 ACCT 123456789012", "m1")]
    new = ingest_rows(db, chk, rows, batch=None, now=now(), model=client)
    assert new[0].business_hint == 90
    assert [h for h, _ in seen] == ["gateway-box"]
    sent = [r["description"] for _, b in seen for r in b["rows"]]
    assert sent and all(not re.search(r"\d{5,}", d) for d in sent)
    assert not any("anthropic" in h for h, _ in seen)


from steward.services.categorizer_client import Guess  # noqa: E402


class _Unsure:
    """dining for a CAFE, a guess of home for a CENTER, nothing for the rest; records the examples it was given."""
    last_error = None
    missed = False
    features = frozenset({"examples"})

    def __init__(self):
        self.examples = []

    def categorize(self, d, c):
        return None

    def categorize_batch(self, rows, examples=()):
        self.examples.append(list(examples))
        return [("dining", "Bean Cafe") if "CAFE" in d else Guess("home", 45) if "CENTER" in d else Guess(None, 30)
                for d, _ in rows]


def test_an_unsure_answer_keeps_the_guess_and_every_asked_row_remembers_it_was_asked(db):
    """Phase 12 decision 4 and ruling 14."""
    a = make_account(db)
    db.add(MerchantRule(pattern="HARBOR GRILL", merchant="Harbor Grill", category="dining", is_business=None,
                        source=CategorySource.correction)); db.commit()
    model = _Unsure()
    at = now()
    rows = [ParsedRow(date(2026, 10, 3), -500, "BEAN CAFE", "a"), ParsedRow(date(2026, 10, 3), -8000, "UNION SERVICE CENTER", "b"),
            ParsedRow(date(2026, 10, 3), -900, "POS PURCHASE", "c"), ParsedRow(date(2026, 10, 3), -4000, "ZELLE TO SAM", "d"),
            ParsedRow(date(2026, 10, 3), -4100, "HARBOR GRILL 22", "e")]
    new = {t.raw_description: t for t in ingest_rows(db, a, rows, batch=None, now=at, model=model)}
    db.commit()
    cafe, center, pos, zelle, grill = (new[k] for k in ("BEAN CAFE", "UNION SERVICE CENTER", "POS PURCHASE", "ZELLE TO SAM", "HARBOR GRILL 22"))
    assert (cafe.category, cafe.category_source, cafe.model_asked_at, cafe.guess_category) == ("dining", CategorySource.model, at, None)
    assert (center.category, center.guess_category, center.guess_pct, center.model_asked_at) == ("uncategorized", "home", 45, at)
    assert (pos.category, pos.guess_category, pos.guess_pct, pos.model_asked_at) == ("uncategorized", None, 30, at)
    assert zelle.model_asked_at is None and grill.model_asked_at is None        # rules answered: never asked
    assert model.examples == [[("HARBOR GRILL", "dining")]]                     # the household's rule went along


def test_no_examples_and_no_scan_unless_the_gateway_lists_examples(db, monkeypatch):
    from steward.services import ingest
    db.add(MerchantRule(pattern="HARBOR GRILL", merchant="Harbor Grill", category="dining", is_business=None,
                        source=CategorySource.correction)); db.commit()
    scans = []
    real = ingest.example_rules
    monkeypatch.setattr(ingest, "example_rules", lambda d: scans.append(1) or real(d))
    model = _Unsure()
    model.features = frozenset()                    # HttpModelClient's until the gateway's health says
    assert ingest.teaching_examples(db, model) == [] and scans == []
    model.features = frozenset({"guess", "examples"})
    assert ingest.teaching_examples(db, model) == [("HARBOR GRILL", "dining")] and scans == [1]


def test_rows_the_model_never_saw_have_no_model_asked_at(db):
    a = make_account(db)
    rows = [ParsedRow(date(2026, 10, 3), -500, f"BEAN CAFE {i}", str(i)) for i in range(3)]
    new = ingest_rows(db, a, rows, batch=None, now=now(), model=None)
    assert all(t.model_asked_at is None and t.guess_category is None for t in new)


class _PerRow:
    """No categorize_batch: the per-row fallback. None is a failed call."""
    last_error = None
    missed = False

    def categorize(self, d, c):
        return None


def test_rows_no_model_looked_at_are_not_marked_asked(db):
    from steward.services.categorizer_client import NullModelClient
    a = make_account(db)
    rows = [ParsedRow(date(2026, 10, 3), -500, f"BEAN CAFE {i}", str(i)) for i in range(3)]
    for model in (NullModelClient(), _PerRow()):
        new = ingest_rows(db, a, rows, batch=None, now=now(), model=model)
        assert all(t.model_asked_at is None for t in new)
        for t in new:
            db.delete(t)
        db.flush()
