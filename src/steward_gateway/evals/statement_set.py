"""The synthetic statement set (PDF statements spec, Testing; P47, P53). Made-up banks' statements, generated as PDFs
with reportlab (invariant=1, so the bytes are the same every run) and never committed: the NAS's tests and the
gateway's eval (steward-gateway eval statements) build them in memory. Each comes with its truth: the rows as Steward
stores them (money out negative), the facts, and the layout a perfect proposal gives. Made-up institutions and
merchants; the person is "Jane Doe" at a made-up address; account numbers are 0000-style. Seeded from the spike's
gen.py (tmp/pdfspike). reportlab is a dev dependency: the gateway has it through uv sync, and the NAS image never
imports this module. PR 2 adds the scanned renders, PR 3 layouts 9-13."""
from __future__ import annotations

import io
import random
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

PAGE_W, PAGE_H = 612.0, 792.0
LINE, WRAP, GAP = 13.0, 10.0, 24.0       # a row, a wrapped line under it, the space before a sub-heading
TOP_TABLE, BOTTOM = 250.0, 730.0
MERCHANTS = ("MAPLEWOOD GROCERY #214", "BLUE HERON COFFEE", "SUNDIAL FUEL STOP 0418", "GLIMMER STREAMING",
             "PINEBROOK PHARMACY", "TALLGRASS PIZZA CO", "RIVERBEND HARDWARE", "COPPERLEAF CINEMA", "MOSSROCK GYM",
             "ORCHARD LANE MARKET", "FERNHILL VET CLINIC", "NORTHWIND TRANSIT", "KESTREL OUTFITTERS",
             "QUILLFEATHER BOOKS", "DUNMORE DELI", "HOLLOWAY AUTO SPA", "BRAMBLE AND BLOOM FLORIST",
             "STARLING ELECTRIC")


@dataclass(frozen=True)
class Col:
    head: tuple[str, ...]          # as printed: one line, or two
    field: str
    x: float                       # the left edge; the right edge for a number
    right: bool = False


@dataclass(frozen=True)
class Item:
    day: int                       # days after the period's first day
    text: tuple[str, ...]          # the description; more than one line wraps
    cents: int                     # as Steward stores it: money out negative
    ref: str = ""                  # a check number, in an ignore column


@dataclass(frozen=True)
class Sec:
    title: str
    way: str
    items: tuple[Item, ...]
    total: str | None = None
    headings: tuple[tuple[int, str], ...] = ()     # (item index, a sub-heading drawn GAP above that item)


@dataclass(frozen=True)
class Part:
    account: str                   # 0000-style, as printed
    name: str
    opening: int                   # cents as printed (on a card, owed is positive)
    sections: tuple[Sec, ...]


@dataclass(frozen=True)
class Spec:
    sid: str
    kind: str
    institution: str
    account_label: str
    period_label: str
    period_fmt: str
    period_join: str
    end: date
    days: int
    opening_label: str
    closing_label: str
    date_fmt: str
    negative: str
    cols: tuple[Col, ...]
    parts: tuple[Part, ...]
    marker: str | None = None      # P44: the label that starts each account's part
    in_printed: str = "abs"        # how an "in" section prints: abs | negative
    out_printed: str = "abs"
    balance_on: str = ""           # after a balance label: " on {B} {d}, {Y}", " {m}/{d}"
    extra: tuple[str, ...] = ()    # lines beside the summary that are never rows
    after: tuple[str, ...] = ()    # lines after the table that are never rows (YTD totals)
    daily: bool = False            # a "DAILY ENDING BALANCE" table after the transactions (a skip section)
    skip: tuple[str, ...] = ()


@dataclass(frozen=True)
class Truth:
    sid: str
    kind: str
    institution: str
    period: tuple[date, date]
    last4: str
    opening_cents: int
    closing_cents: int
    rows: tuple[dict, ...]         # {"date", "description", "amount_cents", "section", "page"}
    layout: dict
    pages: int
    parts: tuple["Truth", ...] = ()
    misprint_cents: int = 0
    sections: tuple[dict, ...] = field(default=())   # {"title", "total_cents"} as Steward stores them
    holdings: tuple[dict, ...] = ()                  # {"symbol", "name", "shares_milli", "value_cents", "cash"}
    total_cents: int | None = None                   # a holdings statement's printed total


def _money(cents: int, style: str, dollar: bool = False) -> str:
    a = f"{abs(cents) / 100:,.2f}"
    a = "$" + a if dollar else a
    if cents >= 0:
        return a
    return {"minus": "-" + a, "parens": f"({a})", "trailing_minus": a + "-", "cr": a + " CR"}[style]


def _spend(seed: int, n: int, days: int, lo: int = 300, hi: int = 18000) -> tuple[Item, ...]:
    r = random.Random(seed)
    items = [Item(r.randrange(days), (r.choice(MERCHANTS),), -r.randrange(lo, hi)) for _ in range(n)]
    return tuple(sorted(items, key=lambda i: i.day))


