"""merchant_detail (spec 4.4): rows with store names, cleaned before anyone sees them, at most 92 days and 200 rows."""
import re
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import Account, AccountType, AdvisorAlias, CategorySource, Transaction
from steward.demo import seed, seed_people
from steward_boundary import tools as T
from tests.advisor.helpers import call

TODAY = date(2026, 10, 20)


@pytest.fixture
def household(books, ours, engine):
    with Session(engine) as db:
        seed(db, years=1, seed=7)
    with Session(books.directory) as ddb:
        seed_people(ddb, ours.id)
    return next(p.id for p in books.people(ours.id) if p.username == "alex")


def checking(engine) -> int:
    with Session(engine) as db:
        return db.scalar(select(Account.id).where(Account.type == AccountType.checking).order_by(Account.id))


def add_rows(engine, rows):
    with Session(engine) as db:
        db.add_all([Transaction(account_id=a, posted_at=d, amount_cents=c, raw_description=raw, merchant=m,
                                category=cat, category_source=CategorySource.none) for a, d, c, raw, m, cat in rows])
        db.commit()


def ask(books, ours, uid, engine, **inp):
    base = {"reason": "Totals can't name them.", "start": "2026-10-01", "end": "2026-10-20", "category": None,
            "payees": None}
    return call(engine, ours, books.people(ours.id), uid, T.MERCHANT, {**base, **inp}, TODAY)


def test_rows_carry_date_amount_category_store_and_account_alias(books, ours, engine, household):
    add_rows(engine, [(checking(engine), date(2026, 10, 18), -1599, "STREAMBOX 800-555-0100", "StreamBox",
                       "subscriptions")])
    r = ask(books, ours, household, engine, category="subscriptions")
    assert r["error"] is None
    row = next(x for x in r["content"]["rows"] if x["merchant"] == "StreamBox")
    assert row == {"date": "2026-10-18", "amount_cents": -1599, "category": "subscriptions", "merchant": "StreamBox",
                   "account": row["account"]}
    assert re.fullmatch(r"Account [0-9]+", row["account"])
    assert all(x["category"] == "subscriptions" for x in r["content"]["rows"])


def test_names_and_long_numbers_in_store_names_never_reach_the_rows(books, ours, engine, household):
    add_rows(engine, [(checking(engine), date(2026, 10, 19), -2500, "ZELLE TO SAM 4417002918 CONF", None, "gifts")])
    r = ask(books, ours, household, engine, category="gifts")
    stores = [x["merchant"] for x in r["content"]["rows"]]
    assert stores, r
    for s in stores:
        assert not re.search(r"(?i)\bsam\b", s), s
        assert "4417002918" not in s and not re.search(r"\d{5,}", s.replace(" ", "")), s
    assert any("[name]" in s for s in stores)


def test_store_names_go_through_the_canonical_normaliser_and_the_strict_stored_text_path():
    """Controller addition: look-alike letters, zero-width characters and full-width digits can't hide a name or a
    number from the cleaning, and what comes out passes the strict stored-text rule."""
    from steward.advisor.identifiers import Identifier
    from steward.advisor.tools.merchant import clean_store
    from steward_boundary.text import is_stored_safe

    idents = (Identifier("Sam", "name", "[name]", name=True),)
    cases = {
        "Venmo S​am": "[name]",                                   # zero-width inside the name
        "Venmo Ｓａｍ": "[name]",                          # full-width letters
        "Venmo Sаm": "[name]",                                    # Cyrillic a
        "Shop ４４１７００２９１８": None,   # full-width digits
        "Café​ Rouge": None,
    }
    for raw, wants in cases.items():
        out = clean_store(raw, idents)
        assert is_stored_safe(out), (raw, out)
        assert "​" not in out and not re.search(r"\d{5,}", out), (raw, out)
        assert not re.search(r"(?i)\bs\W*a\W*m\b", out), (raw, out)
        if wants:
            assert wants in out, (raw, out)
    assert not re.search(r"\d{5}", re.sub(r"\D", "", clean_store(list(cases)[3], idents)))
    assert clean_store("", ()) == "[payee]"
    assert clean_store("​", ()) == "[payee]"


