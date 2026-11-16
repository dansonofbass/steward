"""A made-up household for tests and `steward bench`. Nothing here is real (spec section 9)."""
from __future__ import annotations

from dataclasses import replace

from steward.engine.inputs import Bucket, Child, EngineInputs, Household, Levers, Mix, Person


def synthetic_household(levers: Levers | None = None, **overrides) -> EngineInputs:
    jr = Person(
        birth_year=1982, sex="male",
        earnings=tuple((y, (30_000 + (y - 2004) * 5_714) * 100) for y in range(2004, 2026)),
    )
    spouse = Person(
        birth_year=1984, sex="female",
        earnings=tuple((y, (40_000 + (y - 2006) * 2_500) * 100) for y in range(2006, 2015)),
    )
    retirement_mix = Mix(0.7, 0.3, 0.0, fee_bp=8)
    taxable_mix = Mix(0.6, 0.4, 0.0, fee_bp=5)
    all_cash = Mix(0.0, 0.0, 1.0, fee_bp=0)
    children = (
        Child("Oldest", 2015, "in_state_public", Bucket(3_000_000, Mix(0.6, 0.4, 0.0, 10)), 30_000),
        Child("Middle", 2018, "in_state_public", Bucket(2_000_000, Mix(0.7, 0.3, 0.0, 10)), 30_000),
        Child("Youngest", 2021, "in_state_public", Bucket(1_000_000, Mix(0.8, 0.2, 0.0, 10)), 30_000),
    )
    hh = Household(
        plan_year=2026, jr=jr, spouse=spouse, filing_status="mfj", state="CA",
        salary_cents=16_000_000, k401_pct_bp=1_000, k401_roth_share_bp=0, match_rate_bp=5_000, match_cap_bp=600,
        spending_basis_cents=8_400_000, spending_months=12, surplus_cents=1_800_000,
        mortgage_payment_cents=3_600_000, mortgage_payoff_year=2048, health_premium_cents=2_400_000,
        cash=Bucket(4_000_000, all_cash), taxable=Bucket(15_000_000, taxable_mix),
        traditional=Bucket(45_000_000, retirement_mix), roth=Bucket(9_000_000, retirement_mix),
        hsa=Bucket(2_000_000, retirement_mix), children=children,
    )
    hh = replace(hh, **overrides)
    return EngineInputs(household=hh, levers=levers or Levers())
