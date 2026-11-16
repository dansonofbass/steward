from datetime import date, datetime, time, timezone

import pytest
from sqlalchemy import func, select, text

from steward.db.directory_models import Membership, User
from steward.db.models import (Account, BalanceSnapshot, BusinessState, Fact, Holding, SsEarnings, TaxState,
                               Transaction)
from steward.demo import DEMO_LOGINS, seed, seed_people
from tests.personal_strings import private_matcher, tokens


def _sig(db):
    txns = db.execute(select(Transaction.posted_at, Transaction.amount_cents, Transaction.raw_description)
                      .order_by(Transaction.id)).all()
    snaps = db.execute(select(BalanceSnapshot.account_id, BalanceSnapshot.as_of, BalanceSnapshot.balance_cents)
                       .order_by(BalanceSnapshot.account_id, BalanceSnapshot.as_of)).all()
    return txns, snaps


def test_seed_is_deterministic_and_realistic(db):
    counts = seed(db, years=1, seed=7)
    assert counts["accounts"] == 13
    assert 900 <= counts["transactions"] <= 1600
    uncategorized = db.scalar(select(func.count()).select_from(Transaction).where(Transaction.category == "uncategorized"))
    assert 0.1 <= uncategorized / counts["transactions"] <= 0.3
    # every account has a snapshot for the last day
    last = db.scalar(select(func.max(BalanceSnapshot.as_of)))
    n_accounts = db.scalar(select(func.count()).select_from(Account))
    assert db.scalar(select(func.count()).select_from(BalanceSnapshot).where(BalanceSnapshot.as_of == last)) == n_accounts


def test_seed_people_makes_two_managers_once(ddb, ours):
    seed_people(ddb, ours.id)
    seed_people(ddb, ours.id)
    assert ddb.scalar(select(func.count()).select_from(User)) == 2
    assert list(ddb.scalars(select(Membership.role).where(Membership.book_id == ours.id))) == ["manager", "manager"]


def test_seed_same_seed_same_data(engine):
    from sqlalchemy.orm import Session
    with Session(engine) as a:
        seed(a, years=1, seed=3)
        sig_a = _sig(a)
    # fresh db
    from steward.db.models import Base
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    with Session(engine) as b:
        seed(b, years=1, seed=3)
        sig_b = _sig(b)
    assert sig_a == sig_b


def test_no_real_names(db):
    seed(db, years=1)
    descs = " ".join(d for (d,) in db.execute(select(Transaction.raw_description)).all())
    for forbidden in ("Chase", "Marcus", "Betterment", "Empower", "depot"):
        assert forbidden.lower() not in descs.lower()
    matches = private_matcher()   # the family's names; the list is private (tests/personal_strings.py)
    if matches is None:
        pytest.skip("no private term list here (STEWARD_PRIVATE_TERMS); the institution checks above passed")
    assert not matches(descs)


def test_transfer_and_uncategorized_invariants(db):
    seed(db, years=1)
    rows = db.scalars(select(Transaction)).all()
    for t in rows:
        if t.category == "transfer":
            assert t.is_transfer and t.category_source.value == "rule"
        if t.category == "uncategorized":
            assert t.category_source.value == "none"
    # card payments pair up: equal and opposite on the same day
    pays = [t for t in rows if t.category == "transfer" and "CARD" in t.raw_description]
    credits = [t for t in rows if t.raw_description == "PAYMENT THANK YOU"]
    assert pays and len(pays) == len(credits)
    assert sorted((t.posted_at, -t.amount_cents) for t in pays) == sorted((t.posted_at, t.amount_cents) for t in credits)


def test_every_account_has_a_snapshot_every_day(db):
    seed(db, years=1)
    rows = db.execute(select(BalanceSnapshot.account_id, func.count(), func.min(BalanceSnapshot.as_of),
                             func.max(BalanceSnapshot.as_of)).group_by(BalanceSnapshot.account_id)).all()
    assert len(rows) == 13
    for _, n, first, last in rows:
        assert n == (last - first).days + 1 == 366


