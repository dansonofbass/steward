"""The tools in every book (spec 4.2) on the demo household and on Margaret: aliases only, the same numbers as the
screens' services, and errors as fixed words."""
import json
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import AdvisorAlias, BalanceSnapshot, CategorySource, Transaction
from steward.demo import seed, seed_people
from steward.demo_parent import seed_parent
from steward.services import networth
from steward.services.spending import flow_view
from tests.advisor.helpers import call

TODAY = date(2026, 10, 13)


@pytest.fixture
def household(books, ours, engine):
    with Session(engine) as db:
        seed(db, years=2, seed=7)
    with Session(books.directory) as ddb:
        seed_people(ddb, ours.id)
    people = books.people(ours.id)
    return engine, ours, people, next(p.id for p in people if p.username == "alex")


def run(h, name, input):
    engine, book, people, jr = h
    out = call(engine, book, people, jr, name, input, TODAY)
    assert out["error"] is None, out
    return out["content"]


def test_book_summary_in_the_household(household, engine):
    out = run(household, "book_summary", {})
    assert out["book_kind"] == "household" and out["today"] == "2026-10-13" and out["asker"] == "Person 1"
    assert [(p["alias"], p["role"], p["is_asker"]) for p in out["people"][:4]] == [
        ("Person 1", "owner", True), ("Person 2", "owner", False), ("Joint", "joint", False), ("Business", "business", False)]
    assert [p["alias"] for p in out["people"] if p["role"] == "child"] == ["Child 1", "Child 2", "Child 3"]
    assert out["people"][0]["age"] == 41 and out["state"] == "CA" and out["filing_status"] == "mfj"
    with Session(engine) as db:
        assert out["net_worth_cents"] == networth.net_worth_on(db, TODAY)


def test_accounts_carry_aliases_never_names(household):
    out = run(household, "accounts", {"include_closed": False})
    assert all(a["account"].startswith("Account ") for a in out["accounts"])
    text = json.dumps(out)
    for name in ("Big Bank", "Rewards Card", "Robo Invest", "High-yield", "kid 1"):
        assert name not in text, name
    assert run(household, "accounts", {"include_closed": False}) == out          # aliases are stable


def test_an_imported_account_arrives_as_a_file_or_a_statement_never_typed_in(books, ours, engine, ddb):
    """Install gate INS-17: a CSV-imported account told Claude it was typed in. The newest import that wasn't undone
    says file or statement; the file's name never goes (P12)."""
    from datetime import datetime, timezone
    from steward.db.models import ImportBatch
    from tests.factories import make_account, make_person
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    with Session(engine) as db:
        typed, csv, pdf, undone, both = (make_account(db, f"zq{n}") for n in range(5))
        db.add_all([
            ImportBatch(account_id=csv.id, filename="zqxwv_checking.csv", format="chase_checking", row_count=3,
                        imported_by=jr.id, imported_at=at),
            ImportBatch(account_id=pdf.id, filename="zqxwv.pdf", format="statement", row_count=9, imported_by=jr.id,
                        imported_at=at, pages=3),
            ImportBatch(account_id=undone.id, filename="zqxwv.csv", format="chase_checking", row_count=1,
                        imported_by=jr.id, imported_at=at, rolled_back_at=at),
            ImportBatch(account_id=both.id, filename="zqxwv.pdf", format="statement", row_count=9, imported_by=jr.id,
                        imported_at=at, pages=2),
            ImportBatch(account_id=both.id, filename="zqxwv.ofx", format="ofx", row_count=4, imported_by=jr.id,
                        imported_at=datetime(2026, 10, 2, tzinfo=timezone.utc)),
        ])
        db.commit()
    out = call(engine, ours, books.people(ours.id), jr.id, "accounts", {"include_closed": False}, TODAY)
    assert out["error"] is None, out
    assert [a["arrives"] for a in out["content"]["accounts"]] == ["manual", "file", "statement", "manual", "file"]
    assert "zqxwv" not in json.dumps(out["content"])


