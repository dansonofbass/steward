"""Applying a layout (spec P18, P19, P44; the spike's H1-H4): deterministic NAS code over the extracted lines. The
column bands come from the header line (the model never gives a position); sections open at their titles and close
at their total label or the next title; a row is a line with a date in the date band and an amount in a money band,
inside a section that isn't skip; description-only lines just under a row always join it; never-rows are left out;
the sign comes from the debit and credit columns or the section. The layout gives labels only, never a value."""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from steward.services.statements import dates, labels
from steward.services.statements.extract import line_text, mask, norm
from steward.services.statements.money import amounts, parse_amount

NUMERIC = frozenset({"amount", "debit", "credit", "balance", "shares", "price", "value", "cost_basis"})
NEVER = ("minimum payment due", "payment due date", "credit limit", "available credit", "cash advance limit",
         "total fees charged in", "total interest charged in", "year to date", "annual percentage rate")
OWED = frozenset({"card", "loan"})
REACH, PAST, TEXT_LEFT, NEAR = 70.0, 5.0, 5.0, 15.0     # P18's band numbers (Engineering choice 23)
OUTSIDE = timedelta(days=7)
MAX_AGE_DAYS = 3 * 366
MAX_ROWS = 2000


@dataclass(frozen=True)
class Band:
    field: str
    x0: float
    x1: float


@dataclass
class Row:
    date: date
    description: str
    amount_cents: int
    page: int
    section: str | None


@dataclass
class Reading:
    period: tuple[date, date] | None = None
    last4: str | None = None
    opening: int | None = None
    closing: int | None = None
    rows: list[Row] = field(default_factory=list)
    unreadable: list[tuple[int, str]] = field(default_factory=list)      # (page, the line, masked)
    sums: dict[str, int] = field(default_factory=dict)                   # each section's rows, as Steward stores them
    totals: dict[str, int] = field(default_factory=dict)                 # each section's printed total, likewise
    error: str | None = None                                             # no_period | no_header | too_many_rows


def _same(cell: str, head: str) -> bool:
    return bool(cell) and bool(head) and (cell == head or cell.startswith(head + " ") or head.startswith(cell + " "))


def header_cells(columns: list[dict], line: dict) -> list[dict] | None:
    """The header line's cells, one per column, left to right; None when this line isn't the header line. A header
    printed on two lines is found by its top line (H1)."""
    cells, found, start = line["cells"], [], 0
    for col in columns:
        head = norm(col["header"])
        hit = next((k for k in range(start, len(cells)) if _same(norm(cells[k]["text"]), head)), None)
        if hit is None:
            return None
        found.append(cells[hit])
        start = hit + 1
    return found


def bands(columns: list[dict], found: list[dict], width: float) -> list[Band]:
    """H4: a number reaches up to 70 pt left of its header (amounts are right-aligned), never closer than 5 pt past the
    left neighbour's header, and ends 5 pt right of its header; a date or text column runs from 5 pt left of its
    header to the next column's band."""
    out: list[list] = []
    for k, (col, c) in enumerate(zip(columns, found)):
        left = float(found[k - 1]["x1"]) if k else 0.0
        if col["field"] in NUMERIC:
            out.append([col["field"], max(float(c["x0"]) - REACH, left + PAST), float(c["x1"]) + PAST])
        else:
            out.append([col["field"], max(0.0, float(c["x0"]) - TEXT_LEFT), None])
    for k, b in enumerate(out):
        nxt = out[k + 1][1] - 1 if k + 1 < len(out) else float(width)
        b[2] = nxt if b[2] is None else min(b[2], nxt)
    return [Band(f, x0, x1) for f, x0, x1 in out]


def assign(cells: list[dict], bs: list[Band]) -> dict[str, list[str]]:
    """Each cell to the band it overlaps most, else the nearest band within 15 pt, else nowhere."""
    out: dict[str, list[str]] = {}
    for c in cells:
        best, score = None, 0.0
        for b in bs:
            ov = min(float(c["x1"]), b.x1) - max(float(c["x0"]), b.x0)
            if ov > score:
                best, score = b, ov
        if best is None and bs:
            gap, near = min(((max(b.x0 - float(c["x1"]), float(c["x0"]) - b.x1), b) for b in bs), key=lambda t: t[0])
            best = near if gap <= NEAR else None
        if best is not None:
            out.setdefault(best.field, []).append(c["text"])
    return out


