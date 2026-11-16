"""Reading a scanned statement (PDF statements spec P25, "Reading a scanned page"). The vision model gives each page's
values as printed; the NAS parses every one itself: dates by the allowed formats, then P19 once the period is known;
amounts by the statement money reader; the way sets the sign, and unknown takes the printed sign for the statement's
kind (Engineering choice 6). The statement is assembled from its pages: the facts from the first page that has each,
rows in page order. A value that doesn't parse is listed in the import round's words, never dropped. Nothing about a
scan is remembered as a layout, and nothing the model reads back is ever followed."""
from __future__ import annotations

from datetime import date, timedelta

from steward.db.models import INVESTMENT_TYPES, AccountType
from steward.services.statements import dates
from steward.services.statements.extract import mask
from steward.services.statements.holdings import MAX_HOLDINGS, shares_milli
from steward.services.statements.money import parse_amount
from steward.services.statements.rules import MAX_AGE_DAYS, MAX_ROWS, OWED, Reading, Row

AMOUNT_BAD = 'the amount "{value}" isn\'t a dollar amount.'          # the import round's words, after "Page {n}: "
DATE_BAD = 'the date "{value}" isn\'t a date.'                        # plan-owned, in the same shape
OPENING_MISSING = "the opening balance wasn't found."                  # plan-owned, in the same shape: why it's off
CLOSING_MISSING = "the closing balance wasn't found."
OUTSIDE = timedelta(days=7)
DESCRIPTION_MAX = 200


def kind_for(account_type: AccountType | None) -> str:
    if account_type in (AccountType.credit, AccountType.business_credit):
        return "card"
    if account_type in (AccountType.loan, AccountType.mortgage):
        return "loan"
    if account_type in INVESTMENT_TYPES:
        return "investment"
    return "bank"


def _m(value):
    return mask(value) if isinstance(value, str) else value


def mask_answer(answer: dict) -> dict:
    """P14 on every string the model read back, before it is stored (mask keeps dates and amounts, so parsing is
    unchanged)."""
    out = {k: _m(v) for k, v in answer.items() if k not in ("rows", "holdings", "period")}
    p = answer.get("period")
    out["period"] = {k: _m(v) for k, v in p.items()} if isinstance(p, dict) else p
    out["rows"] = [{k: _m(v) for k, v in r.items()} for r in answer.get("rows", [])]
    out["holdings"] = [{k: _m(v) for k, v in h.items()} for h in answer.get("holdings", [])]
    return out


def _signed(way: str, printed: int, kind: str) -> int:
    if way == "in":
        return abs(printed)
    if way == "out":
        return -abs(printed)
    return -printed if kind in OWED else printed


def _first(answers: list[dict], key: str):
    return next((a[key] for a in answers if a.get(key)), None)


def assemble(answers: list[dict], kind: str, today: date) -> tuple[Reading, dict]:
    """answers are [{"n": page, **P25's answer}], in page order. Returns the reading and the facts the stage keeps."""
    r = Reading()
    holdings: list[dict] = []
    total = None
    with_rows = kind in ("bank", "card")          # F7: the other kinds carry no transaction rows
    p = _first(answers, "period")
    r.period = dates.period_dates(f"{p['start']} - {p['end']}", None) if p else None
    if r.period is None or r.period[1] > today or (today - r.period[1]).days > MAX_AGE_DAYS:
        r.period, r.error = None, "no_period"
    else:
        start, end = r.period
        r.last4 = _first(answers, "account_last4")
        r.opening = parse_amount(_first(answers, "opening"))
        r.closing = parse_amount(_first(answers, "closing"))
        # P17: a balance the model didn't read leaves the check with no gap to say; row review says why it is off.
        if with_rows and r.opening is None:
            r.unreadable.append((answers[0]["n"], OPENING_MISSING))
        if with_rows and r.closing is None:
            r.unreadable.append((answers[0]["n"], CLOSING_MISSING))
        for a in answers:
            for row in a["rows"] if with_rows else []:
                amount = parse_amount(row["amount"])
                if amount is None:
                    r.unreadable.append((a["n"], AMOUNT_BAD.format(value=mask(row["amount"])[:40])))
                    continue
                d = dates.row_date(row["date"], None, end)
                if d is None or d < start - OUTSIDE or d > end + OUTSIDE:
                    r.unreadable.append((a["n"], DATE_BAD.format(value=mask(row["date"])[:40])))
                    continue
                r.rows.append(Row(d, mask(" ".join(row["description"].split()))[:DESCRIPTION_MAX],
                                  _signed(row["way"], amount, kind), a["n"], mask(row["section"]) if row["section"] else None))
                if len(r.rows) > MAX_ROWS:
                    r.error = "too_many_rows"
                    break
        for a in answers:
            for x in a.get("holdings", []) if kind in ("investment", "retirement") else []:
                value = parse_amount(x["value"])
                if value is None:
                    r.unreadable.append((a["n"], AMOUNT_BAD.format(value=mask(x["value"])[:40])))
                    continue
                if len(holdings) >= MAX_HOLDINGS:
                    r.error = "too_many_holdings"
                    break
                holdings.append({"symbol": mask(x["symbol"])[:20] if x["symbol"] else None,
                                 "name": mask(x["name"])[:200], "shares_milli": shares_milli(x["shares"]),
                                 "value_cents": value, "cash": False, "state": "read"})
        total = parse_amount(_first(answers, "total"))
    facts = {"kind": kind, "institution": _m(_first(answers, "institution")), "label": None, "model": None,
             "last4": r.last4, "scan": True,
             "period": [r.period[0].isoformat(), r.period[1].isoformat()] if r.period else None,
             "opening_cents": r.opening, "closing_cents": r.closing, "total_cents": total, "holdings": holdings, "opening_label": None, "closing_label": None,
             "sections": [], "unreadable": [{"page": n, "text": t} for n, t in r.unreadable]}
    return r, facts
