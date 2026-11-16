"""A made-up household for Taxes tests (fictional; nothing here is real)."""
from datetime import date, datetime, timezone

from steward.business.settings import update_settings
from steward.db.models import Child
from tests.factories import add_fact, make_account, make_txn

AT = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)


def household(db, *, profit_cents=0, low=None, high=None, salary="0", k401="0", roth="0", kids=(), filing="mfj",
              business="sole_prop", state="CA"):
    for k, v in (("jr.dob", "1982-05-01"), ("spouse.dob", "1984-08-01"), ("state", state), ("filing_status", filing),
                 ("jr.salary_cents", salary), ("jr.k401_pct_bp", k401), ("jr.k401_roth_share_bp", roth)):
        add_fact(db, k, v)
    for i, born in enumerate(kids):
        db.add(Child(label=f"Kid {i + 1}", birth_year=born, cost_level="in_state_public", monthly_contribution_cents=0))
    if profit_cents:
        make_txn(db, make_account(db, "Business checking", type="business_checking", owner="business"),
                 date(2026, 3, 3), profit_cents, "ACH CLIENT INV 1", category="business_income", is_business=True)
    body = {"type": business, "car_method": "actual"}
    if low is not None:
        body["expect"] = {"low_cents": low, "high_cents": high}
    update_settings(db, body, year=2026, this_year=2026, periods=2, user_id=1, at=AT)
    db.commit()
