"""Year-by-year money in, money out and tax, in today's dollars (spec 3.4): project(inputs, assumptions, years).

Each year: income streams, long-term care insurance benefits once care has started and the waiting period is over,
required minimum distributions, and expense streams; the shortfall is withdrawn from cash, then the taxable account,
then traditional (RMDs forced), then Roth, grossed up so the withdrawals also pay the year's tax from annual_tax. Money
left over is saved to the taxable account. Balances grow at the assumed real return.

Amounts are in the first year's dollars. A stream that keeps pace with prices stays the same; one fixed in dollars
(the mortgage) shrinks by inflation each year (D10); care costs grow at their own rate (4% a year by default, about
1.5% above 2.5% inflation). Tax rules stay at the latest published table, in today's dollars, as in the plan.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from steward.engine.inputs import InputError
from steward.engine.tax import annual_tax, rules
from steward.engine.tax.facts import Filing, TaxFacts, TaxResult

IncomeKind = Literal["wages", "business", "pension", "social_security", "interest", "nontaxable"]
ExpenseKind = Literal["spending", "care", "insurance", "mortgage", "property_tax", "other"]
Growth = Literal["prices", "fixed_dollars", "care"]
GROSS_UP_ROUNDS = 8           # fixed-point rounds for the withdrawal that also pays its own tax
GROSS_UP_TOLERANCE = 1.0      # dollars


@dataclass(frozen=True)
class Assumptions:
    inflation: float = 0.025          # a year; fixed-dollar amounts shrink by it
    real_return: float = 0.02         # a year, above inflation, on every balance
    care_inflation: float = 0.04      # a year, nominal (spec 3.4: about 1.5% above 2.5% inflation)
    taxable_gain_share: float = 0.5   # of each taxable-account withdrawal, as in the plan


@dataclass(frozen=True)
class Stream:
    label: str
    amount_cents: int                 # yearly, in the first year's dollars
    start_year: int
    end_year: int | None = None       # the last year it applies; None: every year
    growth: Growth = "prices"


@dataclass(frozen=True)
class Income(Stream):
    kind: IncomeKind = "pension"
    owner: int = 0                    # whose it is: an index into birth_years (wages and business income are per person)


@dataclass(frozen=True)
class Expense(Stream):
    kind: ExpenseKind = "spending"
    medical: bool = False             # counts toward the medical deduction (care costs do)


@dataclass(frozen=True)
class LtcPolicy:
    """Long-term care insurance (D8). Pays toward care costs once care starts and the waiting period has passed,
    until the pool is used up. Benefits are tax-free (a tax-qualified policy within the per diem limit)."""
    care_start_year: int
    benefit_daily_cents: int | None = None
    benefit_monthly_cents: int | None = None
    waiting_days: int = 90
    total_benefit_cents: int | None = None   # the pool; or benefit_years x the yearly benefit
    benefit_years: float | None = None
    benefit_growth: float = 0.0               # nominal yearly growth of the benefit and pool (an inflation rider)
    premium_yearly_cents: int = 0             # already in spending; waived once the policy pays (waiver of premium)

    def yearly_cents(self) -> float:
        if self.benefit_daily_cents is not None:
            return self.benefit_daily_cents * 365.0
        if self.benefit_monthly_cents is not None:
            return self.benefit_monthly_cents * 12.0
        raise InputError("A long-term care policy needs a daily or a monthly benefit.")

    def pool_cents(self) -> float:
        if self.total_benefit_cents is not None:
            return float(self.total_benefit_cents)
        if self.benefit_years is not None:
            return self.yearly_cents() * self.benefit_years
        raise InputError("A long-term care policy needs a total benefit or a number of benefit years.")


@dataclass(frozen=True)
class HomeSale:
    year: int
    price_cents: int
    basis_cents: int                  # what was paid plus improvements
    selling_cost_rate: float = 0.06


@dataclass(frozen=True)
class ProjectionInputs:
    start_year: int
    filing: Filing
    state: str
    birth_years: tuple[int, ...]      # one per filer; the first owns the traditional account (RMDs)
    cash_cents: int = 0
    taxable_cents: int = 0
    traditional_cents: int = 0
    roth_cents: int = 0
    incomes: tuple[Income, ...] = ()
    expenses: tuple[Expense, ...] = ()
    ltc_policies: tuple[LtcPolicy, ...] = ()
    home_sale: HomeSale | None = None
    dependents: tuple[int, ...] = ()  # birth years


@dataclass(frozen=True)
class YearRow:
    year: int
    ages: tuple[int, ...]
    income_cents: int                 # money in from streams (Social Security, pensions, wages...), before tax
    ltc_benefit_cents: int
    home_sale_cents: int              # net proceeds
    rmd_cents: int
    withdrawals_cents: int            # beyond the RMD, from cash, taxable, traditional and Roth together
    expenses_cents: int
    care_cents: int
    tax_cents: int
    saved_cents: int                  # left over and added to the taxable account
    shortfall_cents: int              # what could not be paid; > 0 means the money ran out this year
    cash_cents: int                   # balances at the end of the year, after growth
    taxable_cents: int
    traditional_cents: int
    roth_cents: int
    ltc_pool_cents: int               # left in every policy's pool together
    tax: TaxResult

    @property
    def balance_cents(self) -> int:
        return self.cash_cents + self.taxable_cents + self.traditional_cents + self.roth_cents


def _real(stream: Stream, t: int, a: Assumptions) -> float:
    """The stream's amount t years after the projection starts, in today's dollars (float cents)."""
    if stream.growth == "fixed_dollars":
        return stream.amount_cents / (1.0 + a.inflation) ** t
    if stream.growth == "care":
        return stream.amount_cents * ((1.0 + a.care_inflation) / (1.0 + a.inflation)) ** t
    return float(stream.amount_cents)


def _active(stream: Stream, year: int) -> bool:
    return stream.start_year <= year and (stream.end_year is None or year <= stream.end_year)


def money_lasts_until(rows: list[YearRow]) -> int | None:
    """The last year everything is paid, or None when the money never runs out in the rows."""
    for i, r in enumerate(rows):
        if r.shortfall_cents > 0:
            return rows[i - 1].year if i else r.year - 1
    return None


def ltc_runs_out(rows: list[YearRow]) -> int | None:
    """The year the policies' pools are used up, or None."""
    for r in rows:
        if r.ltc_benefit_cents > 0 and r.ltc_pool_cents <= 0:
            return r.year
    return None


