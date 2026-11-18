"""Fake demo household. Fixed fake merchants only; never touches real data."""
import json
import random
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from steward.db.models import (
    Account, AccountType as T, BalanceSnapshot, BusinessRule, BusinessState, CategorySource, Child, Fact, Holding, Institution, Owner as O, Source,
    SsEarnings, TaxState, Transaction,
)
from steward.services.accounts import manual_institution
from steward.services.costs import fill_ratios

MERCHANTS = {  # raw description -> (merchant, category)
    "GREENLEAF MARKET #12": ("Greenleaf Market", "groceries"), "COSTBOX WHSE #0482": ("Costbox", "groceries"),
    "BEAN & LEAF 0031": ("Bean & Leaf", "dining"), "TAQUERIA SOL": ("Taqueria Sol", "dining"),
    "NOODLE HOUSE": ("Noodle House", "dining"), "PIZZA PLANET 44": ("Pizza Planet", "dining"),
    "CITY POWER & LIGHT": ("City Power & Light", "utilities"), "WATERWORKS DIST": ("Waterworks", "utilities"),
    "FIBERNET INTERNET": ("Fibernet", "utilities"), "MOBILE ONE WIRELESS": ("Mobile One", "utilities"),
    "STREAMFLIX": ("Streamflix", "subscriptions"), "CLOUDTUNES": ("Cloudtunes", "subscriptions"),
    "GYMTIME MONTHLY": ("Gymtime", "personal"), "PETROL STOP 88": ("Petrol Stop", "transport"),
    "QUICKFUEL 102": ("Quickfuel", "transport"), "BRIDGE TOLL AUTH": ("Bridge Toll", "transport"),
    "FAMILY CLINIC": ("Family Clinic", "health"), "PHARMARX 2231": ("PharmaRx", "health"),
    "SAFEGUARD INSURANCE": ("Safeguard Insurance", "insurance"),
    "LITTLE SPROUTS PRESCHOOL": ("Little Sprouts", "childcare_education"),
    "GRACE COMMUNITY CHURCH": ("Grace Community", "giving"), "HOPE FOUNDATION": ("Hope Foundation", "giving"),
    "MEGAMART ONLINE": ("Megamart", "shopping"), "HARDWARE BARN 331": ("Hardware Barn", "home"),
    "TOYLAND 90": ("Toyland", "kids"), "SKYLINE AIR": ("Skyline Air", "travel"),
    "STAYWELL HOTELS": ("Staywell Hotels", "travel"), "CINEMA 12": ("Cinema 12", "entertainment"),
    "BOOKNOOK": ("Booknook", "shopping"), "FLOWER CART": ("Flower Cart", "gifts"),
    "DESIGN SUITE SUB": ("Design Suite", "business_expense"), "CLOUDHOST INC": ("Cloudhost", "business_expense"),
    "COWORK SPACE LLC": ("Cowork Space", "business_expense"), "OFFICE STUFF 12": ("Office Stuff", "business_expense"),
    "NOTEFLOW PRO": ("Noteflow", "subscriptions"),
}
UNCAT = ["SQ *VENDOR 2291", "PAYPAL *MISC", "ZELLE PAYMENT TO J.", "CHECK 1042", "POS DEBIT 77812", "TST* SOMETHING"]

# Merchants that are drawn by their own rhythm, not from the general daily pool.
_SUBSCRIPTIONS = ("STREAMFLIX", "CLOUDTUNES", "GYMTIME MONTHLY", "FIBERNET INTERNET", "MOBILE ONE WIRELESS")
_FIXED = set(_SUBSCRIPTIONS) | {"CITY POWER & LIGHT", "DESIGN SUITE SUB", "CLOUDHOST INC", "NOTEFLOW PRO"}
_GROCERY = [r for r, (_, c) in MERCHANTS.items() if c == "groceries"]
_DINING = [r for r, (_, c) in MERCHANTS.items() if c == "dining"]
_TRAVEL = [r for r, (_, c) in MERCHANTS.items() if c == "travel"]
_POOL = [r for r, (_, c) in MERCHANTS.items()
         if r not in _FIXED and c not in ("groceries", "dining", "travel")]
