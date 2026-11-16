"""Spending with set-asides (spec, Spending (changes to 11b); decision 16): a matched payment leaves its category in
everyday, fixed and occasional, in the typical month and in Over time, but stays in money out; the head with and
without set-asides; months before the first set-aside."""
from datetime import date, datetime, timezone

from steward.db.models import SetAside
from steward.services import setasides as sas
from steward.services import spending as sp
from tests.factories import make_txn
from tests.setaside_fixtures import AT
from tests.spending_fixtures import TODAY, household

OCT, SEP, AUG = date(2026, 10, 1), date(2026, 9, 1), date(2026, 8, 1)


def proptax(db, first_month=date(2026, 11, 1)) -> SetAside:
    row = SetAside(name="Property tax", kind="twice_yearly", amount_cents=421_000, due_month=11, due_day=1, second_month=4,
                   second_day=10, first_month=first_month, payee_key="COUNTY TAX COLLECTOR", category="taxes",
                   created_at=AT, updated_at=AT)
    db.add(row); db.commit()
    sas.match_set_aside(db, row, TODAY)
    db.commit()
    return row


def test_a_matched_payment_leaves_its_category_but_stays_in_money_out(db):
    """Review Focus 4: the county's October payment is matched to Nov 1 (12 days early); Taxes no longer has a
    payment made once in a while, money out is unchanged, and the head's set-aside line names it."""
    household(db)
    before = sp.month_view(db, TODAY, OCT)
    assert before["occasional"] == [{"category": "taxes", "kind": "occasional", "spent_cents": 421_000, "paid_on": "2026-10-20"}]
    assert before["set_aside"] is None and before["head"]["set_aside_cents"] == 0 and before["head"]["paid_from_set_aside_cents"] == 0
    row = proptax(db)
    v = sp.month_view(db, TODAY, OCT)
    assert v["occasional"] == []
    assert (v["head"]["money_out_cents"], v["head"]["occasional_cents"], v["head"]["spent_cents"], v["head"]["planned_cents"]) == (
        935_799, 0, 514_799 + 70_167, 541_000 + 70_167)                                 # money out as before; October counts the share (choice 18)
    assert v["head"]["paid_from_set_aside_cents"] == 421_000 and v["head"]["set_aside_cents"] == 70_167
    s = v["set_aside"]
    assert (s["monthly_cents"], s["count"], s["needs_look"], s["names"]) == (70_167, 1, [], ["Property tax"])   # no account: nothing to look at
    assert s["paid"] == [{"set_aside_id": row.id, "name": "Property tax", "transaction_id": s["paid"][0]["transaction_id"],
                          "payee": "County tax collector", "posted_at": "2026-10-20", "cents": 421_000, "late": False,
                          "account_name": "Checking", "category": "taxes", "archived": False}]
    assert sp.flow_view(db, TODAY, 1)["months"][0]["out_cents"] == 935_799               # Home's strip reconciles with the bank


def test_a_matched_payment_leaves_the_typical_month_and_over_time(db):
    h = household(db)
    make_txn(db, h["checking"], date(2026, 8, 14), -186_000, "SAFEGUARD INSURANCE", merchant="Safeguard Insurance", category="insurance")
    assert sp.category_months(db, AUG, SEP)["2026-08"]["insurance"].out_cents == 186_000
    assert next(r for r in sp.trends_view(db, TODAY, 12)["categories"] if r["category"] == "insurance")["spent"][-3] == 186_000
    aug = sp.month_view(db, TODAY, AUG)
    assert next(r for r in aug["fixed"] if r["category"] == "insurance")["spent_cents"] == 186_000
    ins = SetAside(name="Car insurance", kind="yearly", amount_cents=186_000, due_month=8, due_day=14, first_month=date(2026, 1, 1),
                   payee_key="SAFEGUARD INSURANCE", category="insurance", created_at=AT, updated_at=AT)
    db.add(ins); db.commit()
    assert len(sas.match_set_aside(db, ins, TODAY)) == 1
    db.commit()
    assert "insurance" not in sp.category_months(db, AUG, SEP)["2026-08"]
    assert sp.category_months(db, AUG, SEP, with_matched=True)["2026-08"]["insurance"].out_cents == 186_000
    assert all(r["category"] != "insurance" for r in sp.trends_view(db, TODAY, 12)["categories"])
    assert sp.typicals(*sp.window_sums(db, TODAY))["insurance"] == 0
    aug = sp.month_view(db, TODAY, AUG)
    assert all(r["category"] != "insurance" for r in aug["fixed"])                       # nothing expected, nothing in it now
    assert aug["head"]["money_out_cents"] == 727_000 and aug["head"]["paid_from_set_aside_cents"] == 186_000
    # added in October, so August counts no share (first_month is only for should-be); the section stays for the payment
    assert (aug["set_aside"]["monthly_cents"], aug["set_aside"]["count"], len(aug["set_aside"]["paid"])) == (0, 0, 1)
    assert sp.flow_view(db, TODAY, 3)["months"][0]["out_cents"] == 727_000
    assert sp.earliest_month(db) == "2026-04"


