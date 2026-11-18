"""Every tool Claude may call (spec 4.2): what it is for, what it takes, and exactly what it returns. The NAS checks a
result against its schema before it leaves; the gateway checks it again before anything is sent (spec 4.5). Every
field here reaches Claude, so a change is a boundary change (spec 11.3, ruling 25). All tools are offered in every
book so the cached prefix is the same everywhere (ruling 6)."""
from __future__ import annotations

from dataclasses import dataclass

from steward_boundary import vocab as V
from steward_boundary.schema import (
    ALIAS, BOOL, DATE, IN_DATE, INT, MONTH, NUM, SYMBOL, arr, enum, free_text, nullable, obj,
)
from steward_boundary.validate import validate

DECLINED = "The person declined to share store names for this question. Answer from totals."
NEEDS_MANAGER = "Store names need a manager's OK, and the person asking can't give it. Answer from totals."
ERRORS = ("Not in this book.", "That input wasn't understood.", "This couldn't be looked up just now.",
          "The plan isn't set up yet.", "The plan couldn't be worked out.", "That period is too long.",
          DECLINED, NEEDS_MANAGER)
MERCHANT = "merchant_detail"
MERCHANT_DAYS, MERCHANT_ROWS = 92, 200      # spec 4.2: at most 92 days and 200 rows
MERCHANT_STORE_CHARS = 60                   # a store name as a row shows and sends it (plan B ruling 2)
ERROR_RESULT = obj({"error": enum(ERRORS)})
NO_INPUT = obj({})
EVERY, HOUSEHOLD, PARENT = ("household", "parent"), ("household",), ("parent",)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    result_schema: dict
    books: tuple[str, ...]
    status: str
    # Sent with strict: true unless False. Anthropic compiles every strict schema in a request into one grammar and
    # refuses one that is too big ("Schema is too complex", 2026-10-25); each optional parameter roughly doubles it.
    # The NAS validates every input against the schema anyway (validate_input), so a tool whose input is mostly
    # optional is sent without strict.
    strict: bool = True


TYPE_TOTAL = obj({"account_type": enum(V.ACCOUNT_TYPES), "balance_cents": INT})
SUCCESS = arr(obj({"age": INT, "rate": NUM}), 80)
BAND = arr(obj({"year": INT, "person_1_age": INT, "p10_cents": INT, "p50_cents": INT, "p90_cents": INT}), 80)
AGES = {"comfortable_age": nullable(INT), "likely_age": nullable(INT), "comfortable_year": nullable(INT),
        "likely_year": nullable(INT)}
WHAT_IF_INTS = ("save_more_monthly_cents", "spending_pct", "consulting_cents", "consulting_until_age", "gift_cents",
                "gift_until_year", "person_2_earnings_cents", "person_2_start_year", "person_2_stop_age",
                "person_1_claim_age", "person_2_claim_age")
# plan_what_if's input: every lever is optional and none is nullable, so a lever left out stays as it is.
WHAT_IF_LEVERS = {**{f: INT for f in WHAT_IF_INTS}, "college_levels": arr(enum(V.COLLEGE_LEVELS)),
                  "full_ss_benefits": BOOL}
LEVERS_USED = obj({**{f: INT for f in WHAT_IF_INTS}, "college_levels": nullable(arr(enum(V.COLLEGE_LEVELS), 12)),
                   "full_ss_benefits": BOOL})
ASSUMPTIONS = obj({"histories": INT, "full_ss_benefits": BOOL, "state_tax": enum(V.STATE_TAX),
                   "spending_months": INT, "spending_basis_cents": INT, "mortgage_payoff_year": nullable(INT)})
PERIOD = obj({"start": DATE, "end": DATE, "total_out_cents": INT,
              "categories": arr(obj({"category": enum(V.CATEGORIES), "out_cents": INT, "count": INT}), 30)})
CARE_SCENARIO = obj({"n": INT, "level": enum(V.CARE_LEVELS), "care_start_year": nullable(INT),
                     "hours_a_week": nullable(INT), "adult_day_days": nullable(INT),
                     "room": nullable(enum(V.CARE_ROOMS)), "home_sale_year": nullable(INT), "family_monthly_cents": INT,
                     "spending_change_monthly_cents": INT, "care_monthly_cents": INT, "care_cost_is_quote": BOOL,
                     "lasts_until_year": nullable(INT), "lasts_until_age": nullable(INT),
                     "lasts_past_age": nullable(INT), "ltc_pays_from_year": nullable(INT),
                     "ltc_runs_out_year": nullable(INT), "medi_cal_year": INT,
                     "medi_cal_status": enum(V.MEDI_CAL_STATUSES), "medi_cal_over_cents": INT,
                     "medi_cal_first_eligible_year": nullable(INT)})