def _mask(text: str) -> str:
    from steward_pdf.lines import mask           # the NAS's own P14 rule
    return mask(" ".join(text.split()))


class _Doc:
    def __init__(self, c, spec: Spec):
        self.c, self.s, self.page, self.y, self.bal = c, spec, 1, 0.0, 0
        self.desc = next((x for x in spec.cols if x.field in ("description", "name")), spec.cols[0])
        self.money = next((x for x in spec.cols if x.field in ("amount", "debit")), spec.cols[-1])

    def t(self, x: float, y: float, s: str, size: float = 9, bold: bool = False, right: bool = False) -> None:
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        (self.c.drawRightString if right else self.c.drawString)(x, PAGE_H - y, s)

    def header(self) -> None:
        for col in self.s.cols:
            for k, line in enumerate(col.head):
                self.t(col.x, self.y + 9 * k, line, 8 if len(col.head) > 1 else 9, True, col.right)
        self.y += 9 * (max(len(c.head) for c in self.s.cols) - 1)

    def line(self, h: float = LINE, keep: float = 0.0) -> None:
        """Moves down h, turning the page (header repeated) when h plus what must stay with it won't fit."""
        if self.y + h + keep > BOTTOM:
            self.t(560, 770, f"Page {self.page}", 8, right=True)
            self.c.showPage()
            self.page += 1
            self.y = 60.0
            self.header()
        self.y += h

    def printed(self, way: str, cents: int, misprint: int) -> int:
        s = self.s
        if way == "in":
            p = -abs(cents) if s.in_printed == "negative" else abs(cents)
        elif way == "out":
            p = -abs(cents) if s.out_printed == "negative" else abs(cents)
        else:
            p = -cents if s.kind == "card" else cents
        return p + misprint if p >= 0 else p - misprint

    def balance_label(self, label: str, day: date) -> str:
        return label + self.s.balance_on.format(m=day.month, d=day.day, B=day.strftime("%B"), Y=day.year)

    def summary(self, y: float, label: str, cents: int) -> None:
        self.t(40, y, label)
        self.t(300, y, _money(cents, "minus", True), right=True)

    def row(self, sec: Sec, it: Item, start: date, misprint: int) -> date:
        s, day = self.s, start + timedelta(days=it.day)
        dated = day
        for col in s.cols:
            if col.field == "date":
                self.t(col.x, self.y, day.strftime(s.date_fmt), right=col.right)
            elif col.field == "post_date":
                dated = day + timedelta(days=1)
                self.t(col.x, self.y, dated.strftime(s.date_fmt), right=col.right)
            elif col.field == "description":
                self.t(col.x, self.y, it.text[0])
            elif col.field == "ignore" and it.ref:
                self.t(col.x, self.y, it.ref, right=col.right)
            elif col.field == "amount":
                self.t(col.x, self.y, _money(self.printed(sec.way, it.cents, misprint), s.negative), right=True)
            elif col.field == "debit" and it.cents < 0:
                self.t(col.x, self.y, _money(-it.cents + misprint, "minus"), right=True)
            elif col.field == "credit" and it.cents > 0:
                self.t(col.x, self.y, _money(it.cents + misprint, "minus"), right=True)
            elif col.field == "balance":
                self.bal += it.cents
                self.t(col.x, self.y, _money(self.bal, s.negative), right=True)
        return dated

    def part(self, part: Part, start: date, end: date, misprint: int, combined: bool) -> tuple[list[dict], int, list[dict]]:
        s, owed = self.s, self.s.kind == "card"
        moved = sum(it.cents for sec in part.sections for it in sec.items)
        closing = part.opening - moved if owed else part.opening + moved
        self.bal = part.opening
        if combined:
            self.line(GAP, keep=4 * LINE)
            self.t(40, self.y, f"{s.marker} {part.account} {part.name}", 10, True)
            self.line()
            self.summary(self.y, self.balance_label(s.opening_label, start), part.opening)
            self.line(LINE + 6)
            self.header()
        else:
            self.summary(126, self.balance_label(s.opening_label, start), part.opening)
            y = 138
            for sec in part.sections:
                if sec.way in ("in", "out"):
                    self.summary(y, sec.title.title(), sum(self.printed(sec.way, it.cents, 0) for it in sec.items))
                    y += 12
            self.summary(y, self.balance_label(s.closing_label, end), closing)
            self.y = TOP_TABLE
            self.header()
        rows, totals, slipped = [], [], misprint
        for sec in part.sections:
            self.line(18, keep=LINE)
            self.t(40, self.y, sec.title, 10, True)
            heads = dict(sec.headings)
            for k, it in enumerate(sec.items):
                if k in heads:
                    self.line(GAP, keep=LINE)
                    self.t(self.desc.x, self.y, heads[k], 9, True)
                self.line(LINE, keep=WRAP * (len(it.text) - 1))
                page = self.page
                dated = self.row(sec, it, start, slipped if sec.way != "in" else 0)
                if sec.way != "in":
                    slipped = 0                                # the misprint goes on the first row outside an in section
                for more in it.text[1:]:
                    self.line(WRAP)
                    self.t(self.desc.x, self.y, more)
                rows.append({"date": dated.isoformat(), "description": _mask(" ".join(it.text)),
                             "amount_cents": it.cents, "section": sec.title, "page": page})
            if sec.total:
                total = sum(self.printed(sec.way, it.cents, 0) for it in sec.items)
                self.line()
                self.t(self.desc.x, self.y, sec.total, bold=True)
                self.t(self.money.x, self.y, _money(total, s.negative, True), bold=True, right=True)
                totals.append({"title": sec.title, "total_cents": sum(it.cents for it in sec.items)})
        if combined:
            self.line()
            self.summary(self.y, self.balance_label(s.closing_label, end), closing)
        return rows, closing, totals

    def daily(self, part: Part, start: date) -> None:
        s = self.s
        self.line(18, keep=LINE)
        self.t(40, self.y, "DAILY ENDING BALANCE", 10, True)
        bal = part.opening
        by_day: dict[int, int] = {}
        for sec in part.sections:
            for it in sec.items:
                by_day[it.day] = by_day.get(it.day, 0) + it.cents
        for d in sorted(by_day):
            bal += by_day[d]
            self.line()
            self.t(40, self.y, (start + timedelta(days=d)).strftime(s.date_fmt))
            self.t(self.money.x, self.y, _money(bal, s.negative), right=True)