def _starts(text: str, phrase: str) -> bool:
    """Steward's own never-row phrases (NEVER), normalized at the line's start. A layout's labels go through labels."""
    n = norm(phrase)
    return bool(n) and (text + " ").startswith(n + " ")


def _fact_line(lines: list[dict], label: str) -> int | None:
    return labels.find(label, lines)


def _after(line: dict, label: str) -> str:
    return labels.after(label, line)


def _opens(line: dict, title: str) -> bool:
    """A section title or total label: it starts the line, whole (as validation checks)."""
    return labels.starts(title, line_text(line))


def _skips(line: dict, skip: list[str]) -> bool:
    """A skip label: it starts the line or fills one of its cells (as validation checks)."""
    return any(labels.opens(k, line) for k in skip)


def fact_amount(lines: list[dict], label: str) -> int | None:
    """P18: the first amount after the label on its line, else the first on the next line."""
    i = _fact_line(lines, label)
    if i is None:
        return None
    got = amounts(_after(lines[i], label))
    if got:
        return got[0]
    nxt = amounts(line_text(lines[i + 1])) if i + 1 < len(lines) else []
    return nxt[0] if nxt else None


def _period(lines: list[dict], layout: dict) -> tuple[date, date] | None:
    label, hint = layout["period"]["label"], layout["period"]["date_format"]
    i = _fact_line(lines, label)
    if i is None:
        return None
    for text in (_after(lines[i], label), line_text(lines[i + 1]) if i + 1 < len(lines) else ""):
        got = dates.period_dates(text, hint)
        if got:
            return got
    return None


def _last4(lines: list[dict], label: str) -> str | None:
    i = _fact_line(lines, label)
    if i is None:
        return None
    found = re.findall(r"\d{4}(?!\d)", _after(lines[i], label))
    return found[0] if found else None


def _marker_lines(every: list[tuple[int, dict]], marker: str | None) -> list[int]:
    if not marker:
        return []
    return [i for i, (_, ln) in enumerate(every) if _opens(ln, marker)]


def part_count(pages: list[dict], marker: str | None) -> int:
    every = [(p["n"], ln) for p in pages for ln in p["lines"]]
    return max(1, len(_marker_lines(every, marker)))


def _segment(every: list[tuple[int, dict]], marker: str | None, part: int) -> list[tuple[int, dict]]:
    """P44: a combined statement's part runs from its marker line to the next."""
    idx = _marker_lines(every, marker)
    if not idx:
        return every if part == 0 else []
    end = idx[part + 1] if part + 1 < len(idx) else len(every)
    return every[idx[part]:end] if part < len(idx) else []


def _line_height(lines: list[dict]) -> float:
    gaps = sorted(b["y"] - a["y"] for a, b in zip(lines, lines[1:]) if b["y"] > a["y"])
    return statistics.median(gaps) if gaps else 12.0


def _stored(way: str, printed: int, owed: bool) -> int:
    if way == "in":
        return abs(printed)
    if way == "out":
        return -abs(printed)
    return -printed if owed else printed


def _money(got: dict[str, list[str]], fields: set[str], way: str | None, owed: bool) -> int | None:
    if "amount" in fields:
        v = parse_amount(" ".join(got["amount"])) if got.get("amount") else None
        return None if v is None else (v if way is None else _stored(way, v, owed))
    deb = parse_amount(" ".join(got["debit"])) if got.get("debit") else None
    cre = parse_amount(" ".join(got["credit"])) if got.get("credit") else None
    if deb:
        return -abs(deb)
    if cre:
        return abs(cre)
    return None