ITEM = obj({"kind": enum(V.ITEM_KINDS), "type": nullable(enum(V.ITEM_TYPES)), "n": INT, "status": enum(V.ITEM_STATUSES),
            "owner": ALIAS, "account": nullable(ALIAS), "amount_cents": nullable(INT),
            "frequency": nullable(enum(V.FREQUENCIES)), "usual_day": nullable(INT), "lands_in": nullable(ALIAS),
            "paid_from": nullable(ALIAS), "paid_from_income": nullable(enum(V.INCOME_SOURCES)),
            "renewal_month": nullable(MONTH), "balance_cents": nullable(INT), "as_of": nullable(DATE)})

TOOLS: tuple[ToolSpec, ...] = tuple(sorted([
    ToolSpec("book_summary",
             "Start here. The book's kind, today's date, the people as aliases with ages and roles, which alias is "
             "asking, the state and filing status (household books), net worth and totals by account type. Amounts "
             "are in cents.",
             NO_INPUT,
             obj({"book_kind": enum(V.BOOK_KINDS), "today": DATE, "asker": ALIAS,
                  "people": arr(obj({"alias": ALIAS, "age": nullable(INT), "role": enum(V.PERSON_ROLES),
                                     "is_asker": BOOL}), 40),
                  "state": nullable(enum(V.STATES)), "filing_status": nullable(enum(V.FILING_STATUSES)),
                  "net_worth_cents": INT, "totals_by_account_type": arr(TYPE_TOTAL, 20)}),
             EVERY, "Looking at the book"),
    ToolSpec("accounts",
             "Each account by alias: type, tax treatment, owner alias, latest balance in cents and its date, how its "
             "data arrives (bank feed, statements, files such as CSV or typed in) and whether its bank feed is behind. "
             "Liabilities are negative. Set include_closed to see closed accounts too.",
             obj({"include_closed": BOOL}),
             obj({"accounts": arr(obj({"account": ALIAS, "account_type": enum(V.ACCOUNT_TYPES),
                                       "tax_treatment": enum(V.TAX_TREATMENTS), "owner": ALIAS,
                                       "balance_cents": nullable(INT), "as_of": nullable(DATE),
                                       "arrives": enum(V.DATA_ARRIVES), "sync_behind": BOOL, "active": BOOL}), 300)}),
             EVERY, "Looking at accounts"),
    ToolSpec("balance_history",
             "Net worth at the end of each month for the last `months` months (1 to 60), newest last, optionally "
             "split by account type. The current month uses today's balances. Give `account` (an alias) to get that "
             "account's month-end balance too.",
             obj({"months": INT, "by_account_type": BOOL, "account": {"type": "string"}}, optional=("account",)),
             obj({"months": arr(obj({"month": MONTH, "net_worth_cents": INT,
                                     "by_account_type": nullable(arr(TYPE_TOTAL, 20)),
                                     "account_cents": nullable(INT)}), 60)}),
             EVERY, "Looking at balances over time"),
    ToolSpec("cash_flow",
             "Money in and money out per calendar month for the last `months` months (1 to 60), the same figures as "
             "Steward's Spending and Home: personal accounts at their personal share, transfers and card payments left "
             "out, refunds netted against their own category (what takes a category past $0 is money in). Reimbursable "
             "work expenses and their repayments are left out. Optionally grouped by category, by owner alias, or by "
             "business (business money is reported as its own group). Give `account` (an alias) to count only that account.",
             obj({"months": INT, "by": nullable(enum(V.CASH_FLOW_BY)), "account": {"type": "string"}}, optional=("account",)),
             obj({"months": arr(obj({"month": MONTH, "in_cents": INT, "out_cents": INT, "net_cents": INT,
                                     "groups": nullable(arr(obj({"category": nullable(enum(V.CATEGORIES)),
                                                                 "owner": nullable(ALIAS),
                                                                 "business": nullable(BOOL),
                                                                 "in_cents": INT, "out_cents": INT}), 40))}), 60)}),
             EVERY, "Looking at money in and out"),
    ToolSpec("spending_by_category",
             "Spending (money out) by category with counts between two dates, at most 366 days apart, inclusive. Reimbursable "
             "work expenses and their repayments are left out; a leftover settled as not coming back isn't a transaction, so it "
             "shows only in Steward's Spending figures. Set compare_previous to get the period of the same length just before it.",
             obj({"start": IN_DATE, "end": IN_DATE, "compare_previous": BOOL}),
             obj({"period": PERIOD, "previous": nullable(PERIOD)}),
             EVERY, "Looking at spending by category"),
    ToolSpec("recurring",
             "Payments and deposits that repeat, found from the last 13 months: payee alias, direction, category, "
             "cadence, the range of amounts, the usual day of the month, when it was last seen and whether the next "
             "one is late.",
             NO_INPUT,
             obj({"items": arr(obj({"payee": ALIAS, "direction": enum(V.DIRECTIONS), "category": enum(V.CATEGORIES),
                                    "cadence": enum(V.CADENCES), "low_cents": INT, "high_cents": INT,
                                    "usual_day": nullable(INT), "last_seen": DATE, "late": BOOL}), 150)}),
             EVERY, "Looking at recurring payments"),
    ToolSpec("holdings",
             "Investments in each account: ticker symbol (null when there is none), asset class, value and cost "
             "basis when known, with totals by asset class.",
             NO_INPUT,
             obj({"holdings": arr(obj({"symbol": nullable(SYMBOL), "asset_class": enum(V.ASSET_CLASSES),
                                       "account": ALIAS, "value_cents": INT, "cost_basis_cents": nullable(INT),
                                       "as_of": DATE}), 500),
                  "totals_by_asset_class": arr(obj({"asset_class": enum(V.ASSET_CLASSES), "value_cents": INT}), 10)}),
             EVERY, "Looking at holdings"),
    ToolSpec(MERCHANT,
             "Only when totals and payee aliases can't answer the question: the transactions between two dates at "
             "most 92 days apart, inclusive, newest first and at most 200, each with its date, amount in cents (money "
             "out is negative), category, account alias and the store or payee name; and, for payee aliases listed in "
             "`payees`, the name behind each. A manager of the book sees exactly these rows and must approve them for "
             "this one question, so write `reason` as one plain sentence the person will read, saying why totals "
             "aren't enough. Narrow with `category` when you can. If the result says the names weren't shared, "
             "answer from totals and don't ask again in this turn.",
             obj({"reason": {"type": "string"}, "start": IN_DATE, "end": IN_DATE,
                  "category": nullable(enum(V.CATEGORIES)), "payees": nullable(arr({"type": "string"}))}),
             obj({"rows": arr(obj({"date": DATE, "amount_cents": INT, "category": enum(V.CATEGORIES),
                                   "merchant": free_text(MERCHANT_STORE_CHARS), "account": ALIAS}), MERCHANT_ROWS),
                  "payees": arr(obj({"payee": ALIAS, "name": free_text(80)}), 50), "more": BOOL}),
             EVERY, "Asking for store names"),
    ToolSpec("debts",
             "Credit cards, the mortgage and loans: kind, balance owed in cents (positive), interest rate in basis "
             "points, monthly payment and payoff month when known.",
             NO_INPUT,
             obj({"debts": arr(obj({"account": ALIAS, "kind": enum(V.DEBT_KINDS), "balance_cents": INT,
                                    "rate_bp": nullable(NUM), "payment_cents": nullable(INT),
                                    "payoff_month": nullable(MONTH)}), 50)}),
             EVERY, "Looking at debts"),
    ToolSpec("facts",
             "Household books: the facts the plan uses. Salary (whose, as an alias), 401(k) rate and Roth share, the "
             "employer match, state, filing status, home value, mortgage rate, payment and payoff month, the health "
             "premium, and each adult's age. Rates are in basis points.",
             NO_INPUT,
             obj({"salary_person": ALIAS, "salary_cents": nullable(INT), "k401_pct_bp": nullable(INT),
                  "k401_roth_share_bp": nullable(INT), "employer_match_rate_bp": nullable(INT),
                  "employer_match_cap_bp": nullable(INT), "state": nullable(enum(V.STATES)),
                  "filing_status": nullable(enum(V.FILING_STATUSES)), "home_value_cents": nullable(INT),
                  "mortgage_rate_bp": nullable(NUM), "mortgage_payment_cents": nullable(INT),
                  "mortgage_payoff_month": nullable(MONTH), "health_premium_cents": nullable(INT),
                  "ages": arr(obj({"alias": ALIAS, "age": INT}), 20)}),
             HOUSEHOLD, "Looking at household facts"),
    ToolSpec("plan_result",
             "Household books: the saved retirement plan's result. The comfortable age (high chance of success) and "
             "likely age, as ages of age_of and as years, the chance of success by retirement age, the band of "
             "outcomes by year, and the assumptions behind it.",
             NO_INPUT,
             obj({"saved": BOOL, "age_of": ALIAS, **AGES, "success_by_age": SUCCESS, "band": BAND,
                  "assumptions": ASSUMPTIONS}),
             HOUSEHOLD, "Looking at the plan"),
    ToolSpec("plan_what_if",
             "Household books: the plan with some levers changed. Give a value for each lever to change and leave "
             "out the levers that stay as they are; nothing is saved. Money is in cents a year except "
             "save_more_monthly_cents; spending_pct is a percentage of today's spending; claim ages are 62 to 70.",
             obj({"levers": obj(WHAT_IF_LEVERS, optional=tuple(WHAT_IF_LEVERS))}),
             obj({"age_of": ALIAS, **AGES, "success_by_age": SUCCESS, "band": BAND, "levers_used": LEVERS_USED}),
             HOUSEHOLD, "Trying the plan with changes", strict=False),
    ToolSpec("plan_lever_impacts",
             "Household books: which changes move the comfortable retirement age most, ranked. Each has the lever, "
             "the child it applies to when it is a college lever, the value tried, the change in months (negative "
             "is earlier) and the resulting comfortable age.",
             NO_INPUT,
             obj({"impacts": arr(obj({"lever": enum(V.LEVER_KEYS), "child": nullable(ALIAS),
                                      "try_value": {"anyOf": [INT, BOOL, enum(V.COLLEGE_LEVELS)]},
                                      "delta_months": nullable(INT), "comfortable_age": nullable(INT)}), 30)}),
             HOUSEHOLD, "Looking at what moves the plan"),
    ToolSpec("savings_checklist",
             "Household books: the savings checklist. Each item is done, not yet, or can't tell, with the numbers "
             "behind the items and the adults who haven't added to a Roth IRA in the last 12 months.",
             NO_INPUT,
             obj({"items": arr(obj({"item": enum(V.CHECKLIST_ITEMS), "status": enum(V.CHECKLIST_STATUSES)}), 10),
                  "numbers": obj({"cash_months": nullable(NUM), "k401_pct_bp": nullable(INT),
                                  "match_cap_bp": nullable(INT), "k401_contribution_cents": nullable(INT),
                                  "interest_charges_3mo": nullable(INT), "hsa_contributions_12mo_cents": nullable(INT),
                                  "taxable_contributions_12mo_cents": nullable(INT),
                                  "missing_roth": arr(ALIAS, 4)})}),
             HOUSEHOLD, "Looking at the savings checklist"),
    ToolSpec("inventory",
             "Parent books: everything the parent has. Items by kind with type, status, owner alias, account alias, "
             "amounts and how often, usual day, where income lands or a premium is paid from, renewal month and "
             "balance; how many need checking; totals by group. `n` tells apart two items of the same type.",
             obj({"kind": nullable(enum(V.ITEM_KINDS))}),
             obj({"items": arr(ITEM, 300), "needs_checking": INT,
                  "totals": arr(obj({"group": enum(V.TOTAL_GROUPS), "cents": INT}), 5)}),
             PARENT, "Looking at the inventory"),
    ToolSpec("money_in_monthly",
             "Parent books: each income item with its expected amount and usual day, what arrived in each of the last "
             "`months` months (1 to 24) and which months it was missed.",
             obj({"months": INT}),
             obj({"items": arr(obj({"source": enum(V.INCOME_SOURCES), "n": INT, "owner": ALIAS,
                                    "expected_cents": nullable(INT), "usual_day": nullable(INT),
                                    "lands_in": nullable(ALIAS),
                                    "months": arr(obj({"month": MONTH, "arrived_cents": INT,
                                                       "arrived_on": nullable(DATE)}), 24),
                                    "missed": arr(MONTH, 24)}), 40)}),
             PARENT, "Looking at money coming in"),
    ToolSpec("premiums",
             "Parent books: each insurance policy with its premium and how often, what pays it, the last matched "
             "payment, whether a payment was missed, and the renewal month.",
             NO_INPUT,
             obj({"items": arr(obj({"type": enum(V.INSURANCE_TYPES), "n": INT, "owner": ALIAS,
                                    "premium_cents": nullable(INT), "frequency": nullable(enum(V.FREQUENCIES)),
                                    "paid_from": nullable(ALIAS), "paid_from_income": nullable(enum(V.INCOME_SOURCES)),
                                    "last_paid_on": nullable(DATE), "last_paid_cents": nullable(INT), "missed": BOOL,
                                    "renewal_month": nullable(MONTH)}), 40)}),
             PARENT, "Looking at insurance premiums"),
    ToolSpec("flags",
             "Parent books: what Steward's checks flagged to look into: the check, how urgent, status, amount, date, "
             "account and payee aliases. Set include_done to include ones already dealt with.",
             obj({"include_done": BOOL}),
             obj({"flags": arr(obj({"check": enum(V.FLAG_CHECKS), "severity": enum(V.FLAG_SEVERITIES),
                                    "status": enum(V.FLAG_STATUSES), "amount_cents": nullable(INT), "date": DATE,
                                    "account": nullable(ALIAS), "payee": nullable(ALIAS)}), 200)}),
             PARENT, "Looking at flags"),
    ToolSpec("care_projection",
             "Parent books: how long the money lasts in each care scenario: care level, start year (null at "
             "home), hours and adult day days a week, nursing home room, levers (home sale year, family help, "
             "spending change), monthly care cost in today's dollars and whether it's a quote, lasts_until_year "
             "(before this year: short now) and the age then, when long-term care insurance pays and runs out, "
             "and the Medi-Cal check (medi_cal_year is the year care starts). Also the asset limit and its rules "
             "year, and money by month; expected_in/out_cents are the next 60 days. If spending_counted is false, "
             "no spending is counted, so each scenario lasts longer than it would; say so. Cents. An "
             "estimate, not legal advice.",
             NO_INPUT,
             obj({"set_up": BOOL, "age": nullable(INT), "spending_counted": BOOL, "medi_cal_limit_cents": nullable(INT),
                  "medi_cal_rules_year": nullable(INT), "scenarios": arr(CARE_SCENARIO, 5),
                  "monthly": obj({"months": arr(obj({"month": MONTH, "in_cents": INT, "out_cents": INT}), 12),
                                  "expected_in_cents": INT, "expected_out_cents": INT,
                                  "cash_above_floor_cents": INT, "short_month": nullable(MONTH),
                                  "short_cents": INT})}),
             PARENT, "Looking at care"),
], key=lambda t: t.name))
BY_NAME = {t.name: t for t in TOOLS}