def _layout(s: Spec) -> dict:
    secs = [{"title": x.title, "way": x.way, "total_label": x.total} for x in s.parts[0].sections]
    if s.daily:
        secs.append({"title": "DAILY ENDING BALANCE", "way": "skip", "total_label": None})
    return {"kind": s.kind, "institution": s.institution, "account_label": s.account_label, "account_marker": s.marker,
            "period": {"label": s.period_label, "date_format": s.period_fmt},
            "opening": {"label": s.opening_label}, "closing": {"label": s.closing_label},
            "table": {"columns": [{"header": c.head[0], "field": c.field} for c in s.cols], "date_format": s.date_fmt,
                      "negative": s.negative, "sections": secs, "skip": list(s.skip)},
            "holdings": None}


def _draw(s: Spec, end: date, misprint: int = 0, encrypt=None) -> tuple[bytes, Truth]:
    from reportlab.pdfgen import canvas
    start = end - timedelta(days=s.days - 1)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H), invariant=1, encrypt=encrypt)
    d = _Doc(c, s)
    d.t(40, 40, s.institution, 16, True)
    for k, a in enumerate(("Jane Doe", "1428 Maple Hollow Rd", "Springfield, ZZ 00000")):
        d.t(40, 62 + 11 * k, a)
    combined = s.marker is not None
    if not combined:
        d.t(340, 62, s.account_label)
        d.t(440, 62, s.parts[0].account)
    d.t(340, 73, s.period_label)
    d.t(440, 73, start.strftime(s.period_fmt) + s.period_join + end.strftime(s.period_fmt))
    for k, text in enumerate(s.extra):
        d.t(340, 126 + 12 * k, text)
    d.y = 100.0
    truths = []
    for part in s.parts:
        rows, closing, totals = d.part(part, start, end, misprint if not truths else 0, combined)
        truths.append(Truth(s.sid, s.kind, s.institution, (start, end), part.account[-4:], part.opening, closing,
                            tuple(rows), _layout(s), 0, sections=tuple(totals)))
    if s.daily:
        d.daily(s.parts[0], start)
    for k, text in enumerate(s.after):
        d.line(28 if k == 0 else LINE)
        d.t(40, d.y, text)
    d.t(560, 770, f"Page {d.page}", 8, right=True)
    c.showPage()
    c.save()
    pages = d.page
    truths = [replace(t, pages=pages) for t in truths]
    if len(truths) == 1:
        return buf.getvalue(), replace(truths[0], misprint_cents=misprint)
    first = truths[0]
    return buf.getvalue(), replace(first, last4="", rows=tuple(r for t in truths for r in t.rows),
                                   parts=tuple(truths), misprint_cents=misprint)


@dataclass(frozen=True)
class Holding:
    symbol: str | None
    name: str
    shares: str | None             # as printed: "412.118"
    price_cents: int | None
    value_cents: int
    cash: bool = False


