"""What Claude saw (spec 5.3): for each result a turn sent, a short title and a plain summary, shown above the exact
JSON. Summaries count what was sent and say what wasn't; they never repeat a value."""
from __future__ import annotations

from datetime import date

from steward.inventory.present import long_date
from steward_boundary import tools as T

PREFIXES = ("Looking at ", "Asking for ", "Trying ")


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


TITLES = {t.name: _cap(next((t.status[len(p):] for p in PREFIXES if t.status.startswith(p)), t.status))
          for t in T.TOOLS}


def _n(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _len(c: dict, key: str) -> int:
    v = c.get(key)
    return len(v) if isinstance(v, list) else 0


def _day(iso: str) -> str:
    return long_date(date.fromisoformat(iso))


def _spending(c: dict) -> str:
    p = c["period"]
    out = (f"{_day(p['start'])} to {_day(p['end'])}: {_n(len(p['categories']), 'category', 'categories')}, each with a "
           f"total and a count")
    return out + (", against the period before" if c.get("previous") else "") + ". No store names."


SUMMARY = {
    "book_summary": lambda c: f"The book's kind, {_n(_len(c, 'people'), 'person', 'people')} as aliases with ages, net "
                              f"worth and totals by account type.",
    "accounts": lambda c: f"{_n(_len(c, 'accounts'), 'account')} by alias, with type, owner alias and balance. No "
                          f"account names or numbers.",
    "balance_history": lambda c: f"Net worth at the end of each of {_n(_len(c, 'months'), 'month')}.",
    "cash_flow": lambda c: f"Money in and out for {_n(_len(c, 'months'), 'month')}"
                           + (", in groups" if any(m.get("groups") for m in c.get("months", [])) else "") + ".",
    "spending_by_category": _spending,
    "recurring": lambda c: f"{_n(_len(c, 'items'), 'repeating payment or deposit', 'repeating payments and deposits')}"
                           f", with payees as aliases.",
    "holdings": lambda c: f"{_n(_len(c, 'holdings'), 'holding')} by symbol or asset class, with totals by asset class.",
    "debts": lambda c: f"{_n(_len(c, 'debts'), 'debt')} with balance, rate and payment.",
    "facts": lambda c: "Salary, contribution rates, state, filing status, home and mortgage figures, and ages.",
    "plan_result": lambda c: "The saved plan's ages, the chance of success by age and its assumptions.",
    "plan_what_if": lambda c: "The plan with some levers changed. Nothing was saved.",
    "plan_lever_impacts": lambda c: f"{_n(_len(c, 'impacts'), 'change')} ranked by how much each moves the plan.",
    "savings_checklist": lambda c: f"{_n(_len(c, 'items'), 'checklist item')} with their status and the numbers behind "
                                   f"them.",
    "inventory": lambda c: f"{_n(_len(c, 'items'), 'item')} with kind, status and amounts. No policy numbers, contacts "
                           f"or notes.",
    "money_in_monthly": lambda c: f"{_n(_len(c, 'items'), 'income item')} with what arrived each month.",
    "premiums": lambda c: f"{_n(_len(c, 'items'), 'policy', 'policies')} with premium, what pays it and the last "
                          f"payment.",
    "flags": lambda c: f"{_n(_len(c, 'flags'), 'flag')} with check, amount and date. No payee names.",
    "care_projection": lambda c: f"{_n(_len(c, 'scenarios'), 'care scenario')} with the years the money lasts, "
                                 f"insurance and the Medi-Cal estimate, and money in and out by month. No names.",
}
ERROR_SUMMARY = {T.DECLINED: "Not sent: you chose Don't send.",
                 T.NEEDS_MANAGER: "Not sent: store names need a manager's OK."}


def summary(name: str, content: dict, is_error: bool, approver: str | None = None) -> str:
    if is_error:
        e = str(content.get("error", ""))
        return ERROR_SUMMARY.get(e, f"Couldn't be looked up: {e}")
    if name == T.MERCHANT:
        n = _len(content, "rows") + _len(content, "payees")
        if n == 0:          # nothing matched, so no card was shown and nobody approved anything (final review, Task 7)
            return "No store rows matched, so there was nothing to approve."
        return f"{_n(n, 'store row')}, approved by {approver or 'a manager'} for this conversation."
    try:
        return SUMMARY[name](content)
    except (KeyError, TypeError, ValueError):
        return "A result from Steward."