_CHANCE_UNREVIEWED = 0.2  # share of everyday spending left uncategorized for the review queue


# The demo household's two sign-ins. serve refuses to start in prod while either still has its password (release
# spec 2026-11-05, section 6), so they live in one place. Made-up people, as the Sample's are (books/people.py,
# SAMPLE_PEOPLE): Person 1 is Alex there too. Their owner keys stay jr and spouse, as in every household.
DEMO_LOGINS = (("alex", "alex@example.com", "Alex", "pw-demo-alex-2026"),
               ("spouse", "spouse@example.com", "Sam", "pw-demo-spouse-2026"))
# Sign-ins an older demo seeded, (username, password), never seeded again. The prod guard (auth/demo_guard.py) still
# refuses a vault where one keeps its demo password; it compares the password, so a real account that happens to
# have the same username starts as usual.
RETIRED_DEMO_LOGINS = (("jr", "pw-demo-jr-2026"),)


def seed_people(ddb: Session, book_id: int) -> list[int]:
    """The demo household's two people, managers of the book; their ids, first member first. Safe to run twice."""
    from steward.auth.users import create_user, find_user
    from steward.books.service import add_membership
    from steward.db.directory_models import Membership
    ids = []
    for username, email, name, pw in DEMO_LOGINS:
        u = find_user(ddb, username) or create_user(ddb, username, email, name, pw)
        if ddb.get(Membership, (u.id, book_id)) is None:
            add_membership(ddb, u.id, book_id, "manager", by=None, note="demo", welcomed=True)
        ids.append(u.id)
    ddb.commit()
    return ids


def mark_profiles_seen(db: Session, user_ids: list[int], end: date | None = None) -> None:
    """The demo's profile is complete, so its people have seen it: they land on Home, which the demo quick start shows,
    not on Profile's first visit (issue #30)."""
    from steward.services.profile import mark
    at = datetime.combine(end or DEMO_END, time(19), timezone.utc)
    for uid in user_ids:
        mark(db, uid, at, seen=True)
    db.commit()


# Fixed, not today(): a given seed always yields the same data. The Sample book passes today (guided setup spec 8.2).
DEMO_END = date(2026, 10, 12)