def test_liabilities_never_positive(db):
    from steward.db.models import AccountType
    seed(db, years=1)
    liabilities = (AccountType.credit, AccountType.mortgage, AccountType.business_credit)
    worst = db.scalar(select(func.max(BalanceSnapshot.balance_cents)).join(Account)
                      .where(Account.type.in_(liabilities)))
    assert worst <= 0


def test_demo_household_is_ready_for_the_plan(db, ddb, ours):
    from datetime import date

    from steward.services.plan_inputs import build_inputs, missing, setup_items
    counts = seed(db, years=2, seed=7)
    seed_people(ddb, ours.id)
    assert counts["accounts"] == 13 and counts["children"] == 3 and counts["holdings"] == 6
    today = date(2026, 10, 13)
    assert missing(setup_items(db, today)) == []
    pi = build_inputs(db, today)
    assert pi.observed.gift_12mo_cents == 1_000_000 and pi.observed.consulting_12mo_cents > 0
    assert pi.household.default_mix_symbols == ("ACMEX",)
    assert len(pi.household.jr.earnings) == 19 and len(pi.household.spouse.earnings) == 8
    assert pi.names["spouse"] == "Sam"


def test_demo_plan_returns_ages(client, db, ddb, ours, frozen):
    seed(db, years=2, seed=7)
    seed_people(ddb, ours.id)
    assert client.post("/api/auth/login", json={"username": "alex", "password": "pw-demo-alex-2026"}).status_code == 200
    body = client.get("/api/b/ours/plan").json()
    assert body["result"]["comfortable_age"] is not None and body["result"]["likely_age"] is not None
    assert body["levers"]["try_notes"] == {"spouse_earnings": "No history yet"}


def test_reseeding_with_force_keeps_one_earnings_record(db):
    seed(db, years=1, seed=1)
    seed(db, years=1, seed=2)
    from steward.db.models import SsEarnings
    assert db.scalar(select(func.count()).select_from(SsEarnings).where(SsEarnings.person == "jr")) == 19


def test_the_demo_household_has_a_business_set_up(db):
    from steward.db.models import BusinessRule, BusinessState
    seed(db, years=1, seed=7)
    state = dict(db.execute(select(BusinessState.key, BusinessState.value)).all())
    assert state["type"] == "sole_prop" and "expect:2026" in state and state["car_method:2025"] == "standard"
    kinds = sorted(r.kind for r in db.scalars(select(BusinessRule)))
    assert kinds == ["account", "account", "client"]
    biz = db.scalars(select(Transaction).where(Transaction.is_business.is_(True))).all()
    assert biz and all(t.business_pct == 100 and t.business_source == "rule" for t in biz)
    asked = db.scalars(select(Transaction).where(Transaction.business_hint >= 60)).all()
    assert 1 <= len(asked) <= 6 and all(t.amount_cents < 0 and t.business_pct == 0 for t in asked)


def test_the_demo_401k_has_its_own_deposits_and_its_funds_costs_come_from_the_table(db):
    seed(db, years=1, seed=7)
    k = db.scalar(select(Account).where(Account.name == "401(k)"))
    assert {t.raw_description for t in db.scalars(select(Transaction).where(Transaction.account_id == k.id))} == {
        "EMPLOYEE DEFERRAL", "EMPLOYER MATCH"}
    assert db.scalar(select(Holding).where(Holding.symbol == "ACMEX")).expense_ratio_bp is None   # not in the table: "cost unknown · Add"
    bp = {h.symbol: h.expense_ratio_bp for h in db.scalars(select(Holding).where(Holding.symbol != "ACMEX"))}
    assert bp == {"VTI": 3, "VXUS": 5, "BND": 3, "VFIFX": 8, "FXAIX": 2}   # the shipped table knows every other fund
    assert k.sends_holdings and k.holdings_seen_at is not None and k.transactions_seen_at is not None
    tax = db.scalar(select(Account).where(Account.name == "Taxable"))
    assert tax.holdings_seen_at is not None and tax.transactions_seen_at is None


def _everything(db):
    return (_sig(db),
            db.execute(select(Holding.as_of, Holding.symbol, Holding.market_value_cents).order_by(Holding.id)).all(),
            db.execute(select(Fact.key, Fact.value, Fact.as_of).order_by(Fact.id)).all(),
            db.execute(select(TaxState.key, TaxState.value).order_by(TaxState.key)).all(),
            db.execute(select(BusinessState.key, BusinessState.value).order_by(BusinessState.key)).all(),
            db.execute(select(SsEarnings.person, SsEarnings.year).order_by(SsEarnings.person, SsEarnings.year)).all())


