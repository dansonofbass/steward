"""Household tools (spec 4.2): facts, the plan's result, what-ifs, lever impacts and the savings checklist. They use
the Plan screen's cached solve and impacts, so the ages match the screen. No engine sentence is sent: assumptions,
levers and checklist items go as typed fields, and lever fields keyed jr or spouse are renamed person_1_ and
person_2_ (ruling 5)."""
from __future__ import annotations

from datetime import date

from steward.advisor.tools import PlanFailed, Ref, ToolEnv, ToolError, register
from steward.advisor.tools.common import BAD_INPUT, age
from steward.db.models import active_children
from steward.engine import EngineInputs, savings_checklist
from steward.engine.tax.state import module_for
from steward.services.plan import impacts_cached, latest_plan, saved_state, solve_cached
from steward.services.accounts import mortgage_rate_bp
from steward.services.plan_inputs import SetupIncomplete, build_checklist, build_inputs, latest_facts
from steward.services.plan_levers import LeverError, levers_dict, resolve_state

ENGINE_FIELDS = {
    "save_more_monthly_cents": "save_more_monthly_cents", "spending_pct": "spending_pct",
    "consulting_cents": "consulting_cents", "consulting_until_age": "consulting_until_age",
    "gift_cents": "gift_cents", "gift_until_year": "gift_until_year",
    "person_2_earnings_cents": "spouse_earnings_cents", "person_2_start_year": "spouse_start_year",
    "person_2_stop_age": "spouse_stop_age", "person_1_claim_age": "jr_claim_age",
    "person_2_claim_age": "spouse_claim_age",
}
LEVER_SENT = {"jr_claim": "person_1_claim", "spouse_claim": "person_2_claim", "spouse_earnings": "person_2_earnings"}


def _inputs(env: ToolEnv):
    try:
        return env.plan_cache.inputs.get_or_build(env.today, lambda: build_inputs(env.db, env.today))
    except SetupIncomplete:
        raise ToolError("The plan isn't set up yet.") from None


def _solve(env: ToolEnv, inputs: EngineInputs):
    try:
        return solve_cached(env.plan_cache, inputs)
    except Exception as e:  # noqa: BLE001 - any engine failure is spec 8's answer
        raise PlanFailed(e) from None


def _result(res) -> dict:
    return {"comfortable_age": res.comfortable_age, "likely_age": res.likely_age,
            "comfortable_year": res.comfortable_year, "likely_year": res.likely_year,
            "success_by_age": [{"age": a, "rate": round(r, 4)} for a, r in res.success_by_age][:80],
            "band": [{"year": p.year, "person_1_age": p.jr_age, "p10_cents": p.p10_cents, "p50_cents": p.p50_cents,
                      "p90_cents": p.p90_cents} for p in res.band][:80]}


def _state(env: ToolEnv, pi, body: dict):
    try:
        return resolve_state(body, saved_state(latest_plan(env.db)), pi.household, pi.observed)[0]
    except LeverError:
        raise ToolError(BAD_INPUT) from None


@register("facts")
def facts(inp: dict, env: ToolEnv) -> dict:
    f = latest_facts(env.db)

    def num(key: str, cast=int):
        try:
            return cast(f[key].value) if key in f else None
        except ValueError:
            return None
    ages = []
    for key in ("jr", "spouse"):
        try:
            if f"{key}.dob" in f:
                ages.append({"alias": Ref("owner", key), "age": age(date.fromisoformat(f[f"{key}.dob"].value), env.today)})
        except ValueError:
            pass
    payoff = f["mortgage.payoff_date"].value[:7] if "mortgage.payoff_date" in f else None
    return {"salary_person": Ref("owner", "jr"), "salary_cents": num("jr.salary_cents"),
            "k401_pct_bp": num("jr.k401_pct_bp"), "k401_roth_share_bp": num("jr.k401_roth_share_bp"),
            "employer_match_rate_bp": num("employer.match_rate_bp"), "employer_match_cap_bp": num("employer.match_cap_bp"),
            "state": f["state"].value if "state" in f else None,
            "filing_status": f["filing_status"].value if "filing_status" in f else None,
            "home_value_cents": num("home.value_cents"), "mortgage_rate_bp": mortgage_rate_bp(env.db, f),
            "mortgage_payment_cents": num("mortgage.payment_cents"), "mortgage_payoff_month": payoff,
            "health_premium_cents": num("health.premium_cents"), "ages": ages}


