"""Spec 3.1 and 9: the plan's vectorized tax stays within $50 of annual_tax on a grid of incomes, filing statuses,
ages and states, so the two paths never drift apart."""
import itertools

import numpy as np
import pytest

from steward.engine.tax import TaxFacts, annual_tax
from steward.engine.tax.vectorized import household_tax

ORDINARY = (0, 12_000, 38_000, 75_000, 140_000, 260_000, 520_000, 1_200_000)
GAINS = (0, 15_000, 90_000, 400_000)
SOCIAL_SECURITY = (0, 24_000, 52_000)
HOUSEHOLDS = (("mfj", (45, 43)), ("mfj", (70, 62)), ("mfj", (72, 70)), ("single", (40,)), ("single", (81,)))


@pytest.mark.parametrize("year", [2026, 2029])
@pytest.mark.parametrize("state", ["CA", "TX", "NY"])
@pytest.mark.parametrize("filing,ages", HOUSEHOLDS)
def test_vectorized_is_within_50_dollars_of_annual(year, state, filing, ages):
    n_aged = sum(1 for a in ages if a >= 65)
    worst = 0.0
    for o, g, b in itertools.product(ORDINARY, GAINS, SOCIAL_SECURITY):
        facts = TaxFacts(filing=filing, ages=ages, state=state, ira_distributions_cents=o * 100,
                         long_term_gains_cents=g * 100, social_security_cents=b * 100)
        exact = annual_tax(facts, year).total_tax_cents / 100
        fast = float(household_tax(float(o), float(g), float(b), filing, state, n_aged, year))
        worst = max(worst, abs(fast - exact))
        assert fast == pytest.approx(exact, abs=50), (o, g, b)
    assert worst < 50


def test_the_grid_reaches_every_rule_the_two_share():
    """Guard against a grid that stops exercising something: the top bracket, the 20% gains rate, the 85% Social
    Security tier, the 3.8% tax and California's 1% tax over $1,000,000 all show up somewhere on it."""
    r = annual_tax(TaxFacts(filing="mfj", ages=(70, 62), state="CA", ira_distributions_cents=120_000_000,
                            long_term_gains_cents=40_000_000, social_security_cents=5_200_000), 2026)
    assert r.federal.niit_cents > 0 and r.federal.capital_gains_cents > 0 and r.state.tax_cents > 0
    assert r.taxable_social_security_cents == round(0.85 * 5_200_000)
    assert any("1% tax on income over $1,000,000" in line for line in r.explain)
    assert np.isclose(r.agi_cents, (1_200_000 + 400_000 + 44_200) * 100)