@dataclass(frozen=True)
class HSpec:
    """An investment, retirement or loan statement: summary balances, and for investments a holdings table."""
    sid: str
    kind: str                      # investment | retirement | loan
    institution: str
    account_label: str
    account_text: str
    period_label: str
    period_fmt: str
    period_join: str
    end: date
    days: int
    opening_label: str
    closing_label: str
    opening_cents: int
    closing_cents: int = 0         # a loan's principal; an investment's is its printed total
    title: str = "Your Holdings"
    cols: tuple[Col, ...] = ()
    holdings: tuple[Holding, ...] = ()
    total_label: str | None = None
    rounding: int = 0              # the printed total minus the holdings' sum (rounding, within $1)
    cash_labels: tuple[str, ...] = ()
    after_title: str | None = None
    after: tuple[tuple[str, int], ...] = ()
    extra: tuple[str, ...] = ()


def _shares_milli(text: str | None) -> int:
    if not text:
        return 0
    from decimal import ROUND_HALF_UP, Decimal
    return int((Decimal(text.replace(",", "")) * 1000).to_integral_value(rounding=ROUND_HALF_UP))


def _draw_holdings(s: HSpec, end: date, slip: int = 0) -> tuple[bytes, Truth]:
    from reportlab.pdfgen import canvas
    start = end - timedelta(days=s.days - 1)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H), invariant=1)
    d = _Doc(c, Spec(s.sid, s.kind, s.institution, s.account_label, s.period_label, s.period_fmt, s.period_join, end,
                     s.days, s.opening_label, s.closing_label, "%m/%d", "minus", s.cols or (Col(("x",), "description", 40),),
                     ()))
    d.t(40, 40, s.institution, 16, True)
    for k, a in enumerate(("Jane Doe", "1428 Maple Hollow Rd", "Springfield, ZZ 00000")):
        d.t(40, 62 + 11 * k, a)
    d.t(340, 62, s.account_label)
    d.t(440, 62, s.account_text)
    d.t(340, 73, s.period_label)
    d.t(440, 73, start.strftime(s.period_fmt) + s.period_join + end.strftime(s.period_fmt))
    held = sum(h.value_cents for h in s.holdings)
    total = held + s.rounding + slip if s.holdings else s.closing_cents
    d.summary(126, s.opening_label, s.opening_cents)
    d.summary(138, s.closing_label, total)
    for k, text in enumerate(s.extra):
        d.t(340, 126 + 12 * k, text)
    if s.holdings:
        d.t(40, 200, s.title, 11, True)
        d.y = 217.0
        d.header()
        value_col = next(x for x in s.cols if x.field == "value")
        for h in s.holdings:
            d.line(14)
            for col in s.cols:
                text = {"symbol": h.symbol, "name": h.name, "shares": h.shares,
                        "price": f"${h.price_cents / 100:,.2f}" if h.price_cents is not None else None,
                        "value": _money(h.value_cents, "minus", True)}.get(col.field)
                if text:
                    d.t(col.x, d.y, text, right=col.right)
        d.line(18)
        d.t(40, d.y, s.total_label, bold=True)
        d.t(value_col.x, d.y, _money(total, "minus", True), bold=True, right=True)
        if s.after_title:
            d.line(30)
            d.t(40, d.y, s.after_title, 11, True)
            for label, cents in s.after:
                d.line(13)
                d.t(40, d.y, label)
                d.t(value_col.x, d.y, _money(cents, "minus", True), right=True)
    d.t(560, 770, f"Page {d.page}", 8, right=True)
    c.showPage()
    c.save()
    layout = {"kind": s.kind, "institution": s.institution, "account_label": s.account_label, "account_marker": None,
              "period": {"label": s.period_label, "date_format": s.period_fmt},
              "opening": {"label": s.opening_label}, "closing": {"label": s.closing_label}, "table": None,
              "holdings": {"columns": [{"header": x.head[0], "field": x.field} for x in s.cols], "total_label": s.total_label,
                           "cash_labels": list(s.cash_labels), "ending": {"label": s.closing_label}} if s.holdings else None}
    holdings = tuple({"symbol": h.symbol, "name": _mask(h.name), "shares_milli": _shares_milli(h.shares),
                      "value_cents": h.value_cents, "cash": h.cash} for h in s.holdings)
    return buf.getvalue(), Truth(s.sid, s.kind, s.institution, (start, end), s.account_text[-4:], s.opening_cents, total,
                                 (), layout, d.page, holdings=holdings, total_cents=total if s.holdings else None)


