from dataclasses import replace

import pytest

from steward.engine.inputs import (
    COST_LEVELS, Bucket, Child, EngineInputs, Household, InputError, Levers, Mix, Person, digest, validate,
)
from steward.engine.synthetic import synthetic_household


def test_mix_must_sum_to_one_and_be_non_negative():
    Mix(0.6, 0.4, 0.0)
    with pytest.raises(InputError):
        Mix(0.6, 0.6, 0.0)
    with pytest.raises(InputError):
        Mix(1.2, -0.2, 0.0)



@pytest.mark.parametrize("field", ["stock", "bond", "cash", "fee_bp"])
def test_mix_rejects_non_finite_values(field):
    for bad in (float("nan"), float("inf")):
        values = dict(stock=0.5, bond=0.5, cash=0.0, fee_bp=0)
        values[field] = bad
        with pytest.raises(InputError):
            Mix(**values)


def _smuggled(field="stock"):
    """A Mix whose share was set around the constructor, as a bundle assembled by hand could be."""
    m = Mix(0.6, 0.4, 0.0)
    object.__setattr__(m, field, float("nan"))
    return m


def test_validate_catches_a_non_finite_mix_built_around_the_constructor():
    inputs = synthetic_household()
    hh = inputs.household
    bad = replace(inputs, household=replace(hh, taxable=Bucket(hh.taxable.balance_cents, _smuggled())))
    with pytest.raises(InputError):
        validate(bad)
    kid = replace(hh.children[0], plan529=Bucket(100, _smuggled("bond")))
    bad_529 = replace(inputs, household=replace(hh, children=(kid,) + hh.children[1:]))
    with pytest.raises(InputError):
        validate(bad_529)


def test_synthetic_household_is_valid_and_frozen():
    inputs = synthetic_household()
    validate(inputs)
    assert inputs.household.state == "CA" and inputs.household.filing_status == "mfj"
    assert len(inputs.household.children) == 3
    assert inputs.household.jr.earnings[0][0] == 2004 and isinstance(inputs.household.spouse.earnings, tuple) and len(inputs.household.spouse.earnings) == 9
    with pytest.raises(Exception):
        inputs.household.salary_cents = 1  # frozen dataclass


def test_overrides_replace_household_fields():
    inputs = synthetic_household(salary_cents=12_000_000, children=())
    assert inputs.household.salary_cents == 12_000_000 and inputs.household.children == ()
    inputs = synthetic_household(levers=Levers(spending_pct=90))
    assert inputs.levers.spending_pct == 90


def test_digest_is_stable_and_sensitive():
    a = synthetic_household()
    b = synthetic_household()
    assert digest(a) == digest(b) and len(digest(a)) == 16
    c = synthetic_household(salary_cents=a.household.salary_cents + 100)
    assert digest(c) != digest(a)
    d = replace(a, levers=Levers(jr_claim_age=70))
    assert digest(d) != digest(a)


@pytest.mark.parametrize("field,value,words", [
    ("filing_status", "hoh", "filing status"),
    ("state", "California", "two-letter"),
    ("salary_cents", -1, "salary"),
    ("k401_pct_bp", 10_001, "basis points"),
    ("spending_months", 0, "months"),
    ("spending_basis_cents", -5, "spending"),
])
def test_validate_rejects_bad_household_fields(field, value, words):
    inputs = synthetic_household(**{field: value})
    with pytest.raises(InputError) as e:
        validate(inputs)
    assert words in str(e.value)


def test_validate_rejects_bad_people_and_children():
    base = synthetic_household()
    hh = base.household
    with pytest.raises(InputError, match="95"):
        validate(replace(base, household=replace(hh, jr=Person(1925, "male"), spouse=Person(1920, "female"))))
    with pytest.raises(InputError, match="born"):
        validate(replace(base, household=replace(hh, jr=Person(2030, "male"))))
    with pytest.raises(InputError, match="earnings"):
        validate(replace(base, household=replace(hh, jr=Person(1982, "male", ((2010, 100), (2010, 200))))))
    bad_child = Child("Oldest", 2015, "ivy", Bucket(0, Mix(0, 0, 1)), 0)  # type: ignore[arg-type]
    with pytest.raises(InputError, match="college"):
        validate(replace(base, household=replace(hh, children=(bad_child,))))
    with pytest.raises(InputError, match="college_levels"):
        validate(replace(base, levers=Levers(college_levels=("private",))))


@pytest.mark.parametrize("field", ["jr_claim_age", "spouse_claim_age", "spending_pct", "consulting_until_age",
                                   "spouse_stop_age"])
@pytest.mark.parametrize("bad", [True, 67.0, "67", None, -1])
def test_validate_rejects_a_bad_lever_age_or_percent(field, bad):
    with pytest.raises(InputError):
        validate(synthetic_household(levers=Levers(**{field: bad})))


def test_validate_rejects_bools_where_whole_numbers_are_expected():
    with pytest.raises(InputError):
        validate(synthetic_household(salary_cents=True))
    with pytest.raises(InputError):
        validate(synthetic_household(k401_pct_bp=True))
    with pytest.raises(InputError):
        validate(synthetic_household(levers=Levers(gift_cents=True)))
    with pytest.raises(InputError):
        validate(synthetic_household(spending_months=True))


def test_negative_surplus_and_no_mortgage_are_allowed():
    validate(synthetic_household(surplus_cents=-500_000, mortgage_payment_cents=0, mortgage_payoff_year=None))


def test_cost_levels_run_cheapest_to_dearest():
    assert COST_LEVELS == ("two_year", "in_state_public", "out_of_state_public", "private")


def test_a_kid_s_share_and_living_costs_are_checked():
    base = synthetic_household()
    kids = base.household.children

    def with_first(**changes):
        return replace(base, household=replace(base.household, children=(replace(kids[0], **changes),) + kids[1:]))

    for bad, match in (({"share_pct": 101}, "whole percent from 0 to 100"), ({"share_pct": -10}, "whole percent"),
                       ({"share_pct": 50.0}, "whole percent"), ({"covers_living": 1}, "living costs"),
                       ({"cost_level": "not_sure"}, "two_year, in_state_public, out_of_state_public, private")):
        with pytest.raises(InputError, match=match):
            validate(with_first(**bad))
    validate(with_first(cost_level="two_year", share_pct=35, covers_living=False))   # the engine takes any whole percent
    assert digest(with_first(share_pct=50)) != digest(base)


def test_one_off_costs_change_the_digest_and_are_checked():
    from steward.engine.inputs import OneOffCost
    a = synthetic_household()
    b = replace(a, household=replace(a.household, one_off_costs=(OneOffCost(2030, 100),)))
    assert digest(b) != digest(a) and a.household.one_off_costs == ()
    validate(b)
    for bad in ((OneOffCost(1999, 100),), (OneOffCost(2030, -1),), (OneOffCost(2030, 1.5),)):
        with pytest.raises(InputError, match="one-off"):
            validate(replace(a, household=replace(a.household, one_off_costs=bad)))