def test_the_head_counts_the_monthly_amount_as_spent_and_planned(db):
    household(db)
    proptax(db, first_month=date(2026, 9, 1))
    v = sp.month_view(db, TODAY, OCT)
    assert (v["head"]["spent_cents"], v["head"]["planned_cents"], v["head"]["set_aside_cents"]) == (
        514_799 + 70_167, 541_000 + 70_167, 70_167)
    assert (v["head"]["everyday_spent_cents"], v["head"]["fixed_spent_cents"]) == (234_000, 280_799)   # the parts are as before
    s = v["set_aside"]
    assert (s["monthly_cents"], s["count"], s["yearly_cents"], s["one_off_cents"], s["names"]) == (70_167, 1, 842_000, 0, ["Property tax"])
    assert [r["name"] for r in s["needs_look"]] == []                                     # no account: nothing to look at
    assert s["next"] == {"name": "Property tax", "next_due": "2027-04-10"}                # Nov 1 is paid (Oct 20, early)


def test_months_before_the_first_set_aside_show_nothing_new(db):
    household(db)
    proptax(db)                                                                            # added in October, first month November
    sep = sp.month_view(db, TODAY, SEP)
    assert sep["set_aside"] is None
    assert (sep["head"]["spent_cents"], sep["head"]["planned_cents"], sep["head"]["set_aside_cents"]) == (544_000, 541_000, 0)


def test_a_backdated_first_month_does_not_backdate_spending(db):
    household(db)
    proptax(db, first_month=date(2026, 1, 1))                                              # added in October, should-be counts from January
    sep = sp.month_view(db, TODAY, SEP)
    assert sep["set_aside"] is None and sep["head"]["set_aside_cents"] == 0
    assert sp.month_view(db, TODAY, OCT)["head"]["set_aside_cents"] == 70_167


def test_money_out_is_homes_figure_even_when_a_refund_nets_a_matched_payments_category(db):
    h = household(db)
    proptax(db)
    make_txn(db, h["checking"], date(2026, 10, 22), 50_000, "COUNTY TAX REFUND", merchant="County Tax Collector", category="taxes")
    v = sp.month_view(db, TODAY, OCT)
    assert v["head"]["money_out_cents"] == sp.flow_view(db, TODAY, 1)["months"][0]["out_cents"] == 935_799 - 50_000
    assert v["head"]["income_cents"] == sp.flow_view(db, TODAY, 1)["months"][0]["in_cents"]
    assert v["head"]["paid_from_set_aside_cents"] == 421_000


def test_a_paid_one_off_counts_through_the_month_it_was_paid_and_not_after(db):
    h = household(db)
    make_txn(db, h["checking"], date(2026, 3, 12), -220_000, "ACME PLUMBING", merchant="Acme Plumbing", category="home")
    heater = SetAside(name="Water heater", kind="one_off", amount_cents=220_000, due_year=2026, due_month=4, first_month=date(2026, 1, 1),
                      payee_key="ACME PLUMBING", category="home", created_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
                      updated_at=AT)
    db.add(heater); db.commit()
    assert len(sas.match_set_aside(db, heater, TODAY)) == 1
    db.commit()
    mar, apr = sp.month_view(db, TODAY, date(2026, 3, 1)), sp.month_view(db, TODAY, date(2026, 4, 1))
    assert (mar["set_aside"]["count"], mar["set_aside"]["monthly_cents"], len(mar["set_aside"]["paid"])) == (1, 55_000, 1)
    assert apr["set_aside"] is None and apr["head"]["set_aside_cents"] == 0


def test_a_payment_matched_to_an_archived_set_aside_still_counts_as_paid_from_setting_aside(db):
    household(db)
    row = proptax(db)
    row.archived_at = AT
    db.commit()
    v = sp.month_view(db, TODAY, OCT)
    assert [(p["name"], p["archived"]) for p in v["set_aside"]["paid"]] == [("Property tax", True)]
    assert v["head"]["paid_from_set_aside_cents"] == 421_000 and v["occasional"] == []
    assert v["head"]["set_aside_cents"] == 0
    assert v["head"]["money_out_cents"] == 935_799
    assert (v["set_aside"]["count"], v["set_aside"]["monthly_cents"], v["set_aside"]["names"]) == (0, 0, [])   # archived this month: no share, the payment stays


def test_a_past_month_counts_the_amount_but_has_no_rows_to_look_at(db):
    from steward.db.models import BalanceSnapshot
    from tests.factories import make_account
    h = household(db)
    kids = make_account(db, "Kids fund", type="savings")
    db.add(BalanceSnapshot(account_id=kids.id, as_of=date(2026, 10, 24), balance_cents=10_000))
    camps = SetAside(name="Summer camps", kind="yearly", amount_cents=240_000, due_month=6, due_day=1, first_month=date(2026, 7, 1),
                     account_id=kids.id, created_at=datetime(2026, 7, 5, tzinfo=timezone.utc), updated_at=AT)
    db.add(camps); db.commit()
    now = sp.month_view(db, TODAY, OCT)["set_aside"]
    assert [(r["name"], r["state"]) for r in now["needs_look"]] == [("Summer camps", "behind")]   # $100 of $800
    past = sp.month_view(db, TODAY, SEP)["set_aside"]
    assert (past["monthly_cents"], past["count"], past["needs_look"], past["next"]) == (20_000, 1, [], None)
    camps.archived_at = AT
    db.commit()
    assert sp.month_view(db, TODAY, SEP)["set_aside"]["count"] == 1                         # archived in October: September still counted it (added in July)
    assert sp.month_view(db, TODAY, OCT)["set_aside"] is None                               # the month it was archived in does not count
    assert h["checking"].id