def definitions() -> list[dict]:
    """The tool list as sent to Anthropic: sorted by name, strict except where a ToolSpec says not, identical on every
    request (spec 8.2, 8.3)."""
    return [{"name": t.name, "description": t.description, "input_schema": t.input_schema, "strict": t.strict}
            for t in TOOLS]


def _drop_optional_nulls(schema: dict, value: object) -> object:
    """A null for an optional field counts as leaving it out. The schemas don't offer null there (that would make it
    a union), but an input written for the older nullable plan_what_if levers still means the same thing."""
    if not (schema.get("type") == "object" and isinstance(value, dict)):
        return value
    props, required = schema.get("properties") or {}, set(schema.get("required", []))
    return {k: _drop_optional_nulls(props[k], v) if k in props else v for k, v in value.items()
            if not (v is None and k in props and k not in required)}


def validate_input(name: str, value: object) -> list[str]:
    spec = BY_NAME.get(name)
    if spec is None:
        return ["$: no such tool"]
    return validate(spec.input_schema, _drop_optional_nulls(spec.input_schema, value))


def result_schema(name: str, is_error: bool = False) -> dict:
    return ERROR_RESULT if is_error else BY_NAME[name].result_schema


def validate_result(name: str, value: object, is_error: bool = False) -> list[str]:
    if name not in BY_NAME:
        return ["$: no such tool"]
    return validate(result_schema(name, is_error), value)
