"""care_projection (spec 4.5): the Care screen's figures, read-only. Dollar figures, years, booleans and three enums;
no names and nothing people typed: a scenario goes as its level and years, never its wording (ruling 4), and the
monthly summary goes as totals, never payee names."""
from __future__ import annotations

from steward.advisor.tools import ToolEnv, register
from steward.care.scenarios import ScenarioResult, sale_year
from steward.care.views import compute


def _scenario(n: int, r: ScenarioResult, this_year: int) -> dict:
    s, m = r.scenario, r.medi_cal_shown
    return {"n": n, "level": s.level, "care_start_year": None if s.level == "at_home" else r.care_start_year,
            "hours_a_week": s.hours_week, "adult_day_days": s.adult_day_days, "room": s.room,
            "home_sale_year": sale_year(s, this_year),
            "family_monthly_cents": s.family_monthly_cents,
            "spending_change_monthly_cents": s.spending_change_monthly_cents,
            "care_monthly_cents": r.care_monthly_cents, "care_cost_is_quote": r.quote,
            "lasts_until_year": r.lasts_until, "lasts_until_age": r.lasts_until_age,
            "lasts_past_age": r.last_age if r.lasts_until is None else None,
            "ltc_pays_from_year": r.ltc_pays_from, "ltc_runs_out_year": r.ltc_runs_out,
            "medi_cal_year": m.year, "medi_cal_status": m.status, "medi_cal_over_cents": m.over_cents,
            "medi_cal_first_eligible_year": r.medi_cal_first_year}


@register("care_projection")
def care_projection(inp: dict, env: ToolEnv) -> dict:
    v = compute(env.db, {o.key: o.label for o in env.book.owner_names}, env.today)
    m = v.monthly
    b = v.book
    return {"set_up": v.setup is not None, "age": b.age if b else None,
            "spending_counted": b is not None and (b.spending_typed or b.spending_months > 0),
            "medi_cal_limit_cents": v.limit.cents if v.limit else None,
            "medi_cal_rules_year": v.limit.rules_year if v.limit else None,
            "scenarios": [_scenario(i + 1, r, env.today.year) for i, r in enumerate(v.results)],
            "monthly": {"months": [{"month": r["month"], "in_cents": r["in_cents"], "out_cents": r["out_cents"]}
                                   for r in m.months],
                        "expected_in_cents": m.expected_in_cents, "expected_out_cents": m.expected_out_cents,
                        "cash_above_floor_cents": m.above_floor_cents,
                        "short_month": m.short_month.strftime("%Y-%m") if m.short_month else None,
                        "short_cents": m.short_cents}}
