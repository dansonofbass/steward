"""What a kid's college costs and how much of it their 529 is on track to cover (profile spec P16): the consequence line
under each kid in Profile. Pure. The 529 at the start of college is today's balance and the monthly contribution
until the kid is 18, grown at the 529 mix's geometric-mean real return over the market file; growth during college is
ignored, which is slightly conservative. web/src/screens/profile/outlook.ts does the same arithmetic, and both run
web/src/screens/profile/college_outlook.fixture.json."""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from steward.engine import datafiles
from steward.engine.datafiles import CollegeLevel
from steward.engine.inputs import Child, Mix
from steward.engine.market import real_returns
from steward.engine.simulate import COLLEGE_START_AGE

ENGINE_LEVEL = {"not_sure": "in_state_public"}   # P9


@dataclass(frozen=True)
class Outlook:
    years: int            # college years not yet past (all of them for a kid under 18)
    total_cents: int      # what the household plans to cover, in today's dollars
    covered_cents: int    # how much of that the 529 is on track to cover


def _half_up(x: float) -> int:
    return math.floor(x + 0.5)


def real_return(mix: Mix) -> float:
    """The mix's geometric-mean real return over the market file's years, after its fee."""
    rr = real_returns(datafiles.market())
    yearly = mix.stock * rr.stock + mix.bond * rr.bond + mix.cash * rr.cash - mix.fee_bp / 10_000
    return float(np.prod(1.0 + yearly) ** (1.0 / len(yearly)) - 1.0)


def outlook(child: Child, plan_year: int, real_return: float, *, levels: Mapping[str, CollegeLevel] | None = None,
            growth: float | None = None) -> Outlook:
    table = levels if levels is not None else datafiles.college_levels()
    g = datafiles.college_costs_growth() if growth is None else growth
    lv = table[ENGINE_LEVEL.get(child.cost_level, child.cost_level)]
    start = child.birth_year + COLLEGE_START_AGE
    years = [y for y in range(start, start + lv.years) if y >= plan_year]
    per_year = (lv.tuition_fees_cents + (lv.living_cents if child.covers_living else 0)) * (child.share_pct / 100)
    total = sum(per_year * (1.0 + g) ** (y - plan_year) for y in years)
    n = max(0, start - plan_year)
    grow = (1.0 + real_return) ** n
    monthly_part = child.monthly_contribution_cents * 12 * ((grow - 1.0) / real_return if real_return != 0 else n)
    saved = child.plan529.balance_cents * grow + monthly_part
    return Outlook(len(years), _half_up(total), _half_up(min(saved, total)))