def test_seed_with_no_end_is_the_demo_as_it_was(engine):
    from sqlalchemy.orm import Session
    from steward.db.models import Base
    with Session(engine) as a:
        seed(a, years=1)
        plain = _everything(a)
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    with Session(engine) as b:
        seed(b, years=1, end=date(2026, 10, 12))
        assert _everything(b) == plain
    first_noteflow = min(d for d, _, raw in plain[0][0] if raw == "NOTEFLOW PRO")
    assert first_noteflow == date(2026, 7, 3)
    assert ("withholding:2026", '{"federal_ytd_cents": 1610000, "state_ytd_cents": 540000, "as_of": "2026-09-30"}') in plain[3]
    assert max(y for _, y in plain[5]) == 2025


def test_seed_with_an_end_moves_every_date_with_it(db):
    end = date(2027, 2, 9)
    seed(db, years=1, end=end)
    assert db.scalar(select(func.max(BalanceSnapshot.as_of))) == end
    assert db.scalar(select(func.max(Transaction.posted_at))) <= end
    assert set(db.scalars(select(Holding.as_of))) == {end}
    assert set(db.scalars(select(Fact.as_of))) == {end}
    assert db.get(TaxState, "withholding:2027") is not None and db.get(TaxState, "return:2026") is not None
    assert '"as_of": "2027-01-31"' in db.get(TaxState, "withholding:2027").value
    assert db.get(BusinessState, "miles:2027") is not None and db.get(BusinessState, "car_method:2026") is not None
    assert max(db.scalars(select(SsEarnings.year))) == 2026
    seen = datetime.combine(end, time(19), timezone.utc)
    assert {a.transactions_seen_at for a in db.scalars(select(Account)) if a.transactions_seen_at} == {seen}


def _book_text(db) -> str:
    """Every text value in the seeded book: names, descriptions, labels, facts, state."""
    tables = db.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'")).scalars().all()
    return " ".join(v for t in tables for row in db.execute(text(f'SELECT * FROM "{t}"')) for v in row
                    if isinstance(v, str))


def test_the_demo_names_only_made_up_people(db, ddb, ours):
    """The public demo and its screenshots show only made-up people (Nov 9). Neither its logins nor anything the seed
    writes holds a term from the private list, and no login is jr: Person 1's owner key, which was the owner's
    initials. The list leaves jr out on purpose (it is a key everywhere), so that one is checked here."""
    seed(db, years=1)
    seed_people(ddb, ours.id)
    logins = " ".join(f"{u} {e} {n}" for u, e, n, _pw in DEMO_LOGINS)
    users = " ".join(f"{u.username} {u.email} {u.display_name}" for u in ddb.scalars(select(User)))
    assert "jr" not in tokens(logins) | tokens(users)
    matches = private_matcher()
    if matches is None:
        pytest.skip("no private term list here (STEWARD_PRIVATE_TERMS); the jr check above passed")
    assert not matches(logins) and not matches(users)
    assert not matches(_book_text(db))


def test_the_demo_and_the_sample_are_the_same_made_up_couple(books, ddb, ours):
    """The demo household and the Sample book show the same two people (books/people.py, SAMPLE_PEOPLE), so a
    screenshot of either names Alex and Sam, and a change to one has to change the other."""
    from steward.books.people import SAMPLE_PEOPLE, household_labels
    seed_people(ddb, ours.id)
    assert household_labels(books.people(ours.id)) == household_labels(SAMPLE_PEOPLE)
    username, _email, name, _pw = DEMO_LOGINS[0]
    assert (username, name) == (SAMPLE_PEOPLE[0].username, SAMPLE_PEOPLE[0].display_name)


def test_seed_people_marks_them_welcomed(ddb, ours):
    seed_people(ddb, ours.id)
    assert all(m.welcome_seen_at is not None for m in ddb.scalars(select(Membership).where(Membership.book_id == ours.id)))