def apply(layout: dict, pages: list[dict], today: date, part: int = 0) -> Reading:
    table = layout["table"]
    cols, owed = table["columns"], layout["kind"] in OWED
    fields = {c["field"] for c in cols}
    date_field = "post_date" if "post_date" in fields else "date"
    every = [(p["n"], ln) for p in pages for ln in p["lines"]]
    r = Reading()
    r.period = _period([ln for _, ln in every], layout)
    if r.period is None or r.period[1] > today or (today - r.period[1]).days > MAX_AGE_DAYS:
        r.period, r.error = None, "no_period"
        return r
    start, end = r.period
    marker = layout.get("account_marker")
    seg = _segment(every, marker, part)
    seg_lines = [ln for _, ln in seg]
    r.last4 = _last4(seg_lines, marker) if marker else _last4([ln for _, ln in every], layout["account_label"])
    r.opening = fact_amount(seg_lines, layout["opening"]["label"])
    r.closing = fact_amount(seg_lines, layout["closing"]["label"])
    page_bands: dict[int, list[Band]] = {}
    heads: set[int] = set()
    last: list[Band] | None = None
    for p in pages:
        for ln in p["lines"]:
            found = header_cells(cols, ln)
            if found is not None:
                heads.add(id(ln))
                if p["n"] not in page_bands:
                    page_bands[p["n"]] = bands(cols, found, p["width"])
        last = page_bands.get(p["n"], last)
        if last is not None:
            page_bands[p["n"]] = last
    if not page_bands:
        r.error = "no_header"
        return r
    secs = table["sections"]
    titles = [(s["title"], s) for s in secs]
    totals = [(s["total_label"], s) for s in secs if s.get("total_label")]
    skip = list(table.get("skip", []))
    facts = (layout["opening"]["label"], layout["closing"]["label"])
    heights = {p["n"]: _line_height(p["lines"]) for p in pages}
    cur: dict | None = None
    page_now, last_y = None, None
    for n, ln in seg:
        if n != page_now:
            page_now, last_y = n, None
        bs = page_bands.get(n)
        if bs is None or id(ln) in heads:
            last_y = None
            continue
        t = norm(line_text(ln))
        hit = next((s for label, s in totals if _opens(ln, label)), None)
        if hit is not None:
            got = amounts(_after(ln, hit["total_label"]))
            if got and hit["way"] != "skip":
                r.totals[hit["title"]] = _stored(hit["way"], got[0], owed)
            cur = None if cur is hit else cur
            last_y = None
            continue
        opened = next((s for title, s in titles if _opens(ln, title)), None)
        if opened is not None:
            cur, last_y = opened, None
            continue
        if any(_starts(t, k) for k in NEVER) or _skips(ln, skip) or any(_opens(ln, k) for k in facts):
            last_y = None
            continue
        got = assign(ln["cells"], bs)
        dcell = " ".join(got.get(date_field, []))
        raw = _money(got, fields, None, owed)
        d = dates.row_date(dcell, table["date_format"], end) if dcell else None
        reading = cur is not None and cur["way"] != "skip"
        if d is not None and raw is not None:
            if not reading:
                last_y = None
                continue
            if d < start - OUTSIDE or d > end + OUTSIDE:
                r.unreadable.append((n, mask(line_text(ln))))
                last_y = None
                continue
            amount = _money(got, fields, cur["way"], owed)
            r.rows.append(Row(d, mask(" ".join(got.get("description", []))), amount, n, cur["title"]))
            r.sums[cur["title"]] = r.sums.get(cur["title"], 0) + amount
            if len(r.rows) > MAX_ROWS:
                r.error = "too_many_rows"
                return r
            last_y = ln["y"]
            continue
        if (d is None and raw is None and last_y is not None and r.rows and got.get("description")
                and set(got) <= {"description"} and ln["y"] - last_y <= 1.5 * heights[n]):
            r.rows[-1].description = mask(r.rows[-1].description + " " + " ".join(got["description"]))
            last_y = ln["y"]
            continue
        if reading and dcell and raw is not None and d is None:
            r.unreadable.append((n, mask(line_text(ln))))
        last_y = None
    return r