def state_tax_word(state: str) -> str:
    """What plan_result says about state tax: one fixed word, never a number (plan ruling 9)."""
    if state == "CA":
        return "california"
    return "none" if module_for(state) is not None else "not_calculated"


@register("plan_result")
def plan_result(inp: dict, env: ToolEnv) -> dict:
    pi = _inputs(env)
    state = _state(env, pi, {})
    res = _solve(env, EngineInputs(pi.household, state.assumed))
    hh = pi.household
    state_tax = state_tax_word(hh.state)
    return {"saved": latest_plan(env.db) is not None, "age_of": Ref("owner", "jr"), **_result(res),
            "assumptions": {"histories": res.histories, "full_ss_benefits": state.assumed.full_ss_benefits,
                            "state_tax": state_tax, "spending_months": hh.spending_months,
                            "spending_basis_cents": hh.spending_basis_cents,
                            "mortgage_payoff_year": hh.mortgage_payoff_year}}


@register("plan_what_if")
def plan_what_if(inp: dict, env: ToolEnv) -> dict:
    # A lever left out, or sent as null by an older caller, stays as it is.
    levers = inp["levers"]
    changes = {ENGINE_FIELDS[k]: v for k, v in levers.items() if k in ENGINE_FIELDS and v is not None}
    if levers.get("college_levels") is not None:
        changes["college_levels"] = list(levers["college_levels"])
    if levers.get("full_ss_benefits") is not None:
        changes["full_ss_benefits"] = levers["full_ss_benefits"]
    pi = _inputs(env)
    state = _state(env, pi, {"assumed": changes})
    res = _solve(env, EngineInputs(pi.household, state.assumed))
    used = levers_dict(state.assumed)
    return {"age_of": Ref("owner", "jr"), **_result(res),
            "levers_used": {**{sent: used[engine] for sent, engine in ENGINE_FIELDS.items()},
                            "college_levels": used["college_levels"], "full_ss_benefits": used["full_ss_benefits"]}}


@register("plan_lever_impacts")
def plan_lever_impacts(inp: dict, env: ToolEnv) -> dict:
    pi = _inputs(env)
    state = _state(env, pi, {})
    try:
        rows = impacts_cached(env.plan_cache, EngineInputs(pi.household, state.assumed), state.trial)
    except Exception as e:  # noqa: BLE001
        raise PlanFailed(e) from None
    children = {c.label: c.id for c in env.db.scalars(active_children())}
    return {"impacts": [{"lever": LEVER_SENT.get(i.key, i.key),
                         "child": Ref("child", children[i.child_label]) if i.child_label in children else None,
                         "try_value": i.try_value, "delta_months": i.delta_months,
                         "comfortable_age": i.comfortable_age} for i in rows][:30]}


@register("savings_checklist")
def savings_checklist_tool(inp: dict, env: ToolEnv) -> dict:
    ci, names = build_checklist(env.db, env.today)
    key_of = {names[k]: k for k in ("spouse", "jr")}          # the checklist names the adults; we send their aliases
    months = round(ci.cash_cents * 12 / ci.spending_basis_cents, 1) if ci.spending_basis_cents > 0 else None
    return {"items": [{"item": i.key, "status": i.status} for i in savings_checklist(ci)],
            "numbers": {"cash_months": months, "k401_pct_bp": ci.k401_pct_bp, "match_cap_bp": ci.match_cap_bp,
                        "k401_contribution_cents": ci.k401_contribution_cents,
                        "interest_charges_3mo": ci.interest_charges_3mo,
                        "hsa_contributions_12mo_cents": ci.hsa_contributions_12mo_cents,
                        "taxable_contributions_12mo_cents": ci.taxable_contributions_12mo_cents,
                        "missing_roth": [Ref("owner", key_of[o]) for o in ci.owners
                                         if o not in ci.roth_contributed_owners and o in key_of]}}
