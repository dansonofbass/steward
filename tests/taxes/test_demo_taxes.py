"""The demo household shows every Taxes card filled in (fictional figures)."""
from datetime import date

from steward.demo import seed
from steward.taxes.plans import plans
from steward.taxes.quarterly import quarterly
from steward.taxes.roth import roth_view

TODAY = date(2026, 10, 13)


def test_the_demo_fills_every_card(db):
    seed(db)
    q = quarterly(db, TODAY)
    assert q.prior is not None and q.withholding is not None and q.needs_withholding is False
    assert q.federal.prior_share == 1.10                         # 2025 AGI $198,500 is over $150,000
    assert len([p for p in q.payments if p.agency == "federal"]) >= 3   # January, April and July 28
    assert plans(db, TODAY).points[0].room.solo_total_cents > 0
    assert roth_view(db, TODAY).later is not None