TODAY_END = date(2026, 3, 31)
SPECS: dict[str, Spec] = {
    "chase_checking": Spec(
        "chase_checking", "bank", "Lakeshore National Bank", "Account Number", "Statement Period", "%B %d, %Y",
        " through ", TODAY_END, 31, "Beginning Balance", "Ending Balance", "%m/%d", "minus",
        (Col(("DATE",), "date", 40), Col(("DESCRIPTION",), "description", 100), Col(("AMOUNT",), "amount", 560, True)),
        (Part("000001234567890", "Total Checking", 245018, (
            Sec("DEPOSITS AND ADDITIONS", "in", (
                Item(0, ("PAYROLL DEPOSIT ACME WIDGETS INC",), 218433), Item(7, ("ZELLE FROM SAM ROE",), 12000),
                Item(14, ("PAYROLL DEPOSIT ACME WIDGETS INC",), 218433), Item(25, ("REFUND KESTREL OUTFITTERS",), 4299)),
                "Total Deposits and Additions"),
            Sec("ELECTRONIC WITHDRAWALS", "out", (
                Item(3, ("ORIG CO NAME:STARLING ELECTRIC", "ORIG ID:9001234567 DESC DATE:030426 CO ENTRY"), -11267),
                Item(9, ("ONLINE TRANSFER TO SAV XXXXX4471",), -50000), *_spend(11, 12, 31)),
                "Total Electronic Withdrawals"),
            Sec("CHECKS PAID", "out", (Item(10, ("CHECK 1043",), -20000), Item(21, ("CHECK 1044",), -8500)),
                "Total Checks Paid"))),),
        daily=True),
    "boa_checking": Spec(
        "boa_checking", "bank", "Harborview Bank", "Account number:", "Statement period", "%B %d, %Y", " to ",
        TODAY_END, 31, "Beginning balance", "Ending balance", "%m/%d/%y", "trailing_minus",
        (Col(("Date",), "date", 40), Col(("Description",), "description", 100), Col(("Amount",), "amount", 560, True)),
        (Part("0000 1111 2222 3456", "Advantage Plus", 532077, (
            Sec("Deposits and other additions", "in", (
                Item(1, ("NORTHWIND PAYROLL DES:PAYROLL",), 241800), Item(15, ("NORTHWIND PAYROLL DES:PAYROLL",), 241800),
                Item(20, ("MOBILE DEPOSIT",), 6000)), "Total deposits and other additions"),
            Sec("Withdrawals and other subtractions", "out", _spend(22, 16, 31), "Total withdrawals and other subtractions")
        )),),
        out_printed="negative", balance_on=" on {B} {d}, {Y}"),
    "wells_checking": Spec(
        "wells_checking", "bank", "Prairie Trust Bank", "Account number", "Statement period", "%m/%d/%Y", " - ",
        TODAY_END, 31, "Beginning balance on", "Ending balance on", "%m/%d", "minus",
        (Col(("Date",), "date", 40), Col(("Check", "Number"), "ignore", 72), Col(("Description",), "description", 110),
         Col(("Deposits/", "Credits"), "credit", 440, True), Col(("Withdrawals/", "Debits"), "debit", 510, True),
         Col(("Ending daily", "balance"), "balance", 580, True)),
        (Part("0000012345678", "Everyday Checking", 310402, (
            Sec("Transaction history", "signed", (
                Item(1, ("DEPOSIT PAYROLL", "BRIGHTWATER MFG DIRECT DEP"), 187540),
                Item(3, ("ACH DEBIT PRAIRIE ENERGY COOP", "WEB ID 9001234567"), -13422),
                Item(5, ("CHECK",), -8500, "2207"), Item(8, ("POS PURCHASE MAPLEWOOD GROCERY", "#214 SPRINGFIELD ZZ"), -6731),
                Item(12, ("TRANSFER FROM SHARE SAVINGS",), 25000), Item(16, ("DEPOSIT PAYROLL", "BRIGHTWATER MFG DIRECT DEP"), 187540),
                Item(21, ("CHECK",), -120000, "2208"), Item(24, ("MOBILE DEPOSIT",), 6000),
                Item(28, ("POS PURCHASE ORCHARD LANE", "MARKET SPRINGFIELD"), -5219))),)),),
        balance_on=" {m}/{d}"),
    "cu_savings": Spec(
        "cu_savings", "bank", "Riverbend Federal Credit Union", "Share Account", "Statement Period", "%m/%d/%Y", " - ",
        TODAY_END, 31, "Beginning Balance", "Ending Balance", "%b %d", "minus",
        (Col(("Date",), "date", 40), Col(("Description",), "description", 100), Col(("Amount",), "amount", 560, True)),
        (Part("0000000011", "Primary Savings", 812040, (Sec("Transactions", "signed", (
            Item(2, ("DEPOSIT TRANSFER FROM CHECKING",), 25000), Item(17, ("WITHDRAWAL TO CHECKING",), -10000),
            Item(30, ("DIVIDEND EARNED",), 312))),)),
         Part("0000000029", "Holiday Club", 120000, (Sec("Transactions", "signed", (
             Item(14, ("DEPOSIT",), 5000), Item(20, ("WITHDRAWAL",), -2000), Item(30, ("DIVIDEND EARNED",), 41))),))),
        marker="Share Account"),
    "chase_card": Spec(
        "chase_card", "card", "Summit Card Services", "Account Number", "Opening/Closing Date", "%m/%d/%y", " - ",
        TODAY_END, 31, "Previous Balance", "New Balance", "%m/%d", "minus",
        (Col(("Date of", "Transaction"), "date", 40), Col(("Merchant Name or Transaction Description",), "description", 100),
         Col(("$ Amount",), "amount", 560, True)),
        (Part("XXXX XXXX XXXX 4417", "Summit Rewards", 184207, (
            Sec("PAYMENTS AND OTHER CREDITS", "in", (Item(10, ("AUTOMATIC PAYMENT - THANK YOU",), 120410),
                                                     Item(22, ("RETURN QUILLFEATHER BOOKS",), 2499))),
            Sec("PURCHASE", "out", _spend(5, 20, 29)),
            Sec("FEES CHARGED", "out", (Item(29, ("ANNUAL MEMBERSHIP FEE",), -9500),)),
            Sec("INTEREST CHARGED", "out", (Item(30, ("PURCHASE INTEREST CHARGE",), -3118),)))),),
        in_printed="negative", extra=("Payment Due Date 04/25/26", "Minimum Payment Due $40.00", "Credit Limit $8,000"),
        after=("2026 Totals Year-to-Date", "Total fees charged in 2026 $95.00", "Total interest charged in 2026 $31.18")),
    "amex_card": Spec(
        "amex_card", "card", "Bluewater Express", "Account Ending", "Billing Period", "%m/%d/%y", " to ",
        date(2026, 1, 17), 31, "Previous Balance", "New Balance", "%m/%d", "cr",
        (Col(("Date",), "date", 40), Col(("Description",), "description", 100), Col(("Amount",), "amount", 560, True)),
        (Part("0-00000-01004", "Platinum", 184207, (
            Sec("Payments and Credits", "signed", (Item(8, ("PAYMENT RECEIVED - THANK YOU",), 184207),)),
            Sec("New Charges", "signed", (
                Item(1, ("DUNMORE DELI",), -1420), Item(2, ("KESTREL OUTFITTERS",), -18999),
                Item(6, ("QUILLFEATHER BOOKS",), -2499), Item(13, ("COPPERLEAF CINEMA",), -3800),
                Item(4, ("BRAMBLE AND BLOOM FLORIST",), -6500), Item(9, ("SUNDIAL FUEL STOP",), -5233),
                Item(18, ("KESTREL OUTFITTERS RETURN",), 2500), Item(22, ("ORCHARD LANE MARKET",), -7745),
                Item(28, ("BLUE HERON COFFEE",), -825)),
                headings=((0, "Card Member JANE DOE"), (4, "Card Member SAM ROE"))))),),
        extra=("Payment Due Date 02/11/26",)),
    "citi_card": Spec(
        "citi_card", "card", "Granite Card Bank", "Account number ending in", "Billing Period:", "%m/%d/%y", "-",
        TODAY_END, 31, "Previous balance", "New balance", "%m/%d", "minus",
        (Col(("Sale Date",), "date", 40), Col(("Post Date",), "post_date", 90), Col(("Description",), "description", 140),
         Col(("Amount",), "amount", 560, True)),
        (Part("0000-0000-0000-5521", "Double Cash", 96233, (
            Sec("Payments, Credits and Adjustments", "in", (Item(12, ("ONLINE PAYMENT, THANK YOU",), 96233),)),
            Sec("Standard Purchases", "out", _spend(77, 18, 29)))),),
        in_printed="negative"),
    "capone_card": Spec(
        "capone_card", "card", "Northpoint One", "Account ending in", "Billing Cycle", "%b %d, %Y", " - ",
        TODAY_END, 31, "Previous Balance", "New Balance", "%b %d", "parens",
        (Col(("Trans Date",), "date", 40), Col(("Description",), "description", 100), Col(("Amount",), "amount", 560, True)),
        (Part("XXXXXXXXXXXX2218", "Quicksilver", 41260, (
            Sec("Transactions", "signed", (*_spend(91, 40, 30), Item(15, ("RETURN HOLLOWAY AUTO SPA",), 2500),
                                           Item(19, ("CAPITAL PAYMENT - THANK YOU",), 41260))),)),)),
}
BANK_CARD = ("chase_checking", "boa_checking", "wells_checking", "cu_savings", "chase_card", "amex_card", "citi_card",
             "capone_card")
