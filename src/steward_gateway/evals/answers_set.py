"""The 30 fictional questions of spec 11.4 over the demo books, each with the figures a correct answer must contain,
worked out by Steward's own tools as of the eval's day. A case whose figure the demo books don't have (a zero amount,
a plan that isn't saved) is skipped and counts as not passed. Questions name the parent rather than saying "her"."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta


class Missing(Exception):
    """The demo books don't have this figure."""


@dataclass(frozen=True)
class Figure:
    kind: str           # "money" (cents), "percent" (basis points) or "number" (a whole number)
    value: int


@dataclass(frozen=True)
class Case:
    id: str
    book: str           # "household" or "parent"
    question: str
    tools: Callable[[date], list[tuple[str, dict]]]
    figures: Callable[[list[dict], date], list[Figure]]


def last_month(today: date) -> tuple[date, date]:
    end = today.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


def full_months(today: date, n: int) -> tuple[date, date]:
    end = today.replace(day=1) - timedelta(days=1)
    start = end.replace(day=1)
    for _ in range(n - 1):
        start = (start - timedelta(days=1)).replace(day=1)
    return start, end


def ym(d: date) -> str:
    return f"{d:%Y-%m}"


def money(cents) -> Figure:
    if not isinstance(cents, int) or cents == 0:
        raise Missing()
    return Figure("money", cents)


def number(n) -> Figure:
    if not isinstance(n, int):
        raise Missing()
    return Figure("number", n)


def cat(period: dict, name: str) -> int:
    return next((c["out_cents"] for c in period["categories"] if c["category"] == name), 0)


def type_total(summary: dict, account_type: str) -> int:
    return next((t["balance_cents"] for t in summary["totals_by_account_type"] if t["account_type"] == account_type), 0)


def spend(start: date, end: date, compare: bool = False) -> tuple[str, dict]:
    return ("spending_by_category", {"start": start.isoformat(), "end": end.isoformat(), "compare_previous": compare})


def month_row(flow: dict, month: str) -> dict:
    return next(m for m in flow["months"] if m["month"] == month)


def arrived(items: list[dict], month: str) -> int:
    return sum(m["arrived_cents"] for i in items for m in i["months"] if m["month"] == month)


def rate(facts: dict) -> list[Figure]:
    if not facts["k401_pct_bp"]:
        raise Missing()
    return [Figure("percent", facts["k401_pct_bp"])]


