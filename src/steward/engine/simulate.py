"""One year at a time, every history and every candidate retirement age at once (spec section 3.4).

Arrays are shaped (rows, H): one row per simulated column, a candidate retirement age for Person 1 (and, for the lever
impacts, a trial lever set), by H simulated histories. Rows are ordered by age so that the columns that have retired
(a prefix of the ascending ages) are one contiguous block. Money inside the engine is float32 dollars in today's
purchasing power (float64 outside the simulation loop); the boundary is integer cents.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from steward.engine import datafiles, social_security as ss
from steward.engine.checklist import K401_LIMIT_CENTS
from steward.engine.inputs import EngineInputs, Household, Levers
from steward.engine.market import N_HISTORIES, SEED, Histories, mix_return, sample_histories
from steward.engine.mortality import Deaths, draw_deaths
from steward.engine.tax import rules
from steward.engine.tax.vectorized import LeverIncome, household_tax, lever_income, lever_income_after_tax

HORIZON_AGE = 95
COLLEGE_START_AGE = 18
MEDICARE_AGE = 65
TAX_GROSS_UP_PASSES = 1   # one pass, seeded with last year's tax (ruling 5, rung 4); the tax a year of withdrawals causes barely moves year to year
DTYPE = np.float32   # the (A, H) money arrays: half the memory traffic (ruling 5, rung 2); good to about a dollar at $10M
SHORTFALL_TOLERANCE = 0.5   # dollars; below this a year counts as met
RETIRE_BLOCK_CELLS = 16_000   # rows x histories per block of retirement work: its float64 temporaries stay in a core's cache


@dataclass(frozen=True)
class Prepared:
    hist: Histories
    deaths: Deaths
    n_years: int


def horizon_years(hh: Household) -> int:
    younger = min(hh.plan_year - hh.jr.birth_year, hh.plan_year - hh.spouse.birth_year)
    return HORIZON_AGE - younger


def prepare(hh: Household, n_hist: int = N_HISTORIES, seed: int = SEED) -> Prepared:
    """The random draws every solve on this household shares: markets first, then lifespans."""
    rng = np.random.default_rng(seed)
    n_years = horizon_years(hh)
    hist = sample_histories(datafiles.market(), n_hist, n_years, rng)
    deaths = draw_deaths(hh, n_hist, rng)
    return Prepared(hist=hist, deaths=deaths, n_years=n_years)


def rmd_start_age(birth_year: int, year: int = 2026) -> int:
    return rules.rmd_start_age(birth_year, year)


def rmd_divisor(age: int, year: int = 2026) -> float:
    return rules.rmd_divisor(age, year)


def fixed_dollars_by_year(amount: float, cpi: np.ndarray | None, n_years: int) -> np.ndarray | None:
    """A payment fixed in dollars, in today's dollars for each simulated year and history: (Y, H) float32, or None
    when the histories carry no inflation. Year 0 is the full amount; year t divides by the prices after t years."""
    if not amount or cpi is None:
        return None
    prices = np.cumprod(1.0 + cpi[:, :n_years], axis=1)
    start = np.concatenate([np.ones((cpi.shape[0], 1)), prices[:, :-1]], axis=1)
    return np.ascontiguousarray((amount / start).T, dtype=DTYPE)


def college_cost(level: str, year: int, plan_year: int, share_pct: int = 100, covers_living: bool = True) -> float:
    """One college year in today's dollars at the share the household plans to cover. The share is one factor, so
    100% multiplies by 1.0 exactly and every existing plan keeps its bits (Engineering choice 12)."""
    lv = datafiles.college_levels()[level]
    per_year = lv.tuition_fees_cents + (lv.living_cents if covers_living else 0)
    growth = 1.0 + datafiles.college_costs_growth()
    return per_year / 100 * (share_pct / 100) * growth ** (year - plan_year)


def college_years(level: str) -> int:
    return datafiles.college_levels()[level].years


def _draw(buckets: list[np.ndarray], amount: np.ndarray) -> np.ndarray:
    """Take `amount` (A, H) from each bucket in order, in place. Returns what could not be met."""
    rem = amount
    for b in buckets:
        take = np.minimum(b, rem)
        b -= take
        rem = rem - take
    return rem


def _retire_year(part, passes, hh, year, basis_all, n_aged, gross_all, ben_all, lever_ord_all, rmd_on, jr_age, cash, taxable, trad, hsa,
                 roth, tax_carry, failed):
    """One year of retirement withdrawals for the columns in `part`, grossed up for tax in `passes` passes.

    gross is the year's need less Social Security and lever cash; it is negative when income more than covers the
    need. Lever income's ordinary part is on the same return as the withdrawals and Social Security (D11)."""
    c, tx, td, hs, ro = cash[part], taxable[part], trad[part], hsa[part], roth[part]
    gross, ben = gross_all[part], ben_all[part]
    basis = basis_all if isinstance(basis_all, float) else basis_all[part]   # one value for every row, or one per row
    lever_ord = lever_ord_all if isinstance(lever_ord_all, float) else lever_ord_all[part]
    rmd = td / rmd_divisor(jr_age, year) if rmd_on else np.zeros_like(gross)
    tax = tax_carry[part]
    for _ in range(passes):
        target = gross + tax
        need = target - rmd                          # the RMD is cash in hand and counts toward the need
        np.maximum(need, 0.0, out=need)
        w_cash = c - basis
        np.maximum(w_cash, 0.0, out=w_cash)
        np.minimum(w_cash, need, out=w_cash)
        need -= w_cash                               # `need` now holds what is still unmet
        w_tax = np.minimum(tx, need)
        need -= w_tax
        w_trad = td - rmd
        np.maximum(w_trad, 0.0, out=w_trad)
        np.minimum(w_trad, need, out=w_trad)
        need -= w_trad
        w_hsa = np.minimum(hs, need)
        need -= w_hsa
        w_roth = np.minimum(ro, need)
        need -= w_roth
        w_buf = c - w_cash                           # the buffer itself, only when nothing else is left
        np.minimum(w_buf, need, out=w_buf)
        need -= w_buf
        tax = household_tax(rmd + w_trad + lever_ord, 0.5 * w_tax, ben, hh.filing_status, hh.state, n_aged, year)
    rem = need
    tax_carry[part] = tax
    c -= w_cash + w_buf
    tx -= w_tax
    td -= rmd + w_trad
    hs -= w_hsa
    ro -= w_roth
    tx += np.maximum(rmd - target, 0.0)   # an RMD or income beyond the need, after tax, is saved
    for b in (td, hs, ro):
        np.maximum(b, 0.0, out=b)          # rounding noise from subtracting a bucket's own balance
    failed[part] |= rem > SHORTFALL_TOLERANCE


