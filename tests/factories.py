from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.business.tagging import is_business_account

from steward.db.models import Account, AccountType, BalanceSnapshot, CategorySource, Child, Fact, Holding, Institution, Owner, Source, SsEarnings, Transaction


TEST_BOOK_KEY = "steward.test_book"


def make_account(db: Session, name="Checking", type=AccountType.checking, owner=Owner.joint,
                 source=Source.manual, institution_name="Manual") -> Account:
    if isinstance(type, str):
        type = AccountType(type)
    if isinstance(owner, str):
        owner = Owner(owner)
    if isinstance(source, str):
        source = Source(source)
    query = select(Institution).where(Institution.source == source)
    if source != Source.manual:
        query = query.where(Institution.name == institution_name)
    inst = db.scalar(query)
    if inst is None:  # at most one manual institution is allowed, so reuse it whatever its name
        inst = Institution(name=institution_name, source=source)
        db.add(inst)
    a = Account(institution=inst, name=name, type=type, owner=owner, source=source)
    db.add(a); db.commit()
    return a


def make_txn(db: Session, account: Account, posted_at: date, amount_cents: int, raw: str,
             merchant=None, category="uncategorized", is_business=None, is_transfer=False,
             category_source=CategorySource.none, external_id=None, business_pct=None, business_line=None,
             business_hint=None) -> Transaction:
    """With neither is_business nor business_pct given, a row on a business account is business by account, as at
    import (final review ruling I1)."""
    source = "manual"
    if business_pct is not None:
        pct = business_pct
    elif is_business is not None:
        pct = 100 if is_business else 0
    elif not is_transfer and is_business_account(account):
        pct, source = 100, "account"
    else:
        pct = 0
    t = Transaction(account_id=account.id, posted_at=posted_at, amount_cents=amount_cents,
                    raw_description=raw, merchant=merchant, category=category, is_business=pct == 100,
                    is_transfer=is_transfer, category_source=category_source, external_id=external_id,
                    business_pct=pct, business_source=source if pct else "none", business_line=business_line,
                    business_hint=business_hint)
    db.add(t); db.commit()
    return t


def make_user(db: Session, username="jr", email="jr@x.com", display_name="JR", password="pw-one-two-3",
              role="manager"):
    """A person in the directory, made a member of the test's book (the conftest `db` session knows which)."""
    from steward.auth.users import create_user
    from steward.books.service import add_membership
    books, book_id = db.info[TEST_BOOK_KEY]
    with Session(books.directory) as ddb:
        u = create_user(ddb, username, email, display_name, password)
        add_membership(ddb, u.id, book_id, role, by=None)
        ddb.commit()
        ddb.refresh(u)
        ddb.expunge(u)
    return u


def make_person(ddb: Session, username: str, memberships=(), password="pw-one-two-3"):
    """A person in the directory with memberships [(book_id, role), ...]; email <username>@x.com."""
    from steward.auth.users import create_user
    from steward.books.service import add_membership
    u = create_user(ddb, username, f"{username}@x.com", username.title(), password)
    for book_id, role in memberships:
        add_membership(ddb, u.id, book_id, role, by=None)
    ddb.commit()
    return u


def login(client, username: str, password="pw-one-two-3") -> None:
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def add_fact(db: Session, key: str, value: str, as_of: date = date(2026, 10, 1)) -> Fact:
    f = Fact(key=key, value=value, as_of=as_of)
    db.add(f); db.commit()
    return f


def make_ready_household(db: Session) -> dict[str, Account]:
    """A made-up household with every Plan input filled in, for today = 2026-10-13. Nothing here is real.

    Derived over Oct 2025-Sep 2026: money in $132,000, money out $108,000 (mortgage debits included),
    principal and interest $36,000, so the spending basis is $72,000 and the surplus $24,000;
    the gift is $10,000 and consulting $6,000."""
    from steward.services.vault_flows import month_add
    for k, v in {"jr.dob": "1982-05-01", "spouse.dob": "1984-08-01", "state": "CA", "filing_status": "mfj",
                 "jr.salary_cents": "16000000", "jr.k401_pct_bp": "1000", "jr.k401_roth_share_bp": "0",
                 "employer.match_rate_bp": "5000", "employer.match_cap_bp": "600", "mortgage.payment_cents": "300000",
                 "mortgage.payoff_date": "2048-06-01", "health.premium_cents": "2400000"}.items():
        db.add(Fact(key=k, value=v, as_of=date(2026, 10, 1)))
    accts = {
        "checking": make_account(db, "Checking", type="checking"),
        "taxable": make_account(db, "Brokerage", type="brokerage_taxable"),
        "k401": make_account(db, "401(k)", type="k401", owner="jr"),
        "roth": make_account(db, "Roth IRA", type="roth_ira", owner="jr"),
        "p529": make_account(db, "529 Oldest", type="plan529"),
        "mortgage": make_account(db, "Mortgage", type="mortgage"),
        "business": make_account(db, "Business checking", type="business_checking", owner="business"),
    }
    for key, cents in (("checking", 4_000_000), ("taxable", 15_000_000), ("k401", 45_000_000), ("roth", 9_000_000),
                       ("p529", 3_000_000), ("mortgage", -40_000_000), ("business", 1_000_000)):
        db.add(BalanceSnapshot(account_id=accts[key].id, as_of=date(2026, 10, 1), balance_cents=cents))
    as_of = date(2026, 10, 1)
    db.add_all([
        Holding(account_id=accts["taxable"].id, as_of=as_of, symbol="VTI", name="Total Stock", shares_milli=1, market_value_cents=9_000_000, expense_ratio_bp=3),
        Holding(account_id=accts["taxable"].id, as_of=as_of, symbol="BND", name="Total Bond", shares_milli=1, market_value_cents=6_000_000, expense_ratio_bp=3),
        Holding(account_id=accts["k401"].id, as_of=as_of, symbol="ZZFUNDX", name="Plan Fund", shares_milli=1, market_value_cents=45_000_000, expense_ratio_bp=20),
    ])
    db.add(Child(label="Oldest", birth_year=2015, cost_level="in_state_public", account_id=accts["p529"].id, monthly_contribution_cents=30_000))
    stamp = datetime(2026, 10, 1, tzinfo=timezone.utc)
    db.add_all([SsEarnings(person="jr", year=y, earnings_cents=(30_000 + (y - 2004) * 5_714) * 100, imported_at=stamp) for y in range(2004, 2026)])
    chk = accts["checking"].id
    for i in range(12):
        d = month_add(date(2025, 10, 1), i)
        db.add_all([Transaction(account_id=chk, posted_at=d, amount_cents=1_100_000, raw_description="PAYROLL", category="income"),
                    Transaction(account_id=chk, posted_at=d.replace(day=5), amount_cents=-300_000, raw_description="HOME LOAN SVC", category="housing"),
                    Transaction(account_id=chk, posted_at=d.replace(day=9), amount_cents=-600_000, raw_description="GROCER", category="groceries")])
    db.add(Transaction(account_id=chk, posted_at=date(2025, 12, 20), amount_cents=1_000_000, raw_description="GIFT FROM FAMILY", category="gifts"))
    db.add(Transaction(account_id=accts["business"].id, posted_at=date(2026, 3, 3), amount_cents=600_000, raw_description="CLIENT",
                       category="business_income", is_business=True, business_pct=100, business_source="manual"))
    db.commit()
    return accts