def _idents():
    from steward.advisor.identifiers import Identifier
    return (Identifier("Sam", "name", "[name]", name=True), Identifier("Margaret Ellis", "name", "[name]", name=True),
            Identifier("Samantha Becker", "name", "[name]", name=True),
            Identifier("1234 Elm Street", "address", "[address]"), Identifier("4417002918", "number", "[account number]"),
            Identifier("sam@example.com", "email", "[email]"))


def test_a_store_name_holding_an_address_an_account_number_a_name_or_an_email_is_masked():
    """Task 6.5: mask_numbers, the canonical normaliser, the exact pass and the survivors check, in that order."""
    from steward.advisor.tools.merchant import clean_store
    from steward_boundary.text import is_stored_safe
    for raw, wants, gone in (("ACME 1234 ELM STREET", "[address]", "elm"),
                             ("ZELLE TO SAM 4417002918 CONF", "[name]", "4417002918"),
                             ("TRANSFER 4417 0029 18", None, "44170029"),
                             ("PAYPAL sam@example.com", "[email]", "example"),
                             ("Venmo Margaret Ellis", "[name]", "ellis")):
        out = clean_store(raw, _idents())
        assert is_stored_safe(out) and not re.search(r"\d{5,}", out.replace(" ", "")), (raw, out)
        assert gone not in out.casefold().replace(" ", ""), (raw, out)
        if wants:
            assert wants in out, (raw, out)


def test_cutting_a_long_store_name_never_leaves_part_of_a_name_or_a_broken_token():
    """Task 6.5: the 60-character cut comes after the exact pass and never splits a word or a bracket token, so a
    known name cut at the boundary ("Sama" of "Samantha", "Elli" of "Ellis") can't slip through."""
    from steward.advisor.tools.merchant import clean_store
    from steward_boundary.text import is_stored_safe
    for raw in ("z" * 55 + " Samantha Becker", "x" * 55 + " Ellis", "a" * 45 + " Mar garet Ellis",
                "w" * 50 + " Margaret Ellis", "q" * 58 + " Sam"):
        out = clean_store(raw, _idents())
        assert len(out) <= 60 and is_stored_safe(out), (raw, out)
        for part in ("sama", "elli", "beck", "sam"):
            assert not re.search(rf"(?i)\b{part}", out), (raw, out)
        assert out.count("[") == out.count("]"), (raw, out)


def test_a_period_longer_than_92_days_is_refused(books, ours, engine, household):
    assert ask(books, ours, household, engine, start="2026-07-01", end="2026-10-20")["error"] == "That period is too long."
    assert ask(books, ours, household, engine, start="2026-07-21", end="2026-10-20")["error"] is None   # 92 days
    assert ask(books, ours, household, engine, start="2026-10-20", end="2026-10-01")["error"] == \
        "That input wasn't understood."


def test_at_most_200_rows_and_more_says_so(books, ours, engine, household):
    a = checking(engine)
    add_rows(engine, [(a, date(2026, 10, 1) + timedelta(days=i % 3), -100 - i, f"CAFE {i % 7}", None, "dining")
                      for i in range(205)])
    r = ask(books, ours, household, engine, start="2026-10-01", end="2026-10-03", category="dining")
    assert len(r["content"]["rows"]) == T.MERCHANT_ROWS and r["content"]["more"] is True


def test_payee_aliases_name_their_payees_and_unknown_ones_find_nothing(books, ours, engine, household):
    add_rows(engine, [(checking(engine), date(2026, 10, 18), -1599, "STREAMBOX", "StreamBox", "subscriptions")])
    call(engine, ours, books.people(ours.id), household, "recurring", {}, TODAY)      # gives payees their aliases
    with Session(engine) as db:
        alias = db.scalar(select(AdvisorAlias.alias).where(AdvisorAlias.kind == "payee").order_by(AdvisorAlias.id))
    r = ask(books, ours, household, engine, payees=[alias])
    assert [p["payee"] for p in r["content"]["payees"]] == [alias] and r["content"]["payees"][0]["name"]
    assert ask(books, ours, household, engine, payees=["Payee 999"])["content"] == {"rows": [], "payees": [],
                                                                                    "more": False}
    assert ask(books, ours, household, engine, payees=["Sam"])["error"] == "That input wasn't understood."
