"""The state registry (spec 3.1, D4): California calculates; the no-wage-tax states return zero; every other state
is not calculated and says so in plain words, by name."""
import numpy as np

from steward.engine.tax.facts import FederalFigures, TaxFacts
from steward.engine.tax.state import NO_WAGE_TAX, STATE_NAMES, module_for, not_calculated_line, state_tax

FED = FederalFigures(agi=80_000, taxable_social_security=0, hsa_deduction=0)


def test_california_and_the_no_wage_tax_states_have_modules():
    assert module_for("CA").code == "CA"
    for code in NO_WAGE_TAX:
        r = state_tax(TaxFacts(filing="single", ages=(50,), state=code, wages_cents=8_000_000), 2026, FED)
        assert r.calculated and r.tax_cents == 0 and r.state == code
        assert module_for(code).estimates_schedule(2026) == ()
        assert np.array_equal(module_for(code).vector_tax(np.ones(3), np.ones(3), "mfj", 0, 2026), np.zeros(3))


def test_any_other_state_is_not_calculated_and_named():
    r = state_tax(TaxFacts(filing="single", ages=(50,), state="OR", wages_cents=8_000_000), 2026, FED)
    assert not r.calculated and r.tax_cents == 0 and r.explain == ("State tax isn't calculated for Oregon yet.",)
    assert module_for("OR") is None
    assert not_calculated_line("DC") == "State tax isn't calculated for the District of Columbia yet."
    assert not_calculated_line("ZZ") == "State tax isn't calculated for ZZ yet."
    assert len(STATE_NAMES) == 51
