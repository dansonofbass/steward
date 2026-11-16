"""TaxFacts validation (spec 3.3): plain words for anything annual_tax can't take."""
from dataclasses import replace

import pytest

from steward.engine.inputs import InputError
from steward.engine.tax.facts import TaxFacts, validate_facts

OK = TaxFacts(filing="mfj", ages=(44, 42), state="CA", wages_cents=10_000_000, business_profit_cents=-200_000,
              long_term_gains_cents=-50_000, dependents=(11,))


def test_good_facts_pass_and_losses_may_be_negative():
    validate_facts(OK)
    validate_facts(replace(OK, payroll_wages_cents=None))


@pytest.mark.parametrize("change, words", [
    (dict(filing="hoh"), "'mfj' or 'single'"),
    (dict(ages=(44,)), "two for a joint return"),
    (dict(ages=(44, 121)), "from 0 to 120"),
    (dict(state="ca"), "two-letter code"),
    (dict(dependents=(-1,)), "dependent's age"),
    (dict(wages_cents=-1), "wages can't be negative"),
    (dict(interest_cents=True), "whole number of cents"),
    (dict(qualified_dividends_cents=5, ordinary_dividends_cents=4), "can't be larger"),
])
def test_bad_facts_say_what_is_wrong(change, words):
    with pytest.raises(InputError, match=words):
        validate_facts(replace(OK, **change))