def test_balance_history_ends_this_month_with_the_screens_net_worth(household, engine):
    out = run(household, "balance_history", {"months": 3, "by_account_type": True})
    assert [m["month"] for m in out["months"]] == ["2026-08", "2026-09", "2026-10"]
    with Session(engine) as db:
        assert out["months"][-1]["net_worth_cents"] == networth.net_worth_on(db, TODAY)
        assert out["months"][0]["net_worth_cents"] == networth.net_worth_on(db, date(2026, 8, 31))
        assert {t["account_type"]: t["balance_cents"] for t in out["months"][-1]["by_account_type"]} == \
            networth.by_type_on(db, TODAY)


def test_cash_flow_matches_homes_strip(household, engine):
    out = run(household, "cash_flow", {"months": 12, "by": "category"})
    with Session(engine) as db:
        strip = flow_view(db, TODAY, 12)["months"]
    assert [(m["month"], m["in_cents"], m["out_cents"]) for m in out["months"]] == [
        (p["month"], p["in_cents"], p["out_cents"]) for p in strip]
    assert out["months"][-2]["groups"]
    by_owner = run(household, "cash_flow", {"months": 3, "by": "owner"})
    assert {g["owner"] for m in by_owner["months"] for g in m["groups"]} <= {"Person 1", "Person 2", "Joint"}
    biz = run(household, "cash_flow", {"months": 3, "by": "business"})
    assert [g["business"] for g in biz["months"][0]["groups"]] == [False, True]