H, P = "household", "parent"
CASES: tuple[Case, ...] = (
    Case("h01", H, "What's our net worth right now?",
         lambda t: [("book_summary", {})], lambda r, t: [money(r[0]["net_worth_cents"])]),
    Case("h02", H, "How much do we owe in total on cards, the mortgage and loans?",
         lambda t: [("debts", {})], lambda r, t: [money(sum(d["balance_cents"] for d in r[0]["debts"]))]),
    Case("h03", H, "How much did we spend in total last month?",
         lambda t: [spend(*last_month(t))], lambda r, t: [money(r[0]["period"]["total_out_cents"])]),
    Case("h04", H, "How much did we spend on groceries last month?",
         lambda t: [spend(*last_month(t))], lambda r, t: [money(cat(r[0]["period"], "groceries"))]),
    Case("h05", H, "What did we spend on dining over the last three full months?",
         lambda t: [spend(*full_months(t, 3))], lambda r, t: [money(cat(r[0]["period"], "dining"))]),
    Case("h06", H, "Are we spending more on dining in the last three full months than in the three before?",
         lambda t: [spend(*full_months(t, 3), compare=True)],
         lambda r, t: [money(cat(r[0]["period"], "dining")), money(cat(r[0]["previous"], "dining"))]),
    Case("h07", H, "How much money came in last month?",
         lambda t: [("cash_flow", {"months": 3, "by": None})],
         lambda r, t: [money(month_row(r[0], ym(last_month(t)[0]))["in_cents"])]),
    Case("h08", H, "What was our net cash flow last month, money in minus money out?",
         lambda t: [("cash_flow", {"months": 3, "by": None})],
         lambda r, t: [money(month_row(r[0], ym(last_month(t)[0]))["net_cents"])]),
    Case("h09", H, "What are our investments worth in total?",
         lambda t: [("holdings", {})], lambda r, t: [money(sum(x["value_cents"] for x in r[0]["totals_by_asset_class"]))]),
    Case("h10", H, "Which kind of investment do we hold the most of, and how much is it worth?",
         lambda t: [("holdings", {})], lambda r, t: [money(max(x["value_cents"] for x in r[0]["totals_by_asset_class"]))]),
    Case("h11", H, "At what age can I retire comfortably, according to the saved plan?",
         lambda t: [("plan_result", {})], lambda r, t: [number(r[0]["comfortable_age"])]),
    Case("h12", H, "What's the likely retirement age in our plan?",
         lambda t: [("plan_result", {})], lambda r, t: [number(r[0]["likely_age"])]),
    Case("h13", H, "If we put $500 more a month into savings, when could I retire comfortably?",
         lambda t: [("plan_what_if", {"levers": {"save_more_monthly_cents": 50_000}})],
         lambda r, t: [number(r[0]["comfortable_age"])]),
    Case("h14", H, "How much is in our checking accounts altogether?",
         lambda t: [("book_summary", {})], lambda r, t: [money(type_total(r[0], "checking"))]),
    Case("h15", H, "How much do we have in savings accounts?",
         lambda t: [("book_summary", {})], lambda r, t: [money(type_total(r[0], "savings"))]),
    Case("h16", H, "What's left on the mortgage?",
         lambda t: [("debts", {})],
         lambda r, t: [money(next(d["balance_cents"] for d in r[0]["debts"] if d["kind"] == "mortgage"))]),
    Case("h17", H, "What salary is on file in our facts?",
         lambda t: [("facts", {})], lambda r, t: [money(r[0]["salary_cents"])]),
    Case("h18", H, "What 401(k) contribution rate is set?",
         lambda t: [("facts", {})], lambda r, t: rate(r[0])),
    Case("h19", H, "How many recurring payments go out of our accounts?",
         lambda t: [("recurring", {})], lambda r, t: [number(sum(i["direction"] == "out" for i in r[0]["items"]))]),
    Case("h20", H, "What have we spent on subscriptions over the last year?",
         lambda t: [spend(t - timedelta(days=364), t)], lambda r, t: [money(cat(r[0]["period"], "subscriptions"))]),
    Case("p01", P, "How much came in for Margaret last month, from every source?",
         lambda t: [("money_in_monthly", {"months": 3})],
         lambda r, t: [money(arrived(r[0]["items"], ym(last_month(t)[0])))]),
    Case("p02", P, "How much did Margaret's pension pay last month?",
         lambda t: [("money_in_monthly", {"months": 3})],
         lambda r, t: [money(arrived([i for i in r[0]["items"] if i["source"] == "pension"], ym(last_month(t)[0])))]),
    Case("p03", P, "How much is Margaret's Social Security expected to be each month?",
         lambda t: [("money_in_monthly", {"months": 1})],
         lambda r, t: [money(next(i["expected_cents"] for i in r[0]["items"] if i["source"] == "social_security"))]),
    Case("p04", P, "How many insurance policies does Margaret have?",
         lambda t: [("premiums", {})], lambda r, t: [number(len(r[0]["items"]))]),
    Case("p05", P, "What is the largest insurance premium Margaret pays?",
         lambda t: [("premiums", {})],
         lambda r, t: [money(max(i["premium_cents"] for i in r[0]["items"] if i["premium_cents"]))]),
    Case("p06", P, "What is Margaret's net worth?",
         lambda t: [("book_summary", {})], lambda r, t: [money(r[0]["net_worth_cents"])]),
    Case("p07", P, "How much went out of Margaret's accounts last month?",
         lambda t: [spend(*last_month(t))], lambda r, t: [money(r[0]["period"]["total_out_cents"])]),
    Case("p08", P, "How many flags are open to look into?",
         lambda t: [("flags", {"include_done": False})],
         lambda r, t: [number(sum(f["status"] == "open" for f in r[0]["flags"]))]),
    Case("p09", P, "How many of Margaret's accounts and items still need checking?",
         lambda t: [("inventory", {"kind": None})], lambda r, t: [number(r[0]["needs_checking"])]),
    Case("p10", P, "How much is in Margaret's checking accounts?",
         lambda t: [("book_summary", {})], lambda r, t: [money(type_total(r[0], "checking"))]),
    Case("p11", P, "Under the assisted living scenario, until what year does Margaret's money last?",
         lambda t: [("care_projection", {})],
         lambda r, t: [number(next(s["lasts_until_year"] for s in r[0]["scenarios"] if s["level"] == "assisted_living"))]),
    Case("p12", P, "What Medi-Cal asset limit is Steward using for Margaret?",
         lambda t: [("care_projection", {})], lambda r, t: [money(r[0]["medi_cal_limit_cents"])]),
)

# Used, in order, in place of any household case the demo books have no figure for (Task 16 Step 1's second test).
SPARE: tuple[Case, ...] = (
    Case("s01", H, "How much went out of our accounts last month?",
         lambda t: [("cash_flow", {"months": 3, "by": None})],
         lambda r, t: [money(month_row(r[0], ym(last_month(t)[0]))["out_cents"])]),
    Case("s02", H, "What did we spend on transport last month?",
         lambda t: [spend(*last_month(t))], lambda r, t: [money(cat(r[0]["period"], "transport"))]),
    Case("s03", H, "What was our net worth at the end of last month?",
         lambda t: [("balance_history", {"months": 2, "by_account_type": False})],
         lambda r, t: [money(next(m["net_worth_cents"] for m in r[0]["months"] if m["month"] == ym(last_month(t)[0])))]),
    Case("s04", H, "How many accounts do we have open?",
         lambda t: [("accounts", {"include_closed": False})], lambda r, t: [number(len(r[0]["accounts"]))]),
    Case("s05", H, "How many payments or deposits repeat every month?",
         lambda t: [("recurring", {})], lambda r, t: [number(sum(i["cadence"] == "monthly" for i in r[0]["items"]))]),
)