HSPECS: dict[str, HSpec] = {
    "fidelity_brokerage": HSpec(
        "fidelity_brokerage", "investment", "Northgate Investments", "Account Number", "0000-1234-5678", "Statement Period",
        "%B %d, %Y", " - ", TODAY_END, 31, "Beginning Account Value", "Ending Account Value", 8_012_544,
        cols=(Col(("Symbol",), "symbol", 40), Col(("Description",), "name", 96), Col(("Quantity",), "shares", 385, True),
              Col(("Price",), "price", 465, True), Col(("Market Value",), "value", 570, True)),
        holdings=(Holding("NGTSX", "Northgate Total Stock Index", "412.118", 12691, 5_230_190),
                  Holding("NGISX", "Northgate International Index", "602.400", 3501, 2_108_903),
                  Holding("SWPXX", "Cash Sweep Money Market", None, None, 1_082_040, cash=True)),
        total_label="Total Holdings", rounding=37, cash_labels=("Cash Sweep",)),
    "vanguard_ira": HSpec(
        "vanguard_ira", "retirement", "Pinecrest Funds", "Account number", "00000098765", "Statement period", "%m/%d/%Y",
        " - ", TODAY_END, 90, "Beginning balance", "Ending balance", 6_502_210, title="Your IRA funds",
        cols=(Col(("Fund name",), "name", 40), Col(("Shares",), "shares", 400, True), Col(("Price",), "price", 480, True),
              Col(("Balance",), "value", 570, True)),
        holdings=(Holding(None, "Pinecrest Target Retirement 2050 Fund", "1,204.553", 4112, 4_953_122),
                  Holding(None, "Pinecrest Total Bond Market Index", "802.114", 1022, 819_761),
                  Holding(None, "Pinecrest Federal Money Market", None, None, 151_020, cash=True)),
        total_label="Total account value", cash_labels=("Money Market",)),
    "empower_401k": HSpec(
        "empower_401k", "retirement", "Brightwater Retirement Services", "Participant ID", "000041286", "Statement Period",
        "%m/%d/%Y", " to ", TODAY_END, 90, "Beginning Balance", "Ending Balance", 11_480_017, title="Your Investments",
        cols=(Col(("Investment",), "name", 40), Col(("Units",), "shares", 390, True), Col(("Unit Price",), "price", 470, True),
              Col(("Balance",), "value", 565, True)),
        holdings=(Holding(None, "Pinecrest Target Retirement 2050 Trust", "1,204.5531", 2412, 2_905_382),
                  Holding(None, "Brightwater Company Stock Fund", "88.2140", 4177, 368_470),
                  Holding(None, "Large Cap Index Fund", "312.0087", 5233, 1_632_741),
                  Holding(None, "Stable Value Fund", "905.4400", 1090, 987_030),
                  Holding(None, "International Index Fund", "140.6620", 1845, 259_473)),
        total_label="Total Account Balance", after_title="Balance by Source",
        after=(("Employee Pre-Tax Deferral", 4_301_267), ("Employer Match", 1_851_829), ("Total", 6_153_096))),
    "auto_loan": HSpec(
        "auto_loan", "loan", "Lakeshore Auto Finance", "Loan Number", "0000077112", "Statement Date Range", "%m/%d/%Y",
        " - ", TODAY_END, 31, "Previous Principal Balance", "Principal Balance", 862_518, closing_cents=841_207,
        extra=("Payment Amount $412.33", "Payment Due Date 04/15/26")),
    "mortgage": HSpec(
        "mortgage", "loan", "Harborview Home Loans", "Loan number", "0000031415", "Statement period", "%B %d, %Y", " to ",
        TODAY_END, 31, "Previous Outstanding Principal", "Outstanding Principal", 21_301_877, closing_cents=21_234_567,
        extra=("Escrow Balance $1,234.56", "Interest Rate 6.125%")),
}
HOLDINGS = ("fidelity_brokerage", "vanguard_ira", "empower_401k")
LOANS = ("auto_loan", "mortgage")
VARIANTS = ("password", "permissions", "redesign", "off", "drifted", "scan", "mixed")