def seed(db: Session, years: int = 2, seed: int = 7, end: date = DEMO_END) -> dict:
    rng = random.Random(seed)
    stamp = datetime.combine(end, time(19), timezone.utc)
    start = end - timedelta(days=365 * years)

    def inst(name, source=Source.simplefin):
        i = Institution(name=name, source=source)
        db.add(i)
        db.flush()
        return i

    # A forced re-seed adds a second household alongside the first; keep external ids unique.
    run = db.scalar(select(func.count()).select_from(Account).where(Account.external_id.like("bb-chk%")))

    def acct(i, name, t, o, source=Source.simplefin, ext=None):
        if ext and run:
            ext = f"{ext}-r{run}"
        a = Account(institution_id=i.id, name=name, type=t, owner=o, source=source, external_id=ext)
        db.add(a)
        db.flush()
        return a

    big, hysa, robo, work, biz, manual = (inst("Big Bank"), inst("Savings Bank"), inst("Robo Invest"),
                                          inst("Workplace Retirement"), inst("Business Bank"),
                                          manual_institution(db))
    chk = acct(big, "Checking", T.checking, O.joint, ext="bb-chk")
    sav = acct(big, "Savings", T.savings, O.joint, ext="bb-sav")
    card = acct(big, "Rewards Card", T.credit, O.joint, ext="bb-card")
    hy = acct(hysa, "High-yield savings", T.savings, O.joint, ext="sb-hy")
    tax = acct(robo, "Taxable", T.brokerage_taxable, O.joint, ext="ro-tax")
    roth = acct(robo, "Roth IRA", T.roth_ira, O.jr, ext="ro-roth")
    k401 = acct(work, "401(k)", T.k401, O.spouse, ext="wr-401k")
    bchk = acct(biz, "Business checking", T.business_checking, O.business, ext="bz-chk")
    bcard = acct(biz, "Business card", T.business_credit, O.business, ext="bz-card")
    mort = acct(manual, "Mortgage", T.mortgage, O.joint, Source.manual)
    home = acct(manual, "Home", T.property, O.joint, Source.manual)
    p529 = acct(manual, "529 — kid 1", T.plan529, O.joint, Source.manual)
    p529b = acct(manual, "529 — kid 2", T.plan529, O.joint, Source.manual)

    bal = {chk.id: 1_450_000, sav.id: 2_200_000, card.id: 0, hy.id: 6_500_000, tax.id: 18_000_000,
           roth.id: 9_500_000, k401.id: 31_000_000, bchk.id: 2_800_000, bcard.id: 0,
           mort.id: -41_250_000, home.id: 92_000_000, p529.id: 2_400_000, p529b.id: 1_100_000}
    ext_by_id = {a.id: a.external_id for a in (chk, sav, card, hy, tax, roth, k401, bchk, bcard)}
    txns: list[dict] = []
    snaps: list[dict] = []

    def add(a, d, cents, raw, merchant=None, cat="uncategorized", biz=False, xfer=False, hint=None):
        categorized = cat != "uncategorized"
        txns.append(dict(
            account_id=a.id, posted_at=d, amount_cents=cents, raw_description=raw, merchant=merchant,
            category=cat, is_business=biz, is_transfer=xfer or cat == "transfer",
            category_source=CategorySource.rule if categorized else CategorySource.none,
            business_pct=100 if biz else 0, business_source="rule" if biz else "none", business_hint=hint,
            external_id=f"{ext_by_id[a.id]}-{len(txns) + 1}"))
        bal[a.id] += cents

    def spend(a, d, raw, lo, hi, biz=False):
        m, c = MERCHANTS[raw]
        if rng.random() < _CHANCE_UNREVIEWED:
            m, c = None, "uncategorized"
        add(a, d, -rng.randint(lo, hi), raw, m, c, biz=biz)

    d = start
    while d <= end:
        if d.day in (1, 15):
            add(chk, d, 412_000, "PAYROLL ACME CORP", "Acme Corp payroll", "income")
            add(k401, d, 80_000, "EMPLOYEE DEFERRAL", "401(k) contribution", "investment")
            add(k401, d, 40_000, "EMPLOYER MATCH", "Employer match", "investment")
        if d.day == 1:
            add(chk, d, -268_000, "MORTGAGE PMT HOMELOAN SVC", "Home loan", "housing")
            bal[mort.id] += 95_000  # principal portion; intentionally no paired transaction (the mortgage is a manual account)
            add(chk, d, -100_000, "TRANSFER TO SAVINGS", "Transfer", "transfer", xfer=True)
            add(sav, d, 100_000, "TRANSFER FROM CHECKING", "Transfer", "transfer", xfer=True)
            add(chk, d, -58_300, "ROBO INVEST ROTH CONTRIB", "Transfer", "transfer", xfer=True)
            add(roth, d, 58_300, "CONTRIBUTION", "Transfer", "transfer", xfer=True)
            add(bchk, d, -rng.randint(60_000, 120_000), "DESIGN SUITE SUB", "Design Suite", "business_expense", biz=True)
            add(bchk, d, -rng.randint(30_000, 70_000), "CLOUDHOST INC", "Cloudhost", "business_expense", biz=True)
            add(bchk, d, -500_000, "OWNER DRAW TO PERSONAL", "Transfer", "transfer", biz=True, xfer=True)
            add(chk, d, 500_000, "DEPOSIT FROM BUSINESS", "Transfer", "transfer", xfer=True)
        if 1 <= d.day <= len(_SUBSCRIPTIONS):  # one subscription per day over the first days of the month
            raw = _SUBSCRIPTIONS[d.day - 1]
            m, c = MERCHANTS[raw]
            add(card, d, -rng.randint(1_200, 9_900), raw, m, c)
        if d.day == 6:
            add(chk, d, -rng.randint(90_000, 190_000), "CITY POWER & LIGHT", "City Power & Light", "utilities")
        if d.day == 3 and d >= end - timedelta(days=103):  # a note-taking app on the personal card: Review asks about it
            add(card, d, -2_900, "NOTEFLOW PRO", "Noteflow", "subscriptions", hint=85)
        if d.day == 20:  # pay the card in full; the card side is the matching credit
            for pay, c, name, is_biz in ((chk, card, "REWARDS", False), (bchk, bcard, "BUSINESS", True)):
                owed = -bal[c.id]
                if owed > 0:
                    add(pay, d, -owed, f"PAYMENT TO {name} CARD", "Transfer", "transfer", biz=is_biz, xfer=True)
                    add(c, d, owed, "PAYMENT THANK YOU", "Transfer", "transfer", biz=is_biz, xfer=True)
        if d.month == 12 and d.day == 15:  # the yearly family gift: a lever, not baseline (spec 1, 2.5)
            add(chk, d, 1_000_000, "ZELLE FROM GRANDMA R", "Family gift", "gifts")
        if rng.random() < 0.1:  # consulting deposits, about 3 a month
            add(bchk, d, rng.randint(150_000, 450_000), f"ACH CLIENT INV {rng.randint(1000, 9999)}",
                "Consulting invoice", "business_income", biz=True)
        if d.weekday() == 5:
            spend(card, d, rng.choice(_GROCERY), 9_000, 32_000)
        elif d.weekday() == 2 and rng.random() < 0.5:
            spend(card, d, rng.choice(_GROCERY), 3_000, 12_000)
        if rng.random() < 2.5 / 7:  # dining 2-3x a week
            spend(card, d, rng.choice(_DINING), 800, 7_500)
        for _ in range(2):  # everyday spending: two independent draws a day
            if rng.random() < 0.7:
                raw = rng.choice(_POOL)
                if MERCHANTS[raw][1] == "business_expense":
                    spend(bcard, d, raw, 1_500, 20_000, biz=True)
                else:
                    spend(card, d, raw, 800, 15_000)
        if d.month in (7, 12) and d.day <= 10 and rng.random() < 0.5:  # travel spike
            spend(card, d, rng.choice(_TRAVEL), 25_000, 90_000)
        if rng.random() < 0.05:
            add(rng.choice([card, chk]), d, -rng.randint(500, 12_000), rng.choice(UNCAT))
        if d.day == 28 and d.month in (1, 4, 7, 10):
            add(chk, d, -rng.randint(400_000, 700_000), "USTREAS IRS ESTIMATED TAX", "IRS", "taxes")
        for a_id in (tax.id, roth.id, k401.id, p529.id, p529b.id):  # market drift
            bal[a_id] = round(bal[a_id] * (1 + rng.gauss(0.0003, 0.006)))
        snaps.extend(dict(account_id=a_id, as_of=d, balance_cents=cents) for a_id, cents in bal.items())
        d += timedelta(days=1)

    db.execute(insert(Transaction), txns)
    db.execute(insert(BalanceSnapshot), snaps)

    holdings = 0
    held: list[Holding] = []
    for a, funds in ((tax, (("VTI", "Total Stock Market ETF", 0.60), ("VXUS", "Total International Stock ETF", 0.25),
                            ("BND", "Total Bond Market ETF", 0.15))),
                     (roth, (("VFIFX", "Target Retirement 2050 Fund", 1.00),)),
                     (k401, (("FXAIX", "500 Index Fund", 0.70), ("ACMEX", "Acme Stable Value Fund", 0.30)))):
        for symbol, name, share in funds:
            h = Holding(account_id=a.id, as_of=end, symbol=symbol, name=name, shares_milli=round(bal[a.id] * share / 100),
                        market_value_cents=round(bal[a.id] * share))
            db.add(h)
            held.append(h)
            holdings += 1
        a.holdings_seen_at, a.sends_holdings = stamp, True
    db.flush()
    fill_ratios(db, held)   # investment views spec: costs come from the fund table; ACMEX isn't in it
    with_rows = {t["account_id"] for t in txns}
    for a in (chk, sav, card, hy, tax, roth, k401, bchk, bcard):   # what the (pretend) bank sends
        a.sends_transactions = a.id in with_rows
        a.transactions_seen_at = stamp if a.id in with_rows else None

    for label, year, plan, monthly in (("Oldest", 2015, p529, 25_000), ("Middle", 2018, p529b, 25_000), ("Youngest", 2021, None, 0)):
        db.add(Child(label=label, birth_year=year, cost_level="in_state_public",
                     account_id=plan.id if plan else None, monthly_contribution_cents=monthly))

    if not db.scalar(select(func.count()).select_from(SsEarnings)):  # a forced re-seed keeps the first record
        db.add_all([SsEarnings(person="jr", year=y, earnings_cents=(38_000 + (y - 2007) * 6_000) * 100, imported_at=stamp)
                    for y in range(2007, end.year)])
        db.add_all([SsEarnings(person="spouse", year=y, earnings_cents=(28_000 + (y - 2009) * 1_500) * 100, imported_at=stamp)
                    for y in range(2009, 2017)])

    # The car and home office are per tax year; last year's carry into this one (final review ruling I2).
    for key, value in (("type", "sole_prop"), (f"car_method:{end.year - 1}", "standard"),
                       (f"home_office:{end.year - 1}", json.dumps({"method": "simplified", "office_sqft": 120, "home_sqft": 1800,
                                                   "home_costs_cents": 0})),
                       (f"miles:{end.year}", json.dumps([1_200, 900])),
                       (f"expect:{end.year}", json.dumps({"low_cents": 800_000, "high_cents": 2_000_000}))):
        if db.get(BusinessState, key) is None:
            db.add(BusinessState(key=key, value=value, updated_at=stamp))
    # Taxes (part 5): last year's return and this year's withholding through the last month end, all made up. The AGI is over
    # $150,000, so the safe harbor is 110%.
    for key, value in ((f"return:{end.year - 1}", json.dumps({"federal_tax_cents": 2_480_000, "federal_agi_cents": 19_850_000,
                                                   "state_tax_cents": 910_000, "state_agi_cents": 19_850_000})),
                       (f"withholding:{end.year}", json.dumps({"federal_ytd_cents": 1_610_000, "state_ytd_cents": 540_000,
                                                        "as_of": (end.replace(day=1) - timedelta(days=1)).isoformat()}))):
        if db.get(TaxState, key) is None:
            db.add(TaxState(key=key, value=value, updated_at=stamp))
    db.add_all([BusinessRule(kind="account", account_id=bchk.id, pct=100, label="Business checking", created_at=stamp),
                BusinessRule(kind="account", account_id=bcard.id, pct=100, label="Business card", created_at=stamp),
                BusinessRule(kind="client", pattern="ACH CLIENT INV", pct=100, line="income", label="ACH CLIENT INV",
                             created_at=stamp)])

    facts = {"jr.dob": "1985-06-14", "spouse.dob": "1987-02-02", "state": "CA", "filing_status": "mfj",
             "home.value_cents": str(bal[home.id]), "mortgage.rate_bp": "312",
             "mortgage.payoff_date": "2051-03-01",
             "jr.salary_cents": "16500000", "jr.k401_pct_bp": "800", "jr.k401_roth_share_bp": "0",
             "employer.match_rate_bp": "5000", "employer.match_cap_bp": "600",
             "mortgage.payment_cents": "268000", "health.premium_cents": "1680000"}
    for k, v in facts.items():
        db.add(Fact(key=k, value=v, as_of=end))
    db.add(Fact(key="home.account_id", value=str(home.id), as_of=end))   # one home value (roadmap 11): Profile's is Home's
    db.commit()
    return {"accounts": 13, "transactions": len(txns), "snapshots": len(snaps), "facts": len(facts),
            "children": 3, "holdings": holdings}
