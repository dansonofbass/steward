from datetime import date

from steward.inventory.items import create_item
from steward.inventory.overview import overview
from steward.inventory.views import load
from tests.factories import login

TODAY = date(2026, 10, 13)
OWNERS = {"margaret": "Margaret", "robert-husband": "Robert (husband)", "joint": "Joint"}


def _make(mdb, mctx, **body):
    return create_item(mdb, mctx, {"owner": "margaret", "status": "confirmed", **body}, today=TODAY)


def _book(mdb, mctx):
    chk = _make(mdb, mctx, kind="account", name="Joint checking", owner="joint", institution="Wells Fargo",
                last4="4417", data_source="statement", details={"type": "checking"}, balance_cents=821455,
                balance_on="2026-10-13")
    _make(mdb, mctx, kind="account", name="Deferred annuity", institution="Westmark Life", last4="5521",
          status="needs_checking", details={"type": "annuity"})
    _make(mdb, mctx, kind="account", name="House", owner="joint", institution="Fullerton", details={"type": "property"},
          balance_cents=78_000_000, balance_on="2026-08-04")
    _make(mdb, mctx, kind="account", name="Citi card", institution="Citi", last4="9012", data_source="statement",
          details={"type": "credit_card"}, balance_cents=-118240, balance_on="2026-10-01")
    ss = _make(mdb, mctx, kind="income", name="Social Security", institution="Social Security Administration",
               details={"source": "social_security", "amount_cents": 214000, "frequency": "monthly", "usual_day": 3,
                        "lands_in_id": chk.id})
    _make(mdb, mctx, kind="insurance", name="Medicare Part B", details={"type": "medicare", "amount_cents": 18500,
                                                                       "frequency": "monthly", "paid_from_id": ss.id})
    _make(mdb, mctx, kind="insurance", name="Long-term care", institution="Evergreen Mutual", last4="7730",
          status="needs_checking", details={"type": "long_term_care", "amount_cents": 21200, "frequency": "monthly",
                                            "usual_day": 10, "paid_from_id": chk.id})
    _make(mdb, mctx, kind="insurance", name="Homeowners", owner="joint", institution="Pacific Shield", last4="4108",
          details={"type": "home", "amount_cents": 146000, "frequency": "yearly", "renewal_on": "2027-03-01",
                   "paid_from_id": chk.id})
    mdb.commit()


def test_the_overview_reads_like_the_mockup(margaret, mdb, mctx):
    _book(mdb, mctx)
    out = overview(mdb, load(mdb, OWNERS), TODAY)
    assert out["net_worth_cents"] == 821455 + 78_000_000 - 118240
    assert out["counted_line"] == "From 3 of Margaret's 4 accounts. The Westmark Life annuity has no balance yet."
    assert out["fresh_line"] == "Statements through Oct 13"
    assert out["needs_checking"] == {"count": 2, "labels": ["Westmark Life annuity", "Evergreen Mutual long-term care"]}
    assert [(t["key"], t["cents"], t["note"]) for t in out["totals"]] == [
        ("cash", 821455, "1 account"), ("investments", 0, "None listed"),
        ("retirement", 0, "1 account, 1 with no balance"), ("property", 78_000_000, "House, estimate"),
        ("debts", -118240, "1 credit card")]
    assert out["incoming"]["monthly_cents"] == 214000
    assert out["incoming"]["rows"][0]["sub"] == "Around the 3rd \u00b7 into Wells Fargo \u2022\u20224417 \u00b7 after Medicare Part B"
    assert out["incoming"]["foot"] is None
    assert out["outgoing"]["monthly_cents"] == 21200 + 12167
    assert [(r["name"], r["cents"], r["per"], r["sub"]) for r in out["outgoing"]["rows"]] == [
        ("Long-term care \u00b7 Evergreen Mutual", 21200, "monthly", "Around the 10th \u00b7 from Wells Fargo \u2022\u20224417"),
        ("Homeowners \u00b7 Pacific Shield", 146000, "yearly",
         "Renews Mar 1 \u00b7 from Wells Fargo \u2022\u20224417 \u00b7 $121.67 a month")]
    assert out["outgoing"]["foot"] == ("From insurance items. Medicare Part B ($185.00) comes out of Social Security "
                                       "before it arrives.")


def test_pending_income_is_named_but_not_counted(margaret, mdb, mctx):
    _book(mdb, mctx)
    out = overview(mdb, load(mdb, OWNERS), TODAY, pending_income=[("Westmark Life", 41000)])
    assert out["incoming"]["monthly_cents"] == 214000
    assert out["incoming"]["foot"] == "Not counted yet: Westmark Life deposits of $410.00 a month, waiting in Is this one of Margaret's?"


def test_an_empty_book_says_so(margaret, mdb):
    out = overview(mdb, load(mdb, OWNERS), TODAY)
    assert (out["net_worth_cents"], out["counted_line"], out["fresh_line"]) == (0, "No accounts listed yet.", None)
    assert all(t["note"] == "None listed" for t in out["totals"])


def test_the_route_adds_recent_changes(frozen, margaret, mdb, mctx, client):
    _book(mdb, mctx)
    login(client, "jr")
    out = client.get("/api/b/margaret-ellis/inventory/overview").json()
    assert len(out["recent"]) == 3 and out["recent"][0]["summary"] == "Jr added Homeowners"
    assert out["suggestions"] is None