def scan_image(png: bytes, seed: int) -> bytes:
    """A page picture made to look scanned: 0.5-1.5 degrees of skew, a mild blur, seeded speckle and a grey paper cast."""
    from PIL import Image, ImageFilter
    rng = random.Random(seed)
    img = Image.open(io.BytesIO(png)).convert("L")
    img = img.rotate(rng.uniform(0.5, 1.5) * rng.choice((-1, 1)), resample=Image.BICUBIC, expand=False, fillcolor=255)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    px = img.load()
    for _ in range(img.width * img.height // 400):
        x, y = rng.randrange(img.width), rng.randrange(img.height)
        px[x, y] = rng.choice((0, 90, 160, 255))
    img = img.point(lambda v: min(255, int(v * 0.93 + 10)))
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def _pictures(data: bytes, seed: int, dpi: int) -> list[bytes]:
    """Each page rendered in this process (synthetic files only; Steward itself renders only in its sandbox)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(data)
    try:
        out = []
        for k in range(len(doc)):
            page = doc[k]
            img = page.render(scale=dpi / 72, grayscale=True).to_pil().convert("L")
            page.close()
            buf = io.BytesIO()
            img.save(buf, "PNG")
            out.append(scan_image(buf.getvalue(), seed + k))
        return out
    finally:
        doc.close()


def _as_pictures(data: bytes, keep_text: set[int], seed: int = 7) -> bytes:
    """A PDF of page pictures, with no text layer, except the pages in keep_text (1-based), copied as text pages."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    import pypdfium2 as pdfium
    pictures = _pictures(data, seed, 150 + seed % 51)
    if keep_text:
        src = pdfium.PdfDocument(data)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H), invariant=1)
    for k, png in enumerate(pictures, 1):
        if k in keep_text:
            continue
        c.drawImage(ImageReader(io.BytesIO(png)), 0, 0, width=PAGE_W, height=PAGE_H)
        c.showPage()
    c.save()
    if not keep_text:
        return buf.getvalue()
    out = pdfium.PdfDocument.new()
    pics = pdfium.PdfDocument(buf.getvalue())
    p = 0
    for k in range(1, len(pictures) + 1):
        if k in keep_text:
            out.import_pages(src, [k - 1])
        else:
            out.import_pages(pics, [p])
            p += 1
    final = io.BytesIO()
    out.save(final)
    return final.getvalue()