def test_cash_flow_is_spendings_money_in_and_out_to_the_cent(household, engine):
    """JR, on #58's open question 3: Ask's cash_flow gives the money in and out Spending shows for the month (Home's
    figure), through the same service, with the same exclusions. September gains a 40% business phone bill (only the
    $60 personal share counts), a reimbursable hotel and a $500 card payment the feed didn't pair (neither counts), a
    paired transfer (never counts) and a $10,000 gift sorted to Gifts (the part past $0 is money in). Every month and
    every grouping agrees with Spending's head; by category and by business the groups add up to it."""
    from datetime import datetime, timezone

    from steward.db.models import Reimburser
    from steward.services import spending as sp
    alias, aid = _checking(household, engine)
    before = run(household, "cash_flow", {"months": 3, "by": None})
    with Session(engine) as db:
        acme = Reimburser(name="Acme", created_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.add(acme)
        db.flush()
        for cents, category, kw in ((-10_000, "utilities", {"business_pct": 40}),
                                    (-30_000, "travel", {"reimburser_id": acme.id}),
                                    (-50_000, "transfer", {}),
                                    (-70_000, "transfer", {"is_transfer": True}),
                                    (1_000_000, "gifts", {})):
            db.add(Transaction(account_id=aid, posted_at=date(2026, 9, 16), amount_cents=cents, raw_description="ROW",
                               category=category, category_source=CategorySource.none, **kw))
        db.commit()
    for by in (None, "category", "business", "owner"):
        out = run(household, "cash_flow", {"months": 3, "by": by})
        with Session(engine) as db:
            for m in out["months"]:
                head = sp.month_view(db, TODAY, sp.first_of(m["month"]))["head"]
                assert (m["in_cents"], m["out_cents"]) == (head["money_in_cents"], head["money_out_cents"]), (by, m)
                assert m["net_cents"] == m["in_cents"] - m["out_cents"]
                if by == "category":
                    assert (sum(g["in_cents"] for g in m["groups"]), sum(g["out_cents"] for g in m["groups"])) == (
                        m["in_cents"], m["out_cents"])
                    assert not {g["category"] for g in m["groups"]} & {"transfer", "reimbursement"}
                if by == "business":
                    assert (m["groups"][0]["in_cents"], m["groups"][0]["out_cents"]) == (m["in_cents"], m["out_cents"])
    sep_before = next(m for m in before["months"] if m["month"] == "2026-09")
    sep = next(m for m in run(household, "cash_flow", {"months": 3, "by": None})["months"] if m["month"] == "2026-09")
    assert sep["net_cents"] - sep_before["net_cents"] == 1_000_000 - 6_000     # the gift, less the phone's personal share


def test_spending_by_category_with_the_period_before(household):
    out = run(household, "spending_by_category", {"start": "2026-09-01", "end": "2026-09-30", "compare_previous": True})
    assert out["period"]["total_out_cents"] == sum(c["out_cents"] for c in out["period"]["categories"])
    assert (out["previous"]["start"], out["previous"]["end"]) == ("2026-08-02", "2026-08-31")


@pytest.mark.parametrize("input, error", [
    ({"start": "2025-01-01", "end": "2026-09-30", "compare_previous": False}, "That period is too long."),
    ({"start": "2026-09-30", "end": "2026-09-01", "compare_previous": False}, "That input wasn't understood."),
])
def test_spending_by_category_refuses_bad_periods(household, input, error):
    engine, book, people, jr = household
    assert call(engine, book, people, jr, "spending_by_category", input, TODAY)["error"] == error


def test_recurring_finds_subscriptions_as_payee_aliases(household):
    out = run(household, "recurring", {})
    monthly = [i for i in out["items"] if i["cadence"] == "monthly" and i["direction"] == "out"]
    assert len(monthly) >= 5 and all(i["payee"].startswith("Payee ") for i in monthly)
    assert "STREAMFLIX" not in json.dumps(out).upper()


def test_holdings_send_symbols_and_classes(household):
    out = run(household, "holdings", {})
    assert {h["symbol"] for h in out["holdings"]} >= {"VTI", "VXUS", "BND", "VFIFX", "FXAIX", "ACMEX"}
    assert {t["asset_class"] for t in out["totals_by_asset_class"]} >= {"us_stock", "intl_stock", "bond", "target_date"}
    assert "Total Stock" not in json.dumps(out)


def test_debts_use_the_household_facts(household):
    out = run(household, "debts", {})
    mortgage = next(d for d in out["debts"] if d["kind"] == "mortgage")
    assert (mortgage["rate_bp"], mortgage["payment_cents"], mortgage["payoff_month"]) == (312.0, 268_000, "2051-03")


def test_wrong_book_and_bad_input_are_fixed_words(margaret, books):
    engine = books.engine_for(margaret)
    with Session(engine) as db:
        seed_parent(db, date(2026, 10, 18))
    people = books.people(margaret.id)
    jr = next(p.id for p in people if p.username == "jr")
    assert call(engine, margaret, people, jr, "plan_result", {}, TODAY)["error"] == "Not in this book."
    assert call(engine, margaret, people, jr, "balance_history", {"months": 0, "by_account_type": False}, TODAY)["error"] \
        == "That input wasn't understood."
    assert call(engine, margaret, people, jr, "balance_history", {"months": 3}, TODAY)["error"] == \
        "That input wasn't understood."
    out = call(engine, margaret, people, jr, "book_summary", {}, TODAY)["content"]
    assert [p["alias"] for p in out["people"]] == ["Parent", "Person 2", "Joint", "Person 3", "Person 4"]


def test_no_every_book_tool_result_names_anything_in_margarets_book(margaret, books):
    engine = books.engine_for(margaret)
    with Session(engine) as db:
        seed_parent(db, date(2026, 10, 18))
    people = books.people(margaret.id)
    jr = next(p.id for p in people if p.username == "jr")
    inputs = {"book_summary": {}, "accounts": {"include_closed": True}, "balance_history": {"months": 6, "by_account_type": True},
              "cash_flow": {"months": 6, "by": "category"}, "recurring": {}, "holdings": {}, "debts": {},
              "spending_by_category": {"start": "2026-07-01", "end": "2026-09-30", "compare_previous": True}}
    text = json.dumps([call(engine, margaret, people, jr, n, i, date(2026, 10, 18)) for n, i in inputs.items()])
    for word in ("Margaret", "Robert", "Wells Fargo", "Fidelity", "Citi", "Westmark", "4417", "Joint checking",
                 "Way2Save", "SSA TREAS", "COUNTY SCHOOLS", "Linda", "Ortiz"):
        assert word not in text, word


def test_holdings_send_a_symbol_only_when_it_is_letters(household, engine):
    """Plan ruling 25: a symbol is free text, so only letters go; anything else (digits, spaces, punctuation) is null."""
    from sqlalchemy import select

    from steward.db.models import Holding
    with Session(engine) as db:
        first = db.scalars(select(Holding).order_by(Holding.id)).first()
        newest = db.scalar(select(Holding.as_of).where(Holding.account_id == first.account_id).order_by(Holding.as_of.desc()))
        for symbol in ("714-555-0102", "Jane Doe", "BRK.B", "12345", " ", None, "abc"):
            db.add(Holding(account_id=first.account_id, as_of=newest, symbol=symbol, name="Odd one", shares_milli=1000,
                           cost_basis_cents=100, market_value_cents=100, expense_ratio_bp=None))
        db.commit()
    out = run(household, "holdings", {})
    odd = [h for h in out["holdings"] if h["value_cents"] == 100 and h["cost_basis_cents"] == 100]
    assert len(odd) == 7
    assert sorted(h["symbol"] or "" for h in odd) == ["", "", "", "", "", "", "ABC"]
    assert all(h["asset_class"] == "other" for h in odd)
    text = json.dumps(out)
    for bad in ("714", "Jane", "BRK", "12345", "Odd one"):
        assert bad not in text, bad


def test_debts_read_each_accounts_own_rate_first(household):
    """Final review minor a: an account's rate beats the mortgage fact, and a card's own rate is sent."""
    from sqlalchemy import select
    from steward.db.models import Account, AccountType
    engine = household[0]
    with Session(engine) as db:
        db.scalars(select(Account).where(Account.type == AccountType.mortgage)).first().rate_bp = 650
        card = db.scalars(select(Account).where(Account.type == AccountType.credit)).first()
        card.rate_bp = 2290
        card_id = card.id
        db.commit()
    out = run(household, "debts", {})
    assert next(d for d in out["debts"] if d["kind"] == "mortgage")["rate_bp"] == 650.0
    assert 2290 in [d["rate_bp"] for d in out["debts"] if d["kind"] != "mortgage"], card_id


def test_a_removed_kid_is_left_out_of_the_book_summary(household, engine):
    from datetime import datetime, timezone
    from steward.db.models import Child, active_children
    with Session(engine) as db:
        db.scalars(active_children()).first().removed_at = datetime(2026, 10, 13, tzinfo=timezone.utc)
        db.commit()
    out = run(household, "book_summary", {})
    assert len([p for p in out["people"] if p["role"] == "child"]) == 2


def _checking(household, engine) -> tuple[str, int]:
    """The demo checking account's alias (from the accounts tool) and its id."""
    alias = next(a["account"] for a in run(household, "accounts", {"include_closed": False})["accounts"]
                 if a["account_type"] == "checking")
    with Session(engine) as db:
        return alias, int(db.scalar(select(AdvisorAlias.target).where(AdvisorAlias.kind == "account",
                                                                       AdvisorAlias.alias == alias)))


def test_balance_history_for_one_account_adds_its_month_end_balance(household, engine):
    alias, aid = _checking(household, engine)
    plain = run(household, "balance_history", {"months": 3, "by_account_type": True})
    one = run(household, "balance_history", {"months": 3, "by_account_type": True, "account": alias})
    assert all(m["account_cents"] is None for m in plain["months"])              # without account: today's plus null
    assert [{**m, "account_cents": None} for m in one["months"]] == plain["months"]
    with Session(engine) as db:
        for m, end in zip(one["months"], (date(2026, 8, 31), date(2026, 9, 30), TODAY)):
            assert m["account_cents"] == db.scalar(
                select(BalanceSnapshot.balance_cents).where(BalanceSnapshot.account_id == aid, BalanceSnapshot.as_of <= end)
                .order_by(BalanceSnapshot.as_of.desc()).limit(1))


def test_cash_flow_for_one_account_counts_only_its_rows_with_the_same_exclusions(household, engine):
    alias, aid = _checking(household, engine)
    one = run(household, "cash_flow", {"months": 3, "by": "category", "account": alias})
    with Session(engine) as db:
        rows = db.execute(select(Transaction.posted_at, Transaction.amount_cents).where(
            Transaction.account_id == aid, Transaction.posted_at >= date(2026, 8, 1),
            Transaction.posted_at < date(2026, 11, 1), Transaction.is_transfer.is_(False),
            Transaction.reimburser_id.is_(None), Transaction.category != "reimbursement")).all()
    for m in one["months"]:
        mine = [c for d, c in rows if d.strftime("%Y-%m") == m["month"]]
        assert (m["in_cents"], m["out_cents"]) == (sum(c for c in mine if c > 0), -sum(c for c in mine if c < 0))
        assert sum(g["out_cents"] for g in m["groups"]) == m["out_cents"]
    with Session(engine) as db:            # a transfer on that account changes nothing
        db.add(Transaction(account_id=aid, posted_at=date(2026, 9, 15), amount_cents=-99_999,
                           raw_description="TRANSFER TO SAVINGS", category="transfer", is_transfer=True,
                           category_source=CategorySource.none))
        db.commit()
    assert run(household, "cash_flow", {"months": 3, "by": "category", "account": alias}) == one
    biz = run(household, "cash_flow", {"months": 2, "by": "business", "account": alias})
    for m in biz["months"]:
        assert [g["business"] for g in m["groups"]] == [False, True]
        assert sum(g["out_cents"] for g in m["groups"]) == m["out_cents"]


def _sept(out) -> dict:
    m = next(m for m in out["months"] if m["month"] == "2026-09")
    return {"total": (m["in_cents"], m["out_cents"]),
            **{g["business"]: (g["in_cents"], g["out_cents"]) for g in m["groups"]}}


def test_cash_flow_by_business_splits_each_row_by_its_business_share(household, engine):
    """Argon follow-up 4: a split row is part personal, part business (business_pct, personal_amount), for one account
    and for the book. A 50% split of $100 out adds $50 to each side; an all-business $40 to business alone; an all-business
    $25 in to business money in."""
    alias, aid = _checking(household, engine)
    one = {"months": 2, "by": "business", "account": alias}
    book = {"months": 2, "by": "business"}
    before, book_before = _sept(run(household, "cash_flow", one)), _sept(run(household, "cash_flow", book))
    with Session(engine) as db:
        for cents, pct in ((-10_000, 50), (-4_000, 100), (2_500, 100)):
            db.add(Transaction(account_id=aid, posted_at=date(2026, 9, 15), amount_cents=cents, raw_description="CONSULT",
                               category="business_expense" if cents < 0 else "business_income", is_business=pct == 100,
                               business_pct=pct, category_source=CategorySource.none))
        db.commit()
    after, book_after = _sept(run(household, "cash_flow", one)), _sept(run(household, "cash_flow", book))

    def delta(a, b, key):
        return (a[key][0] - b[key][0], a[key][1] - b[key][1])
    assert delta(after, before, "total") == (2_500, 14_000)                 # the account's rows at their whole amounts
    assert delta(after, before, False) == (0, 5_000)
    assert delta(after, before, True) == (2_500, 9_000)
    assert delta(book_after, book_before, False) == (0, 5_000)            # Spending's personal share
    assert delta(book_after, book_before, True) == (2_500, 9_000)


def test_cash_flow_by_business_leaves_out_what_the_personal_side_leaves_out(household, engine):
    """The book's business side has the personal side's exclusions (personal_clauses): a reimbursable split row, a
    business repayment and a business row on an investment account count on neither side, for the book or the
    account."""
    from datetime import datetime, timezone
    from steward.db.models import Account, AccountType, Reimburser
    alias, aid = _checking(household, engine)
    one = {"months": 2, "by": "business", "account": alias}
    book = {"months": 2, "by": "business"}
    before = (_sept(run(household, "cash_flow", one)), _sept(run(household, "cash_flow", book)))
    with Session(engine) as db:
        acme = Reimburser(name="Acme", created_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.add(acme)
        db.flush()
        invest = db.scalar(select(Account.id).where(Account.type == AccountType.brokerage_taxable).limit(1))
        for account, cents, pct, category, payer in ((aid, -6_000, 50, "travel", acme.id),
                                                     (aid, 3_000, 100, "reimbursement", None),
                                                     (invest, -7_000, 100, "business_expense", None)):
            db.add(Transaction(account_id=account, posted_at=date(2026, 9, 16), amount_cents=cents, raw_description="X",
                               category=category, is_business=pct == 100, business_pct=pct, reimburser_id=payer,
                               category_source=CategorySource.none))
        db.commit()
    assert (_sept(run(household, "cash_flow", one)), _sept(run(household, "cash_flow", book))) == before


def test_an_account_alias_the_book_never_gave_is_bad_input(household):
    engine, book, people, jr = household
    for name, inp in (("balance_history", {"months": 3, "by_account_type": False, "account": "Account 999"}),
                      ("cash_flow", {"months": 3, "by": None, "account": "Account 999"}),
                      ("cash_flow", {"months": 3, "by": None, "account": "Payee 1"})):
        assert call(engine, book, people, jr, name, inp, TODAY)["error"] == "That input wasn't understood.", inp