def _validate(p: ProjectionInputs, years: int) -> None:
    if not 1 <= years <= 80:
        raise InputError("A projection runs from 1 to 80 years.")
    if len(p.birth_years) != (2 if p.filing == "mfj" else 1):
        raise InputError("Give one birth year for a single return and two for a joint return.")
    for name in ("cash_cents", "taxable_cents", "traditional_cents", "roth_cents"):
        if getattr(p, name) < 0:
            raise InputError(f"The {name.removesuffix('_cents')} balance can't be negative.")
    for s in (*p.incomes, *p.expenses):
        if s.amount_cents < 0:
            raise InputError(f"{s.label} can't be negative.")
        if s.end_year is not None and s.end_year < s.start_year:
            raise InputError(f"{s.label} ends before it starts.")
    for inc in p.incomes:
        if not 0 <= inc.owner < len(p.birth_years):
            raise InputError(f"{inc.label} belongs to someone who isn't on the return.")
    if len({inc.owner for inc in p.incomes if inc.kind == "business"}) > 1:
        raise InputError("Business income can belong to only one person on the return for now.")


def project(p: ProjectionInputs, a: Assumptions, years: int, *, marginal_from: int | None = None) -> list[YearRow]:
    """marginal_from: from this year on, each row's tax also carries its marginal rate (one more annual_tax call a
    year; Roth or traditional's rate later, tax decisions ruling 16). Every other number is the same either way."""
    _validate(p, years)
    cash, taxable, trad, roth = (float(x) for x in (p.cash_cents, p.taxable_cents, p.traditional_cents, p.roth_cents))
    pools = [pol.pool_cents() for pol in p.ltc_policies]
    waits = [float(pol.waiting_days) for pol in p.ltc_policies]
    claiming = [False] * len(p.ltc_policies)
    owner = p.birth_years[0]
    rows: list[YearRow] = []
    last_tax = 0.0
    last_state_tax = 0           # the state income tax paid in a year is taken as last year's, for the SALT deduction
    business_owner = next((inc.owner for inc in p.incomes if inc.kind == "business"), 0)
    for t in range(years):
        year = p.start_year + t
        ages = tuple(year - b for b in p.birth_years)
        by_kind: dict[str, float] = {}
        wages_by_person = [0.0] * len(p.birth_years)
        for inc in p.incomes:
            if _active(inc, year):
                by_kind[inc.kind] = by_kind.get(inc.kind, 0.0) + _real(inc, t, a)
                if inc.kind == "wages":
                    wages_by_person[inc.owner] += _real(inc, t, a)
        income = sum(by_kind.values())
        expenses = care = medical = property_tax = 0.0
        for ex in p.expenses:
            if _active(ex, year):
                amount = _real(ex, t, a)
                expenses += amount
                care += amount if ex.kind == "care" else 0.0
                medical += amount if ex.medical else 0.0
                property_tax += amount if ex.kind == "property_tax" else 0.0
        # Long-term care insurance, in today's dollars: the benefit and pool grow by the rider and shrink by inflation.
        # The premium is waived from the day the policy first pays; once the pool is used up the policy has ended.
        ltc = waived = 0.0
        for i, pol in enumerate(p.ltc_policies):
            factor = ((1.0 + pol.benefit_growth) / (1.0 + a.inflation)) ** t
            if t > 0:
                pools[i] *= (1.0 + pol.benefit_growth) / (1.0 + a.inflation)
            if claiming[i]:
                waived += pol.premium_yearly_cents
            if year < pol.care_start_year or pools[i] <= 0 or care - ltc <= 0:
                continue
            days = 365.0
            if waits[i] > 0:
                used = min(waits[i], days)
                waits[i] -= used
                days -= used
            pay = min(pol.yearly_cents() * factor * days / 365.0, pools[i], care - ltc)
            pools[i] -= pay
            ltc += pay
            if pay > 0 and not claiming[i]:
                claiming[i] = True
                waived += pol.premium_yearly_cents * days / 365.0
        expenses = max(expenses - waived, 0.0)
        sale_net, sale_gain = 0.0, 0.0
        if p.home_sale is not None and p.home_sale.year == year:
            hs = p.home_sale
            sale_net = hs.price_cents * (1.0 - hs.selling_cost_rate)
            exclusion = rules.table("federal", year)["home_sale_exclusion"][p.filing] * 100
            sale_gain = max(sale_net - hs.basis_cents - exclusion, 0.0)
        start_age = rules.rmd_start_age(owner, year)
        rmd = trad / rules.rmd_divisor(year - owner, year) if year - owner >= start_age and trad > 0 else 0.0

        def facts(from_trad: float, from_taxable: float) -> TaxFacts:
            return TaxFacts(
                filing=p.filing, ages=tuple(min(x, 120) for x in ages), state=p.state, wages_cents=round(by_kind.get("wages", 0.0)),
                ss_wages_by_person_cents=tuple(round(x) for x in wages_by_person), business_owner=business_owner,
                business_profit_cents=round(by_kind.get("business", 0.0)), pensions_cents=round(by_kind.get("pension", 0.0)),
                social_security_cents=round(by_kind.get("social_security", 0.0)), interest_cents=round(by_kind.get("interest", 0.0)),
                ira_distributions_cents=round(rmd + from_trad),
                long_term_gains_cents=round(sale_gain + a.taxable_gain_share * from_taxable),
                medical_cents=round(max(medical - ltc, 0.0)), property_tax_cents=round(property_tax),
                state_income_tax_cents=max(last_state_tax, 0),
                dependents=tuple(year - b for b in p.dependents if 0 <= year - b <= 120),
            )

        cash_in = income + ltc + sale_net + rmd
        withdraw = max(expenses + last_tax - cash_in, 0.0)
        for _ in range(GROSS_UP_ROUNDS):
            w_cash, w_tax, w_trad, w_roth, short = _split(withdraw, cash, taxable, trad - rmd, roth)
            result = annual_tax(facts(w_trad, w_tax), year, marginal=False)
            tax = result.total_tax_cents
            nxt = max(expenses + tax - cash_in, 0.0)
            if abs(nxt - withdraw) < GROSS_UP_TOLERANCE * 100:
                withdraw = nxt
                break
            withdraw = nxt
        # The converged withdrawal is reported with the tax from the round it converged from, so withdrawals - tax == need.
        w_cash, w_tax, w_trad, w_roth, short = _split(withdraw, cash, taxable, trad - rmd, roth)
        if marginal_from is not None and year >= marginal_from:
            result = replace(result, marginal_rate=annual_tax(facts(w_trad, w_tax), year).marginal_rate)
        saved = max(cash_in - expenses - tax, 0.0)
        cash -= w_cash
        taxable -= w_tax
        trad -= rmd + w_trad
        roth -= w_roth
        taxable += saved
        grow = 1.0 + a.real_return
        cash, taxable, trad, roth = cash * grow, taxable * grow, max(trad, 0.0) * grow, roth * grow
        last_tax = float(tax)
        last_state_tax = result.state.tax_cents
        rows.append(YearRow(
            year=year, ages=ages, income_cents=round(income), ltc_benefit_cents=round(ltc), home_sale_cents=round(sale_net),
            rmd_cents=round(rmd), withdrawals_cents=round(w_cash + w_tax + w_trad + w_roth), expenses_cents=round(expenses),
            care_cents=round(care), tax_cents=round(tax), saved_cents=round(saved), shortfall_cents=round(short),
            cash_cents=round(cash), taxable_cents=round(taxable), traditional_cents=round(trad), roth_cents=round(roth),
            ltc_pool_cents=round(sum(max(x, 0.0) for x in pools)), tax=result,
        ))
    return rows


def _split(amount: float, cash: float, taxable: float, trad: float, roth: float) -> tuple[float, float, float, float, float]:
    """Take `amount` from cash, then taxable, then traditional, then Roth. Returns each take and what was left unmet."""
    out = []
    rest = amount
    for bal in (cash, taxable, trad, roth):
        take = min(max(bal, 0.0), rest)
        out.append(take)
        rest -= take
    return out[0], out[1], out[2], out[3], rest
