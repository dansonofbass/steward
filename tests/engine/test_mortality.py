import numpy as np

from steward.engine import mortality
from steward.engine.synthetic import synthetic_household


def test_death_ages_are_in_range_and_deterministic():
    a = mortality.death_ages("male", 44, 2000, np.random.default_rng(3))
    b = mortality.death_ages("male", 44, 2000, np.random.default_rng(3))
    assert np.array_equal(a, b) and a.shape == (2000,) and a.min() >= 44 and a.max() <= 120


def test_mean_death_age_is_close_to_ssa_life_expectancy():
    men = mortality.death_ages("male", 44, 20000, np.random.default_rng(5))
    women = mortality.death_ages("female", 42, 20000, np.random.default_rng(6))
    assert 76 < men.mean() < 82        # SSA 2023 table: a 44-year-old man expects about 35 more years
    assert 79 < women.mean() < 85      # a 42-year-old woman about 41
    assert women.mean() > men.mean()


def test_draw_deaths_uses_each_persons_sex_and_age():
    hh = synthetic_household().household
    d = mortality.draw_deaths(hh, 500, np.random.default_rng(1))
    assert d.jr.shape == d.spouse.shape == (500,) and d.jr.min() >= 44 and d.spouse.min() >= 42
