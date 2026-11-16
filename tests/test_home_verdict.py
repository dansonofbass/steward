"""The verdict's signals (Home spec, The headline): problems (at most 2, a late Bill before overdrawn), soft signals in
the table's order (at most 2), good clauses (spending, bills, plan), the openers, the caveat and the empty book. The
web words them (lib/headline.ts); these are the keys."""
from steward.services import home as hm


def flex(category: str, level: str | None) -> dict:
    return {"category": category, "over_level": level}


def bill(category: str, state: str, *, expected: bool = True, spent: int = 10_000, usual: int | None = 10_000,
         day: int | None = 12) -> dict:
    return {"category": category, "kind": "fixed", "state": state, "expected": expected, "spent_cents": spent,
            "usual_cents": usual, "typical_day": day}


BASE = dict(empty=False, day=20, net=50_000, payday_day=None, typical_income=500_000, flexible=[flex("dining", "on")],
            has_flex_target=True, bills=[bill("utilities", "as_usual")], overdrawn=[], plan={"age": 54, "still": True},
            stale=False, best_month=False)
ON_TRACK, PAID, PLAN_STILL = {"kind": "spending_on_track"}, {"kind": "bills_paid"}, {"kind": "plan", "age": 54, "still": True}


def v(**kw) -> dict:
    return hm.verdict(**{**BASE, **kw})


def test_a_steady_month_says_spending_bills_and_the_plan():
    assert v() == {"opener": "steady", "problems": [], "clauses": [ON_TRACK, PAID, PLAN_STILL], "stale": False,
                   "best_month": False}


def test_mostly_steady_with_a_little_behind_and_one_category_ahead():
    got = v(net=-40_000, payday_day=15, flexible=[flex("dining", "clear")])
    assert (got["opener"], got["clauses"]) == ("mostly", [{"kind": "behind_until_payday", "little": True},
                                                          {"kind": "over_one", "category": "dining"}])


def test_a_late_bill_is_a_problem_and_otherwise_the_good_clauses_follow():
    got = v(bills=[bill("utilities", "late", day=12)], plan={"age": 54, "still": False})
    assert got["opener"] == "problem"
    assert got["problems"] == [{"kind": "late_bill", "category": "utilities", "usual_day": 12}]
    assert got["clauses"] == [ON_TRACK, {"kind": "plan", "age": 54, "still": False}]          # bills aren't all paid


def test_overdrawn_alone():
    got = v(overdrawn=[("Checking", -12_000)], has_flex_target=False, bills=[], plan=None)
    assert (got["opener"], got["problems"], got["clauses"]) == (
        "problem", [{"kind": "overdrawn", "account": "Checking", "cents": -12_000}], [])


def test_problems_cap_at_two_late_bills_first_then_the_most_overdrawn():
    got = v(bills=[bill("utilities", "late"), bill("insurance", "late")],
            overdrawn=[("Checking", -5_000), ("Joint checking", -9_000)])
    assert got["problems"] == [{"kind": "late_bills", "n": 2},
                               {"kind": "overdrawn", "account": "Joint checking", "cents": -9_000}]


def test_soft_signals_keep_the_tables_order_and_cap_at_two():
    got = v(net=-1_000, day=8, flexible=[flex("dining", "clear"), flex("shopping", "clear")],
            bills=[bill("utilities", "over", spent=20_000)])
    assert got["clauses"] == [{"kind": "more_out_than_in"}, {"kind": "over_many", "n": 2}]


def test_bill_more_names_the_bill_furthest_over():
    got = v(bills=[bill("utilities", "over", spent=13_000), bill("insurance", "over", spent=19_000)])
    assert got["clauses"] == [{"kind": "bill_more", "category": "insurance"}]


def test_a_new_month_on_days_1_to_3_only():
    assert v(day=3)["opener"] == "new_month"
    assert v(day=4)["opener"] == "steady"
    assert v(day=2, net=-40_000, payday_day=15)["opener"] == "new_month"          # soft, still "A new month."
    assert v(day=2, bills=[bill("utilities", "late")])["opener"] == "problem"


def test_stale_adds_its_caveat_whatever_came_before():
    assert v(stale=True)["stale"] is True
    assert v(stale=True, overdrawn=[("Checking", -1)])["stale"] is True


def test_a_little_behind_is_at_most_half_the_usual_income():
    assert v(net=-250_000, payday_day=15)["clauses"][0] == {"kind": "behind_until_payday", "little": True}
    assert v(net=-250_001, payday_day=15)["clauses"][0] == {"kind": "behind_until_payday", "little": False}
    assert v(net=-1_000, payday_day=15, typical_income=None)["clauses"][0] == {"kind": "behind_until_payday",
                                                                                "little": False}


def test_more_out_than_in_from_day_8():
    assert v(net=-1_000, day=7)["opener"] == "steady"
    assert v(net=-1_000, day=8)["clauses"][0] == {"kind": "more_out_than_in"}


def test_spending_close_when_every_over_row_is_a_little():
    assert v(flexible=[flex("dining", "little"), flex("shopping", "on")])["clauses"][0] == {"kind": "spending_close"}
    assert ON_TRACK not in v(has_flex_target=False)["clauses"]


def test_bills_paid_needs_an_expected_bill_all_paid():
    assert PAID not in v(bills=[bill("insurance", "as_usual", expected=False)])["clauses"]
    assert PAID not in v(bills=[bill("utilities", "waiting")])["clauses"]
    assert PAID not in v(bills=[])["clauses"]


def test_not_by_70_has_no_plan_clause():
    assert v(plan={"age": None, "still": False})["clauses"] == [ON_TRACK, PAID]


def test_an_empty_book_says_only_that():
    assert v(empty=True, overdrawn=[("Checking", -1)], stale=True) == {
        "opener": "empty", "problems": [], "clauses": [], "stale": False, "best_month": False}


def test_the_bills_sign_counts_paid_of_expected_and_names_the_late_ones():
    bills = [bill("housing", "as_usual"), bill("utilities", "late", day=12), bill("insurance", "waiting"),
             bill("subscriptions", "over")]
    assert hm.bills_sign(bills) == {"paid": 2, "of": 4, "late": [{"category": "utilities", "usual_day": 12}]}
    assert hm.bills_sign([]) == {"paid": 0, "of": 0, "late": []}