@dataclass
class SimOutput:
    investable: np.ndarray | None   # (n_years + 1, H, A) dollars; index 0 is today. None when not asked for
    success: np.ndarray      # (A, H) bool, viewed as (H, A): investable money never ran out


def _ss_key(lv: Levers) -> tuple:
    """The lever fields Social Security depends on: trials that agree on them share one benefit computation."""
    return (lv.jr_claim_age, lv.spouse_claim_age, lv.spouse_earnings_cents, lv.spouse_start_year, lv.spouse_stop_age,
            lv.full_ss_benefits)


def _lever_income_key(lv: Levers) -> tuple:
    return (lv.consulting_cents, lv.consulting_until_age, lv.gift_cents, lv.gift_until_year, lv.spouse_earnings_cents,
            lv.spouse_start_year, lv.spouse_stop_age)


def _per_column(values: Sequence[float], row_k: np.ndarray) -> np.ndarray | float:
    """One float64 value per trial, as a (C, 1) float32 column over the rows' trials, or the plain float when every
    trial has the same value. A float meeting a float32 array is rounded to float32 first, so both forms give the
    same bits; the plain float just skips the broadcast."""
    if all(v == values[0] for v in values):
        return float(values[0])
    return np.asarray(values, dtype=np.float64)[row_k].astype(DTYPE)[:, None]


