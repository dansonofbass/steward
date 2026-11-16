"""State modules (spec 3.1, D4). A module exposes tax(facts, year, fed) -> StateResult, estimates_schedule(year), and
vector_tax(...) for the Monte Carlo plan. California is the only module that calculates tax in v1; the states with no
wage income tax have a module that returns zero. Any other state is not calculated, and says so."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from steward.engine.tax.facts import FederalFigures, Installment, StateResult, TaxFacts

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "the District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

# No tax on wages (Tax Foundation and each state's revenue department). New Hampshire's tax on interest and dividends
# ended with 2024; Washington taxes large long-term capital gains, which is named, not calculated.
NO_WAGE_TAX = ("AK", "FL", "NV", "NH", "SD", "TN", "TX", "WA", "WY")


class StateModule(Protocol):
    code: str

    def tax(self, facts: TaxFacts, year: int, fed: FederalFigures) -> StateResult: ...

    def estimates_schedule(self, year: int) -> tuple[Installment, ...]: ...

    def vector_tax(self, income: np.ndarray, fed_agi: np.ndarray, filing: str, n_aged: int, year: int) -> np.ndarray: ...


def state_name(code: str) -> str:
    return STATE_NAMES.get(code, code)


def not_calculated_line(code: str) -> str:
    return f"State tax isn't calculated for {state_name(code)} yet."


class NoWageTax:
    def __init__(self, code: str):
        self.code = code

    def tax(self, facts: TaxFacts, year: int, fed: FederalFigures) -> StateResult:
        lines = (f"{state_name(self.code)} has no income tax on wages.",)
        if self.code == "WA":
            lines += ("Washington's tax on large capital gains isn't calculated.",)
        return StateResult(state=self.code, calculated=True, explain=lines)

    def estimates_schedule(self, year: int) -> tuple[Installment, ...]:
        return ()

    def vector_tax(self, income, fed_agi, filing, n_aged, year):
        return np.zeros_like(income)


@dataclass(frozen=True)
class ScorpStateCosts:
    """What a state charges an S-corp that a sole proprietor doesn't pay: a tax on the corporation, and payroll
    taxes on the owner's salary. Cents."""
    state: str
    calculated: bool
    franchise_cents: int = 0     # the state's tax on the S-corp itself; deductible on the federal return
    sdi_cents: int = 0           # payroll taxes withheld from the owner's salary (California SDI)
    unemployment_cents: int = 0  # the employer's payroll taxes on the salary (California UI and ETT); a business expense
    rules_year: int | None = None
    explain: tuple[str, ...] = ()

    @property
    def total_cents(self) -> int:
        return self.franchise_cents + self.sdi_cents + self.unemployment_cents


def scorp_state_costs(state: str, salary_cents: int, net_income_cents: int, year: int) -> ScorpStateCosts:
    """The state's S-corp costs at this salary and the S-corp's net income (after the salary and its payroll tax).
    California calculates them; any other state says they aren't included."""
    mod = module_for(state)
    costs = getattr(mod, "scorp_costs", None)
    if costs is None:
        return ScorpStateCosts(state=state, calculated=False,
                               explain=(f"{state_name(state)}'s S-corp and payroll taxes aren't included.",))
    return costs(salary_cents, net_income_cents, year)


def _registry() -> dict[str, StateModule]:
    from steward.engine.tax.state import california
    mods: dict[str, StateModule] = {code: NoWageTax(code) for code in NO_WAGE_TAX}
    mods["CA"] = california.MODULE
    return mods


_MODULES: dict[str, StateModule] | None = None


def module_for(code: str) -> StateModule | None:
    global _MODULES
    if _MODULES is None:
        _MODULES = _registry()
    return _MODULES.get(code)


def state_tax(facts: TaxFacts, year: int, fed: FederalFigures) -> StateResult:
    mod = module_for(facts.state)
    if mod is None:
        return StateResult(state=facts.state, calculated=False, explain=(not_calculated_line(facts.state),))
    return mod.tax(facts, year, fed)