def _redesign(s: Spec) -> Spec:
    """A bank redesign: new header wording, so no remembered layout matches."""
    cols = tuple(replace(c, head=("TRANSACTION DETAIL",)) if c.field == "description" else c for c in s.cols)
    return replace(s, cols=cols)


def _drifted(s: Spec) -> Spec:
    """Engineering choice 15: a section added under the same header, so the remembered layout matches and misses it."""
    part = s.parts[0]
    extra = Sec("OTHER WITHDRAWALS", "out", (Item(19, ("SERVICE CHARGE",), -1200), Item(26, ("WIRE FEE",), -2500)),
                "Total Other Withdrawals")
    return replace(s, parts=(replace(part, sections=(*part.sections, extra)),))


def _sheets(n: int) -> tuple[bytes, Truth]:
    """A long file of plain pages: 60 opens, 61 is refused (P8)."""
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H), invariant=1)
    for k in range(1, n + 1):
        c.setFont("Helvetica", 9)
        c.drawString(40, PAGE_H - 60, f"Lakeshore National Bank statement archive, sheet {k}")
        c.showPage()
    c.save()
    return buf.getvalue(), Truth(f"pages{n}", "bank", "Lakeshore National Bank", (TODAY_END, TODAY_END), "", 0, 0, (),
                                 {}, n)


def _receipt() -> tuple[bytes, Truth]:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H), invariant=1)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, PAGE_H - 50, "Corner Bakery")
    c.setFont("Helvetica", 9)
    for k, (item, price) in enumerate((("Sourdough loaf", "7.50"), ("Two croissants", "5.00"))):
        c.drawString(40, PAGE_H - 80 - 12 * k, item)
        c.drawRightString(300, PAGE_H - 80 - 12 * k, price)
    c.drawString(40, PAGE_H - 120, "Total")
    c.drawRightString(300, PAGE_H - 120, "12.50")
    c.showPage()
    c.save()
    return buf.getvalue(), Truth("receipt", "receipt", "Corner Bakery", (TODAY_END, TODAY_END), "", 0, 0, (), {}, 1)


def build(sid: str, end: date | None = None, variant: str | None = None) -> tuple[bytes, Truth]:
    """One statement's PDF bytes and its truth. end moves the whole statement (the e2e dates it from its server's
    day); variant is one of VARIANTS."""
    if sid in ("pages60", "pages61"):
        return _sheets(int(sid[5:]))
    if sid == "receipt":
        return _receipt()
    if sid in HSPECS:
        h = HSPECS[sid]
        data, truth = _draw_holdings(h, end or h.end, 250 if variant == "off" else 0)
        if variant == "scan":
            return _as_pictures(data, set()), truth
        if variant not in (None, "off"):
            raise ValueError(variant)
        return data, truth
    s = SPECS[sid]
    misprint, encrypt = 0, None
    if variant == "off":
        misprint = 1240
    elif variant == "redesign":
        s = _redesign(s)
    elif variant == "drifted":
        s = _drifted(s)
    elif variant in ("password", "permissions"):
        from reportlab.lib.pdfencrypt import StandardEncryption
        encrypt = StandardEncryption("secret" if variant == "password" else "", ownerPassword="owner-only",
                                     canPrint=0, canModify=0, canCopy=0, canAnnotate=0)
    elif variant in ("scan", "mixed"):
        data, truth = _draw(s, end or s.end)
        keep = set(range(2, truth.pages + 1)) if variant == "mixed" else set()
        return _as_pictures(data, keep), truth
    elif variant is not None:
        raise ValueError(variant)
    return _draw(s, end or s.end, misprint, encrypt)