_SHARED_AGE = 1_000_000   # a trial's shared working column sorts after every real age, so it sits in the working suffix


def _run(inputs: EngineInputs, trials: Sequence[Levers], ages_a: Sequence[int], columns: Sequence[tuple[int, int]],
         prep: Prepared, *, track_investable: bool, stop_below: float | None, keep_before_crossing: bool = True):
    """The year loop for several trial lever sets and candidate ages at once.

    `columns` lists the (age index, trial index) pairs to simulate; ages_a is ascending. Each row of the state arrays
    is one column, ordered by age and then trial, so the retired rows are still a contiguous prefix. Per-trial terms
    (savings, spending, lever income, college levels, Social Security) are per-row arrays, rounded to float32 exactly
    as numpy rounds a Python float met by a float32 array, so a row's results are the same bits whichever rows run
    beside it.

    Columns of one trial that are still working are identical until one of them retires or someone claims Social
    Security (until then every working column's benefit is exactly zero and nothing else depends on the age), so
    each trial runs one shared working row and a column gets its own row, a copy of the shared one, in the year it
    retires, or for every remaining column in the first year either spouse could have claimed.

    stop_below: drop a column once its success rate can no longer reach the threshold (failures only accumulate). With
    keep_before_crossing, only when the next older age of the same trial is doomed too, so the age just before a
    trial's first crossing keeps its exact rate.

    Returns (rates, failed, investable): rates is (K, A) float64 with NaN for columns not asked for or dropped; failed
    is (len(columns), H) bool in the order of `columns`, or None if anything was dropped; investable is
    (n_years + 1, len(columns), H) when tracked.
    """
    hh = inputs.household
    H = prep.hist.stock.shape[0]
    A = len(ages_a)
    K = len(trials)
    N = len(columns)
    ages_arr = np.asarray(list(ages_a), dtype=np.int64)
    col_a_req = np.asarray([a for a, _ in columns], dtype=np.int64)
    col_k_req = np.asarray([k for _, k in columns], dtype=np.int64)
    py = hh.plan_year
    jr0 = py - hh.jr.birth_year
    sp0 = py - hh.spouse.birth_year

    # Social Security: one schedule per distinct set of the levers it reads; lever income likewise.
    ss_keys: dict[tuple, int] = {}
    trial_ss = np.asarray([ss_keys.setdefault(_ss_key(lv), len(ss_keys)) for lv in trials], dtype=np.int64)
    ss_levers = [trials[int(np.flatnonzero(trial_ss == g)[0])] for g in range(len(ss_keys))]
    ss_sched = [ss.benefit_schedule(hh, lv, list(ages_a)) for lv in ss_levers]
    li_keys: dict[tuple, int] = {}
    trial_li = [li_keys.setdefault(_lever_income_key(lv), len(li_keys)) for lv in trials]
    li_levers = [trials[trial_li.index(g)] for g in range(len(li_keys))]

    # Rows: a requested column (row_col >= 0) or a trial's shared working row (row_col == -1).
    pending: dict[int, list[int]] = {}
    for c in sorted(range(N), key=lambda c: (col_a_req[c], col_k_req[c])):
        pending.setdefault(int(col_k_req[c]), []).append(c)
    row_k = np.asarray(sorted(pending), dtype=np.int64)
    row_col = np.full(row_k.size, -1, dtype=np.int64)
    row_a = np.full(row_k.size, -1, dtype=np.int64)
    row_age = np.full(row_k.size, _SHARED_AGE, dtype=np.int64)
    C = row_k.size

    def start(b):
        return np.full((C, H), b.balance_cents / 100.0, dtype=DTYPE)

    cash, taxable, trad, roth, hsa = (start(b) for b in (hh.cash, hh.taxable, hh.traditional, hh.roth, hh.hsa))
    r_cash, r_tax, r_trad, r_roth, r_hsa = (np.ascontiguousarray(mix_return(prep.hist, b.mix).T, dtype=DTYPE) for b in (hh.cash, hh.taxable, hh.traditional, hh.roth, hh.hsa))
    c529 = [start(c.plan529) for c in hh.children]
    r_529 = [np.ascontiguousarray(mix_return(prep.hist, c.plan529.mix).T, dtype=DTYPE) for c in hh.children]
    levels = [lv.college_levels or tuple(c.cost_level for c in hh.children) for lv in trials]
    failed = np.zeros((C, H), dtype=bool)
    tax_carry = np.zeros((C, H), dtype=DTYPE)

    salary = hh.salary_cents / 100.0
    k401 = min(salary * hh.k401_pct_bp / 10_000, K401_LIMIT_CENTS / 100)   # the elective-deferral limit; the excess stays in pay
    roth_part = k401 * hh.k401_roth_share_bp / 10_000
    match = min(k401, salary * hh.match_cap_bp / 10_000) * hh.match_rate_bp / 10_000
    base_wages = salary - (k401 - roth_part)
    surplus = hh.surplus_cents / 100.0
    save_more = [lv.save_more_monthly_cents / 100.0 * 12 for lv in trials]
    basis = [hh.spending_basis_cents / 100.0 * lv.spending_pct / 100 for lv in trials]
    mortgage = hh.mortgage_payment_cents / 100.0
    mortgage_real = fixed_dollars_by_year(mortgage, prep.hist.cpi, prep.n_years)   # (Y, H) today's dollars, or None (D10)
    premium = hh.health_premium_cents / 100.0
    part_b = rules.table("medicare", py)["part_b_monthly"] * 12
    rmd_age = rmd_start_age(hh.jr.birth_year, py)
    one_off: dict[int, float] = {}
    for c in hh.one_off_costs:                       # phase 11c: by year, in today's dollars, never grown
        one_off[c.year] = one_off.get(c.year, 0.0) + c.cents / 100.0

    def row_of_col():
        """For each requested column, the row that holds its state: its own, or its trial's shared working row."""
        out = np.empty(N, dtype=np.int64)
        own = row_col >= 0
        out[row_col[own]] = np.flatnonzero(own)
        for k in pending:
            out[pending[k]] = np.flatnonzero((row_col == -1) & (row_k == k))[0]
        return out

    investable = np.empty((prep.n_years + 1, N, H)) if track_investable else None
    if investable is not None:
        total = cash + taxable + trad + roth + hsa
        investable[0] = total[row_of_col()]
    rates = np.full((K, A), np.nan)
    doomed = np.zeros((K, A), dtype=bool)
    dropped = np.zeros(N, dtype=bool)
    drop = np.zeros(C, dtype=bool)
    jr_alive_all = prep.deaths.jr[:, None]
    sp_alive_all = prep.deaths.spouse[:, None]
    groups = None

    for t in range(prep.n_years):
        year = py + t
        jr_age = jr0 + t
        sp_age = sp0 + t

        # Give each column its own row in the year it retires, and every column of a trial its own row once either
        # spouse could have claimed; drop the columns found doomed last year.
        forks: list[int] = []
        for k in list(pending):
            lv = trials[k]
            cols = pending[k]
            if jr_age >= lv.jr_claim_age or sp_age >= lv.spouse_claim_age:
                take = len(cols)
            else:
                take = 0
                while take < len(cols) and ages_arr[col_a_req[cols[take]]] <= jr_age:
                    take += 1
            if take:
                forks.extend(cols[:take])
                del cols[:take]
                if not cols:
                    del pending[k]                 # its shared row goes at the rebuild below
        n_drop = int(drop.sum())
        if forks or (n_drop and n_drop * 8 >= C):      # a few doomed rows wait until dropping them pays for the copy
            shared_row = {int(row_k[r]): r for r in np.flatnonzero(row_col == -1)}
            keep_rows = np.flatnonzero(~drop & ((row_col >= 0) | np.isin(row_k, list(pending))))
            dropped[row_col[drop]] = True
            fk = col_k_req[forks]
            src = np.concatenate([keep_rows, np.asarray([shared_row[int(k)] for k in fk], dtype=np.int64)])
            new_col = np.concatenate([row_col[keep_rows], np.asarray(forks, dtype=np.int64)])
            new_k = np.concatenate([row_k[keep_rows], fk])
            new_a = np.concatenate([row_a[keep_rows], col_a_req[forks]])
            new_age = np.concatenate([row_age[keep_rows], ages_arr[col_a_req[forks]]])
            order = np.lexsort((new_k, new_age))
            idx = src[order]
            row_col, row_k, row_a, row_age = new_col[order], new_k[order], new_a[order], new_age[order]
            cash, taxable, trad, roth, hsa, tax_carry, failed = (x[idx] for x in (cash, taxable, trad, roth, hsa, tax_carry, failed))
            c529 = [x[idx] for x in c529]
            C = row_k.size
            drop = np.zeros(C, dtype=bool)
            groups = None
        if C == 0:
            break
        if groups is None:
            basis_col = _per_column(basis, row_k)
            g_of_row = trial_ss[row_k]
            groups = []
            for g in np.unique(g_of_row):
                rows = np.flatnonzero(g_of_row == g)
                sch = ss_sched[g]
                a_idx = np.maximum(row_a[rows], 0)     # a shared row's benefit is zero (nobody has claimed), any age will do
                sub = ss.BenefitSchedule(jr_own=sch.jr_own[a_idx], sp_own=sch.sp_own, sp_spousal=sch.sp_spousal[a_idx], jr_spousal=sch.jr_spousal)
                groups.append((rows, sub, ss_levers[g], rows.size == C))
            present_li = sorted({trial_li[k] for k in row_k.tolist()})

        # Columns that retired in an earlier year: none in the first year, whatever the ages.
        seeded = 0 if t == 0 else int(np.searchsorted(row_age, jr_age - 1, side="right"))
        nr = int(np.searchsorted(row_age, jr_age, side="right"))   # Person 1 retires at the start of the year they turn the candidate age;
                                                                   # rows are in ascending age, so retired rows are the prefix [:nr]

        # College: the child's 529 pays first; the shortfall waits for the branch below. Each trial's level sets the
        # years (two from 18 for two_year, four for the rest), costed at the child's own share and living choice.
        short = np.zeros((C, H), dtype=DTYPE)
        contrib529 = 0.0
        for i, child in enumerate(hh.children):
            cage = year - child.birth_year
            if cage < COLLEGE_START_AGE:
                yearly = child.monthly_contribution_cents / 100.0 * 12
                contrib529 += yearly
                c529[i][nr:] += yearly
                continue
            per_trial = [college_cost(lv_levels[i], year, py, child.share_pct, child.covers_living)
                         if cage < COLLEGE_START_AGE + college_years(lv_levels[i]) else 0.0 for lv_levels in levels]
            if any(per_trial):
                cost = _per_column(per_trial, row_k)
                pay = np.minimum(c529[i], cost)        # the 529 pays first toward what the household plans to cover
                c529[i] -= pay
                short += cost - pay

        if year in one_off:
            short += one_off[year]                    # paid as a college shortfall is: cash first, then the buckets in order

        jr_alive, sp_alive = jr_alive_all > jr_age, sp_alive_all > sp_age
        benefit = np.empty((C, H), dtype=DTYPE)
        for rows, sub, lv, whole in groups:
            monthly = ss.household_benefit(sub, lv, year, jr_age, sp_age, jr_alive, sp_alive).T
            if whole:
                benefit[...] = monthly
            else:
                benefit[rows] = monthly
        benefit *= 12

        # Working years (spec 3.4): contributions and match, surplus, lever income, 529s, college.
        # Working rows are a suffix; each branch below only touches its own rows.
        if nr < C:
            W = slice(nr, C)
            trad[W] += k401 - roth_part + match
            roth[W] += roth_part
            lever_w = {g: lever_income_after_tax(hh, li_levers[g], year, jr_age, sp_age, base_wages) for g in present_li}
            net_in = [surplus + save_more[k] - contrib529 + lever_w.get(trial_li[k], 0.0) for k in range(K)]
            net_in = _per_column(net_in, row_k[W]) + benefit[W]   # benefits already claimed, untaxed (approximate)
            if mortgage and hh.mortgage_payoff_year is not None and py <= hh.mortgage_payoff_year:
                # Today's surplus paid today's payment. While the loan runs, the fixed payment costs less each year in
                # today's dollars and the difference is saved; once it is paid off, the whole of today's payment is (D10).
                if year < hh.mortgage_payoff_year:
                    if mortgage_real is not None:
                        net_in += mortgage - mortgage_real[t]
                else:
                    net_in += mortgage
            taxable[W] += np.maximum(net_in, 0.0)
            need_w = np.maximum(-net_in, 0.0) + short[W]
            rem_w = _draw([cash[W], taxable[W], trad[W], roth[W]], need_w)
            failed[W] |= rem_w > SHORTFALL_TOLERANCE

        # Retirement years: spending need, less Social Security and lever income, met after tax in order.
        if nr > 0:
            R = slice(0, nr)
            if jr_age >= MEDICARE_AGE and sp_age >= MEDICARE_AGE:
                health = 0.0
            elif max(jr_age, sp_age) >= MEDICARE_AGE:
                health = premium / 2
            else:
                health = premium
            medicare = part_b * (int(jr_age >= MEDICARE_AGE) + int(sp_age >= MEDICARE_AGE))
            ben_r = benefit[R]
            spend = _per_column([b + health + medicare for b in basis], row_k[R]) + short[R]
            if mortgage and hh.mortgage_payoff_year is not None and year < hh.mortgage_payoff_year:
                spend += mortgage if mortgage_real is None else mortgage_real[t]   # the fixed payment, in today's dollars (D10)
            lever_r = {g: lever_income(hh, li_levers[g], year, jr_age, sp_age, 0.0) for g in present_li}
            no_lever = LeverIncome(cash=0.0, ordinary=0.0)
            lever_ord = _per_column([lever_r.get(g, no_lever).ordinary for g in trial_li], row_k[R])
            gross = spend - ben_r                        # the need less income; income beyond it is saved after tax
            gross -= _per_column([lever_r.get(g, no_lever).cash for g in trial_li], row_k[R])
            n_aged = int(jr_age >= MEDICARE_AGE) + int(sp_age >= MEDICARE_AGE)
            # Columns that retired in an earlier year start from last year's tax and need one pass; columns
            # retiring this year have no earlier tax, so they get a second pass from zero.
            # Rows are independent, so the work goes in blocks small enough for the float64 tax temporaries to stay in cache.
            block = max(1, RETIRE_BLOCK_CELLS // H)
            for lo, hi, passes in ((0, seeded, TAX_GROSS_UP_PASSES), (seeded, nr, TAX_GROSS_UP_PASSES + 1)):
                for b0 in range(lo, hi, block):
                    _retire_year(slice(b0, min(b0 + block, hi)), passes, hh, year, basis_col, n_aged, gross, ben_r, lever_ord, jr_age >= rmd_age,
                                 jr_age, cash, taxable, trad, hsa, roth, tax_carry, failed)

        # Growth: each bucket by its mix's real return for the year, less fees.
        cash *= 1.0 + r_cash[t]
        taxable *= 1.0 + r_tax[t]
        trad *= 1.0 + r_trad[t]
        roth *= 1.0 + r_roth[t]
        hsa *= 1.0 + r_hsa[t]
        for i in range(len(c529)):
            c529[i] *= 1.0 + r_529[i][t]
        np.maximum(cash, 0.0, out=cash)
        np.maximum(taxable, 0.0, out=taxable)
        if investable is not None:
            where = row_of_col()
            in_place = C == N and np.array_equal(where, np.arange(N))
            total = investable[t + 1] if in_place else np.empty((C, H))
            np.add(cash, taxable, out=total)
            total += trad
            total += roth
            total += hsa
            if not in_place:
                investable[t + 1] = total[where]

        if stop_below is not None and nr > 0:
            # Failures only accumulate, so a column whose success rate is already below the threshold stays below it.
            # The rate is computed as the final one is (successes over H in float64), so the test is exact.
            own = np.flatnonzero(row_col >= 0)
            ka = (row_k[own], row_a[own])
            doomed[ka] |= (H - np.count_nonzero(failed[own], axis=1)) / H < stop_below
            older = np.ones(own.size, dtype=bool)
            if keep_before_crossing:
                has_older = row_a[own] < A - 1
                older[has_older] = doomed[row_k[own][has_older], row_a[own][has_older] + 1]
            drop = np.zeros(C, dtype=bool)
            drop[own] = doomed[ka] & older

    final_rows = row_of_col() if C else np.zeros(N, dtype=np.int64)
    live = ~dropped
    if C:
        rates[col_k_req[live], col_a_req[live]] = (~failed[final_rows[live]]).mean(axis=1)
    return rates, (failed[final_rows] if not dropped.any() else None), investable


def simulate(inputs: EngineInputs, levers: Levers, ages: Sequence[int], prep: Prepared, *,
             track_investable: bool = True) -> SimOutput:
    """track_investable=False skips the year-by-year balances (only the band needs them); success is unchanged."""
    ages_in = np.asarray(list(ages))
    A = len(ages_in)
    order = np.argsort(ages_in, kind="stable")      # the loop wants ascending ages; results are put back in the caller's order
    # Equal ages are separate columns with the same answer; the loop's age list holds each column's own entry.
    _, failed, investable = _run(inputs, [levers], ages_in[order].tolist(), [(a, 0) for a in range(A)], prep,
                                 track_investable=track_investable, stop_below=None)
    success = ~failed
    if not np.array_equal(order, np.arange(A)):
        inv = np.argsort(order)
        success = success[inv]
        if investable is not None:
            investable = investable[:, inv]
    return SimOutput(investable=None if investable is None else investable.transpose(0, 2, 1), success=success.T)


def trial_success_rates(inputs: EngineInputs, trials: Sequence[Levers], ages: Sequence[int], prep: Prepared, *,
                        columns: Sequence[tuple[int, int]] | None = None, stop_below: float,
                        keep_before_crossing: bool = True) -> np.ndarray:
    """Success rates (K, A) for several lever sets over the same strictly ascending ages and the same draws, in one batch.

    columns: (age index, trial index) pairs to run; all of them by default. A rate is NaN for a column not run or
    dropped as unable to reach `stop_below` (see _run); every other rate is exactly what simulate() gives for that
    lever set and age.
    """
    ages_list = list(ages)
    if any(b <= a for a, b in zip(ages_list, ages_list[1:])):
        raise ValueError("trial_success_rates needs strictly ascending ages")
    if columns is None:
        columns = [(a, k) for a in range(len(ages_list)) for k in range(len(trials))]
    if not columns:
        return np.full((len(trials), len(ages_list)), np.nan)
    rates, _, _ = _run(inputs, trials, ages_list, columns, prep, track_investable=False, stop_below=stop_below,
                       keep_before_crossing=keep_before_crossing)
    return rates
