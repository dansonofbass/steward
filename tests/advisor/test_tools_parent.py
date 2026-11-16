"""Parent tools on Margaret's book with her flags (spec 4.2): typed fields only, no names, numbers or notes."""
import json
from datetime import date

import pytest
from sqlalchemy.orm import Session

from steward.demo_parent import seed_parent
from steward.demo_watching import seed_watching
from tests.advisor.helpers import call

TODAY = date(2026, 10, 19)


@pytest.fixture
def parent(margaret, books, mctx):
    engine = books.engine_for(margaret)
    with Session(engine) as db:
        seed_parent(db, TODAY, by=mctx.user_id)
        seed_watching(db, TODAY, by=mctx.user_id)
    people = books.people(margaret.id)
    return engine, margaret, people, mctx.user_id


def run(p, name, input):
    engine, book, people, uid = p
    out = call(engine, book, people, uid, name, input, TODAY)
    assert out["error"] is None, out
    return out["content"]


def test_inventory_lists_items_with_types_and_aliases(parent):
    out = run(parent, "inventory", {"kind": None})
    kinds = [i["kind"] for i in out["items"]]
    assert kinds.count("account") == 9 and kinds.count("contact") == 2 and out["needs_checking"] == 2
    ss = next(i for i in out["items"] if i["type"] == "social_security")
    assert (ss["amount_cents"], ss["frequency"], ss["usual_day"], ss["owner"]) == (214_000, "monthly", 3, "Parent")
    assert ss["lands_in"].startswith("Account ")
    part_b = next(i for i in out["items"] if i["type"] == "medicare")
    assert part_b["paid_from"] is None and part_b["paid_from_income"] == "social_security"
    assert [t["group"] for t in out["totals"]] == ["cash", "investments", "retirement", "property", "debts"]
    only = run(parent, "inventory", {"kind": "insurance"})
    assert {i["kind"] for i in only["items"]} == {"insurance"}


def test_money_in_shows_each_month_and_misses(parent):
    out = run(parent, "money_in_monthly", {"months": 3})
    ss = next(i for i in out["items"] if i["source"] == "social_security")
    assert [m["month"] for m in ss["months"]] == ["2026-08", "2026-09", "2026-10"]
    assert all(m["arrived_cents"] == 214_000 for m in ss["months"]) and ss["missed"] == []


def test_premiums_with_last_payment_and_misses(parent):
    out = run(parent, "premiums", {})
    ltc = next(i for i in out["items"] if i["type"] == "long_term_care")
    assert ltc["premium_cents"] == 21_200 and ltc["paid_from"].startswith("Account ")
    assert isinstance(ltc["missed"], bool)
    home = next(i for i in out["items"] if i["type"] == "home")
    assert home["renewal_month"] and home["frequency"] == "yearly"


def test_flags_send_checks_and_aliases_only(parent):
    out = run(parent, "flags", {"include_done": True})
    assert out["flags"]
    assert {f["status"] for f in out["flags"]} <= {"open", "expected", "handled"}
    assert all(f["payee"] is None or f["payee"].startswith("Payee ") for f in out["flags"])
    assert len(run(parent, "flags", {"include_done": False})["flags"]) <= len(out["flags"])


def test_no_parent_tool_result_names_anything(parent):
    inputs = {"inventory": {"kind": None}, "money_in_monthly": {"months": 12}, "premiums": {}, "flags": {"include_done": True}}
    text = json.dumps([run(parent, n, i) for n, i in inputs.items()])
    for word in ("Margaret", "Robert", "Wells Fargo", "Fidelity", "Evergreen", "Clearpath", "EM-LTC", "0047730",
                 "Linda", "Daniel", "555-01", "example.com", "fire safe", "CVS", "Joint checking", "Medicare Part D"):
        assert word not in text, word


def test_household_tools_are_not_in_a_parent_book(parent):
    engine, book, people, uid = parent
    for name in ("facts", "plan_result", "plan_what_if", "plan_lever_impacts", "savings_checklist"):
        assert call(engine, book, people, uid, name, {}, TODAY)["error"] in ("Not in this book.",
                                                                             "That input wasn't understood.")
