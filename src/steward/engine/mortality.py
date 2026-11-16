"""Lifespans drawn from the Social Security period life table (spec section 3.2)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from steward.engine import datafiles
from steward.engine.inputs import Household

OUTLIVED_TABLE_AGE = 120


@dataclass(frozen=True)
class Deaths:
    """Age during which each person dies, shape (H,). Alive at age x while x < death age."""
    jr: np.ndarray
    spouse: np.ndarray


def death_ages(sex: str, current_age: int, n: int, rng: np.random.Generator) -> np.ndarray:
    q = datafiles.life_table()[sex][current_age:]
    died_by = 1.0 - np.cumprod(1.0 - q)            # probability of dying during or before each later age
    u = rng.random(n)
    return current_age + np.searchsorted(died_by, u, side="right")   # len(q) -> survived every age in the table


def draw_deaths(hh: Household, n: int, rng: np.random.Generator) -> Deaths:
    jr = death_ages(hh.jr.sex, hh.plan_year - hh.jr.birth_year, n, rng)
    spouse = death_ages(hh.spouse.sex, hh.plan_year - hh.spouse.birth_year, n, rng)
    return Deaths(jr=jr, spouse=spouse)
