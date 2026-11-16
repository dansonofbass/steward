"""GET /contributions: this year's limits per person, once on Accounts (investment views spec)."""
from tests.factories import make_ready_household


def test_get_contributions_lists_each_persons_limits(frozen, signed_in, db):
    make_ready_household(db)
    body = signed_in.get("/api/b/ours/contributions").json()
    assert body["year"] == 2026 and body["missing"] is False
    k = next(x for x in body["lines"] if x["kind"] == "k401")
    # No payroll figure: $160,000 x 10% x 9/12 = $12,000 (estimated); 1,200,000 x 365 / 273 on pace; 21% would max it.
    assert (k["owner"], k["label"], k["limit_cents"], k["in_cents"], k["on_pace_cents"], k["raise_pct"], k["estimated"]) == (
        "jr", "401(k)", 2_450_000, 1_200_000, 1_604_396, 21, True)
    ira = next(x for x in body["lines"] if x["kind"] == "ira")
    assert (ira["owner"], ira["label"], ira["in_cents"], ira["limit_cents"], ira["maxed"]) == ("jr", "IRA", 0, 750_000, False)


def test_a_parent_book_has_no_contribution_limits(frozen, client, margaret):
    from tests.factories import login
    login(client, "jr")
    assert client.get("/api/b/margaret-ellis/contributions").status_code == 404
