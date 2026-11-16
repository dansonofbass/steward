from steward import clock
import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, select, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class TZDateTime(TypeDecorator):
    """UTC timestamps. SQLite drops tzinfo, so store naive UTC and restore tzinfo on load."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; pass an aware UTC datetime")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is not None:
            value = value.replace(tzinfo=timezone.utc)
        return value


def utcnow() -> datetime:
    return clock.now()


class Base(DeclarativeBase):
    pass


class Source(str, enum.Enum):
    simplefin = "simplefin"
    manual = "manual"


class AccountType(str, enum.Enum):
    unknown = "unknown"
    checking = "checking"; savings = "savings"; credit = "credit"
    brokerage_taxable = "brokerage_taxable"; k401 = "k401"; roth_ira = "roth_ira"
    traditional_ira = "traditional_ira"; hsa = "hsa"; plan529 = "plan529"
    mortgage = "mortgage"; property = "property"; loan = "loan"   # car, student or personal loan
    business_checking = "business_checking"; business_credit = "business_credit"
    vehicle = "vehicle"   # a car, truck or boat, its value entered by hand like the home's (investment views spec)


LIABILITY_TYPES = {AccountType.credit, AccountType.mortgage, AccountType.loan, AccountType.business_credit}
# The investment account page's six types, and the four with yearly contribution limits (investment views spec).
INVESTMENT_TYPES = frozenset({AccountType.brokerage_taxable, AccountType.k401, AccountType.roth_ira,
                              AccountType.traditional_ira, AccountType.hsa, AccountType.plan529})
RETIREMENT_TYPES = frozenset({AccountType.k401, AccountType.roth_ira, AccountType.traditional_ira, AccountType.hsa})
ADVISORY_FEE_MAX_BP = 300   # 3% a year


class Owner(str, enum.Enum):
    """The household book's owner keys ("Ours"). Other books have their own (steward.books.owners)."""
    jr = "jr"; spouse = "spouse"; joint = "joint"; business = "business"


class OwnerKey(TypeDecorator):
    """account.owner holds one of the book's owner keys (spec 2.1). An Owner member is stored as its value, so the
    household code that passes Owner.joint keeps working."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return value.value if isinstance(value, enum.Enum) else value


class CategorySource(str, enum.Enum):
    rule = "rule"; correction = "correction"; model = "model"; none = "none"


CATEGORIES: tuple[str, ...] = (
    "groceries", "dining", "housing", "utilities", "transport", "travel", "health",
    "insurance", "loan_payments", "childcare_education", "giving", "subscriptions", "shopping", "personal", "cash_atm",
    "kids", "pets", "home", "gifts", "entertainment", "income", "business_income",
    "business_expense", "taxes", "transfer", "investment", "fees", "interest", "reimbursement", "uncategorized",
)


class SimplefinLink(Base):
    __tablename__ = "simplefin_link"
    id: Mapped[int] = mapped_column(primary_key=True)
    access_url: Mapped[str] = mapped_column(Text)
    claimed_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    last_sync_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)


class Institution(Base):
    __tablename__ = "institution"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    source: Mapped[Source] = mapped_column(Enum(Source))
    simplefin_org_id: Mapped[str | None] = mapped_column(String(120))   # despite the name, SimpleFIN's connection id
    org_id: Mapped[str | None] = mapped_column(String(120))   # SimpleFIN's id for the bank itself (same-account spec)
    last_sync_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    dismissed_error: Mapped[str | None] = mapped_column(Text)  # a last_error a person dismissed; not raised again
    accounts: Mapped[list["Account"]] = relationship(back_populates="institution")

    __table_args__ = (
        Index("uq_institution_manual", "source", unique=True, sqlite_where=text("source = 'manual'")),
    )


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institution.id"))
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[AccountType] = mapped_column(Enum(AccountType))
    owner: Mapped[str] = mapped_column(OwnerKey())
    source: Mapped[Source] = mapped_column(Enum(Source))
    external_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    rate_bp: Mapped[int | None] = mapped_column(Integer)   # a card's or loan's yearly interest rate (Next dollar step 4)
    # Investment views spec: an adviser's yearly fee (investment types only); a vehicle's loan, for display; and what
    # SimpleFIN delivered for this account at the last sync, with when each was last seen.
    advisory_fee_bp: Mapped[int | None] = mapped_column(Integer)
    loan_id: Mapped[int | None] = mapped_column(ForeignKey("account.id", ondelete="SET NULL"))
    sends_holdings: Mapped[bool | None] = mapped_column(Boolean)
    sends_transactions: Mapped[bool | None] = mapped_column(Boolean)
    holdings_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    transactions_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    institution: Mapped[Institution] = relationship(back_populates="accounts")


class Transaction(Base):
    __tablename__ = "transaction"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    posted_at: Mapped[date] = mapped_column(Date, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    raw_description: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(200))
    merchant: Mapped[str | None] = mapped_column(String(200), index=True)
    # Polish round P31: a name a person gave the row ("Disney+"), shown as "Disney+ (PayPal)"; never read by the advisor.
    nickname: Mapped[str | None] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(40), default="uncategorized", index=True)
    is_business: Mapped[bool] = mapped_column(Boolean, default=False)
    is_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    transfer_peer_id: Mapped[int | None] = mapped_column(ForeignKey("transaction.id"))
    category_source: Mapped[CategorySource] = mapped_column(Enum(CategorySource), default=CategorySource.none)
    reviewed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    snoozed_until: Mapped[datetime | None] = mapped_column(TZDateTime)
    imported_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batch.id"))
    watched_at: Mapped[datetime | None] = mapped_column(TZDateTime)  # when the checks looked at it (spec 4.1)
    # Business or personal (business plan rulings 1-2): business_pct 0 is personal, 100 is all business, between is a
    # split. is_business stays and means 100% business. business_source: none | manual | rule | account (a business account's
    # default, final review ruling I1). business_line is a
    # Schedule C line key (steward.business.lines) a person chose; None means the category's default.
    business_pct: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    business_source: Mapped[str] = mapped_column(String(8), default="none", server_default=text("'none'"))
    business_line: Mapped[str | None] = mapped_column(String(20))
    business_hint: Mapped[int | None] = mapped_column(Integer)         # the categorizer's likelihood, 0-100 (ruling 5)
    business_answered_at: Mapped[datetime | None] = mapped_column(TZDateTime)   # someone answered Review's question
    # Phase 12: the model's best guess when it wasn't sure enough to sort the row (only on rows still uncategorized;
    # cleared when a person or a rule sorts the row), its confidence 0-100, and when the model last answered about
    # the row (set at sync, import or catch-up, so the catch-up never asks twice; ruling 14).
    guess_category: Mapped[str | None] = mapped_column(String(40))
    guess_pct: Mapped[int | None] = mapped_column(Integer)
    model_asked_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    # Reimbursable spec: the payer of a reimbursable charge (or of a refund marked with it, R2), or of a repayment
    # (category reimbursement); the trip it was marked on; and who decided: none, manual or rule. A rule never changes
    # a manual one. A payer in use can't be deleted; a trip that goes leaves its rows.
    reimburser_id: Mapped[int | None] = mapped_column(ForeignKey("reimburser.id", ondelete="RESTRICT"), index=True)
    trip_id: Mapped[int | None] = mapped_column(ForeignKey("trip.id", ondelete="SET NULL"), index=True)
    reimburse_source: Mapped[str] = mapped_column(String(8), default="none", server_default=text("'none'"))
    # Same-account spec: the SimpleFIN feed the row came through; NULL for a file's rows and anything typed in.
    feed_id: Mapped[int | None] = mapped_column(ForeignKey("account_feed.id", ondelete="SET NULL"))
    statement_page: Mapped[int | None] = mapped_column(Integer)   # PDF statements spec P42: the page it was read from
    notes: Mapped[list["TransactionNote"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    __table_args__ = (UniqueConstraint("account_id", "external_id", name="uq_txn_external"),
                      Index("ix_txn_account_date", "account_id", "posted_at"),
                      Index("ix_txn_account_amount", "account_id", "amount_cents"))


class PositionsImport(Base):
    """One positions CSV saved into an account (investment views spec): the day it is for, the file's name (never its
    contents, which are read in memory and dropped), how many positions and who."""
    __tablename__ = "positions_import"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    as_of: Mapped[date] = mapped_column(Date)
    filename: Mapped[str] = mapped_column(String(200))
    row_count: Mapped[int] = mapped_column(Integer)
    imported_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    imported_by: Mapped[int] = mapped_column(Integer)   # a directory user id; no foreign key across files
    # PDF statements spec P39, P40 (0037): csv | pdf | pdf_scan, the statement's set, the batch that wrote it (its Undo
    # takes these holdings, never another same-day file's), its first day, its $1 check, the ending balance it printed,
    # the snapshot it wrote, and when it was undone.
    source: Mapped[str] = mapped_column(String(8), default="csv", server_default=text("'csv'"))
    set_id: Mapped[int | None] = mapped_column(ForeignKey("import_set.id"))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batch.id"))
    period_start: Mapped[date | None] = mapped_column(Date)
    check_state: Mapped[str | None] = mapped_column(String(8))
    balance_cents: Mapped[int | None] = mapped_column(Integer)
    snapshot_as_of: Mapped[date | None] = mapped_column(Date)
    rolled_back_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class PositionsMapping(Base):
    """A positions CSV's columns, remembered so the next file from the same place asks nothing. The key is
    "inst:{institution id}" for a connected account, "acct:{account id}" for one entered by hand."""
    __tablename__ = "positions_mapping"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    mapping: Mapped[str] = mapped_column(Text)            # JSON: {"symbol", "name", "shares", "value", "cost_basis"}
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class ExpenseRatioOverride(Base):
    """The household's expense ratio for a fund symbol, as a percent in text ("0.04"); it comes before the built-in
    table (steward.services.costs)."""
    __tablename__ = "expense_ratio_override"
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    ratio_pct: Mapped[str] = mapped_column(String(8))
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_by: Mapped[int] = mapped_column(Integer)


class Holding(Base):
    __tablename__ = "holding"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    as_of: Mapped[date] = mapped_column(Date)
    symbol: Mapped[str | None] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    shares_milli: Mapped[int] = mapped_column(Integer)  # shares * 1000
    cost_basis_cents: Mapped[int | None] = mapped_column(Integer)
    market_value_cents: Mapped[int] = mapped_column(Integer)
    expense_ratio_bp: Mapped[int | None] = mapped_column(Integer)  # basis points
    import_id: Mapped[int | None] = mapped_column(ForeignKey("positions_import.id", ondelete="SET NULL"))  # None: the feed


class BalanceSnapshot(Base):
    __tablename__ = "balance_snapshot"
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    balance_cents: Mapped[int] = mapped_column(Integer)


class Fact(Base):
    __tablename__ = "fact"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), index=True)
    value: Mapped[str] = mapped_column(Text)
    as_of: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


NICKNAME_MAX = 40


class MerchantRule(Base):
    """A household rule (phase 12; polish round P33-P35). pattern is a normalized raw description. amount_cents, when
    set, matches the signed row amount exactly, and that rule beats the plain one for its pattern where it has an
    opinion. category may be empty: a rule that names and notes rows but sorts nothing (P34). nickname and note label
    the rows it reaches at ingest, the note written by note_by under the name they had then (P37). Free text can hold
    names, so the advisor and the categorizer never read the label fields (tests/advisor/test_tools_never_read_notes.py)."""
    __tablename__ = "merchant_rule"
    id: Mapped[int] = mapped_column(primary_key=True)
    pattern: Mapped[str] = mapped_column(String(200))  # normalized raw description
    merchant: Mapped[str] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(40))
    is_business: Mapped[bool | None] = mapped_column(Boolean)
    source: Mapped[CategorySource] = mapped_column(Enum(CategorySource))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    amount_cents: Mapped[int | None] = mapped_column(Integer)
    nickname: Mapped[str | None] = mapped_column(String(NICKNAME_MAX))
    note: Mapped[str | None] = mapped_column(Text)
    note_by: Mapped[int | None] = mapped_column(Integer)          # a directory user id; no foreign key across files
    note_by_name: Mapped[str | None] = mapped_column(String(120))
    __table_args__ = (CheckConstraint("category IS NOT NULL OR nickname IS NOT NULL OR note IS NOT NULL",
                                      name="ck_merchant_rule_does_something"),
                      Index("uq_merchant_rule_pattern", "pattern", unique=True, sqlite_where=text("amount_cents IS NULL")),
                      Index("uq_merchant_rule_pattern_amount", "pattern", "amount_cents", unique=True,
                            sqlite_where=text("amount_cents IS NOT NULL")))


NOTE_MAX = 1000


class TransactionNote(Base):
    """A person's note on a transaction (phase 12 decision 18): who wrote it and when, several per transaction, newest
    last. Managers write and delete their own; viewers read. author_name is kept as it was when written. Free text can
    hold names, so the advisor's tools never read this table (tests/advisor/test_tools_never_read_notes.py)."""
    __tablename__ = "transaction_note"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transaction.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(Integer)      # a directory user id; no foreign key across files
    author_name: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


UNDO_MINUTES = 15


class UndoEntry(Base):
    """One Review action that can still be undone (sorting redesign spec, Undo): who did it, what, until when, and the
    before and after values of every transaction and merchant rule it changed (services/undo.py writes and reads it).
    It holds categories, flags, times and a rule's pattern and merchant; never a note. Nothing sends it to Claude or
    the gateway (tests/advisor/test_tools_never_read_notes.py)."""
    __tablename__ = "undo_entry"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)       # a directory user id; no foreign key across files
    action: Mapped[str] = mapped_column(String(12))     # sort | snooze | ignore
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, index=True)
    used_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    before: Mapped[str] = mapped_column(Text)
    after: Mapped[str] = mapped_column(Text)


class UndoText(Base):
    """The old text an undoable action replaced (polish round P36): a transaction's or a rule's name, a rule's note and
    who wrote it, keyed by the entry's token, so undo_entry never holds a note or a name. `written` is the text the
    action wrote: Undo refuses once the field no longer holds it. A merge's journal keeps here the text of the rows it
    deletes (model is the table, row_key the journal's key, written None), the old text of a name it carries onto
    a row it keeps (written the name carried), and the name of a row it makes (value None, written that name: Undo
    deletes the row only while it still holds it). Rows go when their entry is used or expires.
    Never read by the advisor (tests/advisor/test_tools_never_read_notes.py)."""
    __tablename__ = "undo_text"
    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(20))       # txn | rule, or the table a merge deleted the row from
    row_key: Mapped[str] = mapped_column(String(40))
    field: Mapped[str] = mapped_column(String(20))
    value: Mapped[str | None] = mapped_column(Text)
    written: Mapped[str | None] = mapped_column(Text)


REIMBURSE_SOURCES: tuple[str, ...] = ("none", "manual", "rule")


class Reimburser(Base):
    """Who pays the household back for work expenses (reimbursable spec, decision 6): "Acme". Unique in the book
    (services/reimburse.py also compares without case), 1-60 characters with spaces tidied. Household data, like a
    category: never sent to the gateway or Claude."""
    __tablename__ = "reimburser"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    __table_args__ = (CheckConstraint("length(name) BETWEEN 1 AND 60", name="ck_reimburser_name"),)


class Trip(Base):
    """A work trip (decision 4): a name, its first and last days, optionally a city ("Chicago" or "Chicago, IL"), and
    who pays it back. Its charges carry trip_id."""
    __tablename__ = "trip"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    start: Mapped[date] = mapped_column(Date)
    end: Mapped[date] = mapped_column(Date)
    city: Mapped[str | None] = mapped_column(String(60))
    reimburser_id: Mapped[int] = mapped_column(ForeignKey("reimburser.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(Integer)     # a directory user id; no foreign key across files
    __table_args__ = (CheckConstraint('"end" >= start', name="ck_trip_dates"),)


class ReimburseRule(Base):
    """'Always reimbursable for <description>' (decision 3), and a repayment's payer remembered (engineering choice
    5): a normalized description, as merchant_rule's pattern, and the payer."""
    __tablename__ = "reimburse_rule"
    id: Mapped[int] = mapped_column(primary_key=True)
    pattern: Mapped[str] = mapped_column(String(200), unique=True)
    reimburser_id: Mapped[int] = mapped_column(ForeignKey("reimburser.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class ReimburseSettlement(Base):
    """A leftover balance settled as not coming back (decision 7). It counts as the household's spending in `category`,
    in the household month of settled_at (vault_flows.settlements_by_month)."""
    __tablename__ = "reimburse_settlement"
    id: Mapped[int] = mapped_column(primary_key=True)
    reimburser_id: Mapped[int] = mapped_column(ForeignKey("reimburser.id", ondelete="RESTRICT"))
    amount_cents: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(40))
    settled_at: Mapped[datetime] = mapped_column(TZDateTime)
    created_by: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint("amount_cents > 0", name="ck_reimburse_settlement_amount"),)


class ImportBatch(Base):
    __tablename__ = "import_batch"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    filename: Mapped[str] = mapped_column(String(200))
    format: Mapped[str] = mapped_column(String(40))
    row_count: Mapped[int] = mapped_column(Integer)
    imported_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    imported_by: Mapped[int] = mapped_column(Integer)  # a directory user id; no foreign key across files (spec 2.2)
    rolled_back_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    # Import/export spec (0035): the batch it came in with (None for imports before 0035, shown as batches of one),
    # the remembered layout it was read with, and the file's SHA-256 (P38: "imported on Oct 12").
    set_id: Mapped[int | None] = mapped_column(ForeignKey("import_set.id"))
    layout_id: Mapped[int | None] = mapped_column(ForeignKey("import_layout.id", ondelete="SET NULL"))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    # PDF statements spec (0036): one batch per statement and account. The period, the pages, the balance check
    # (adds_up | anyway, with the gap), the remembered layout it was read with, and the snapshot it wrote (its date and
    # value, so Undo deletes it only while unchanged; plan Engineering choice 7). NULL for CSV and OFX files.
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    pages: Mapped[int | None] = mapped_column(Integer)
    check_state: Mapped[str | None] = mapped_column(String(8))
    check_gap_cents: Mapped[int | None] = mapped_column(Integer)
    statement_layout_id: Mapped[int | None] = mapped_column(ForeignKey("statement_layout.id", ondelete="SET NULL"))
    snapshot_as_of: Mapped[date | None] = mapped_column(Date)
    snapshot_cents: Mapped[int | None] = mapped_column(Integer)


class ImportSet(Base):
    """One batch of files imported together (import/export spec P20): one Undo removes every file still in."""
    __tablename__ = "import_set"
    id: Mapped[int] = mapped_column(primary_key=True)
    imported_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    imported_by: Mapped[int] = mapped_column(Integer)  # a directory user id; no foreign key across files (spec 2.2)
    rolled_back_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class ImportLayout(Base):
    """A bank CSV's layout a person confirmed (import/export spec P14), keyed by its normalized header's hash
    ("h:<sha256>") or a headerless file's shapes ("n:<cols>:<shape>"), so the next file like it asks nothing. header
    holds the column names as written, never a data cell. mapping is {field: column index}. forgotten_at is Forget's
    soft delete (plan Engineering choice 1). Per book; the advisor never reads it."""
    __tablename__ = "import_layout"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    label: Mapped[str] = mapped_column(String(60))
    header: Mapped[str] = mapped_column(Text)            # JSON list of the header's cells as written
    mapping: Mapped[str] = mapped_column(Text)           # JSON {field: column index}
    negate: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    date_format: Mapped[str] = mapped_column(String(24))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    uses: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    forgotten_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class ImportHint(Base):
    """Which account an OFX statement went to (import/export spec P5): "ofx:<ORG or BANKID>:<last 4 of ACCTID>".
    Never the full account number."""
    __tablename__ = "import_hint"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"))
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class StatementLayout(Base):
    """A statement layout a person confirmed with "Looks right" (PDF statements spec P23, P24): the digit-free
    fingerprint's key and anchors, and the validated proposal (labels and fields only, never a value from a page).
    forgotten_at is Forget's soft delete (plan Engineering choice 8). Per book; the advisor never reads it."""
    __tablename__ = "statement_layout"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    label: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(12))
    anchors: Mapped[str] = mapped_column(Text)
    rules: Mapped[str] = mapped_column(Text)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id", ondelete="SET NULL"))
    model: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    confirmed_by: Mapped[int] = mapped_column(Integer)          # a directory user id; no foreign key across files
    last_used_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    uses: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    forgotten_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class StatementStage(Base):
    """One staged PDF statement (PDF statements spec P2-P4, P32): book-wide among managers, seven days from its last
    change. Never the PDF itself (its bytes live in the reader's memory only): the lines it extracted (account numbers
    masked, P14), the rows read, the statement's facts and the check. Never in undo_entry; the encrypted export
    empties it (P50); the advisor never reads it."""
    __tablename__ = "statement_stage"
    id: Mapped[int] = mapped_column(primary_key=True)
    added_by: Mapped[int] = mapped_column(Integer)              # a directory user id; no foreign key across files
    added_at: Mapped[datetime] = mapped_column(TZDateTime)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)
    warned_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    removed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    filename: Mapped[str] = mapped_column(String(200))
    bytes: Mapped[int] = mapped_column(Integer)
    pages: Mapped[int | None] = mapped_column(Integer)
    pages_done: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    content_sha256: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str | None] = mapped_column(String(8))          # text | scan | mixed
    state: Mapped[str] = mapped_column(String(10))
    error: Mapped[str | None] = mapped_column(String(24))        # a copy key, never free text
    tries: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    layout_id: Mapped[int | None] = mapped_column(ForeignKey("statement_layout.id", ondelete="SET NULL"))
    proposal: Mapped[str | None] = mapped_column(Text, deferred=True)
    lines: Mapped[str | None] = mapped_column(Text, deferred=True)
    statement: Mapped[str | None] = mapped_column(Text, deferred=True)
    rows: Mapped[str | None] = mapped_column(Text, deferred=True)
    holdings: Mapped[str | None] = mapped_column(Text, deferred=True)
    gap_cents: Mapped[int | None] = mapped_column(Integer)
    anyway: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id", ondelete="SET NULL"))
    suggested_by: Mapped[str | None] = mapped_column(String(8))
    part: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    __table_args__ = (Index("ix_statement_stage_state", "state"), Index("ix_statement_stage_expires_at", "expires_at"))


class EventLog(Base):
    __tablename__ = "event_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(10))  # info|warn|error
    kind: Mapped[str] = mapped_column(String(40))   # sync|import|auth|system
    message: Mapped[str] = mapped_column(Text)      # plain words, shown in Settings
    actionable: Mapped[bool] = mapped_column(Boolean, default=False)  # shown on Home
    resolved_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class DuplicateKeep(Base):
    """A pair the household looked at and decided are two real transactions. a_id < b_id."""
    __tablename__ = "duplicate_keep"
    a_id: Mapped[int] = mapped_column(ForeignKey("transaction.id"), primary_key=True)
    b_id: Mapped[int] = mapped_column(ForeignKey("transaction.id"), primary_key=True)
    kept_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


PERSONS: tuple[str, ...] = ("jr", "spouse")
ASSET_CLASSES: tuple[str, ...] = ("us_stock", "intl_stock", "bond", "cash")
COLLEGE_COST_LEVELS: tuple[str, ...] = ("two_year", "in_state_public", "out_of_state_public", "private", "not_sure")


class Plan(Base):
    """One save of the household plan. The newest row is the plan; earlier rows are its history (spec 2.4)."""
    __tablename__ = "plan"
    id: Mapped[int] = mapped_column(primary_key=True)
    saved_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)
    saved_by: Mapped[int] = mapped_column(Integer)  # a directory user id; no foreign key across files (spec 2.2)
    levers: Mapped[str] = mapped_column(Text)            # JSON: {"assumed": {...}, "try": {...}, "pinned": [...]}
    engine_version: Mapped[str] = mapped_column(String(20))
    comfortable_age: Mapped[int | None] = mapped_column(Integer)
    likely_age: Mapped[int | None] = mapped_column(Integer)
    # JSON: what this save was worked out from (plan subpages; services/plan.inputs_summary). NULL before 0026.
    inputs_summary: Mapped[str | None] = mapped_column(Text)


class SsEarnings(Base):
    """Years and Social Security taxed earnings from a my Social Security record. Nothing else from the file."""
    __tablename__ = "ss_earnings"
    person: Mapped[str] = mapped_column(String(6), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    earnings_cents: Mapped[int] = mapped_column(Integer)
    imported_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    __table_args__ = (CheckConstraint("person IN ('jr', 'spouse')", name="ck_ss_earnings_person"),)


class Child(Base):
    """A kid for college planning (profile spec): their name (`label`, 40 characters, P8), birth year, school
    (`cost_level`; not_sure is counted as in_state_public, P9), the share of college the household plans to cover and
    whether that includes living costs, their 529 and its monthly amount. A removed kid keeps the row with removed_at
    set until the undo window passes (P27); everything except Undo skips it (active_children)."""
    __tablename__ = "child"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(40))
    birth_year: Mapped[int] = mapped_column(Integer)
    cost_level: Mapped[str] = mapped_column(String(20))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"))
    monthly_contribution_cents: Mapped[int] = mapped_column(Integer, default=0)
    share_pct: Mapped[int] = mapped_column(Integer, default=100, server_default=text("100"))
    covers_living: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    removed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    __table_args__ = (
        UniqueConstraint("account_id", name="uq_child_account"),
        CheckConstraint("cost_level IN ('two_year', 'in_state_public', 'out_of_state_public', 'private', 'not_sure')",
                        name="ck_child_cost_level"),
        CheckConstraint("share_pct BETWEEN 0 AND 100 AND share_pct % 10 = 0", name="ck_child_share_pct"),
    )


def active_children():
    """Every kid not removed, in birth order: the order the Plan, Profile and Ask list them in."""
    return select(Child).where(Child.removed_at.is_(None)).order_by(Child.birth_year, Child.id)


class AssetClass(Base):
    """The household's asset-class choice for a fund symbol. Built-ins live in steward.services.asset_classes."""
    __tablename__ = "asset_class"
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    asset_class: Mapped[str] = mapped_column("class", String(12))
    source: Mapped[str] = mapped_column(String(8), default="override")
    __table_args__ = (
        CheckConstraint("class IN ('us_stock', 'intl_stock', 'bond', 'cash')", name="ck_asset_class_class"),
        CheckConstraint("source IN ('builtin', 'override')", name="ck_asset_class_source"),
    )


PROFILE_SECTIONS: tuple[str, ...] = ("you", "kids", "home", "benefits", "banks")
STEP_STATUSES: tuple[str, ...] = ("done", "skipped", "doesnt_apply")


class SetupStep(Base):
    """The household's last answer to one Profile section, who gave it when, and the step its guided flow resumes at
    (P6). No row means not started; a row with no status holds only a resume point. A section whose data is complete
    counts as done whatever this row says (services/profile.py)."""
    __tablename__ = "setup_step"
    step: Mapped[str] = mapped_column(String(10), primary_key=True)
    status: Mapped[str | None] = mapped_column(String(12))
    user_id: Mapped[int] = mapped_column(Integer)  # a directory user id; no foreign key across files (spec 2.2)
    at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    resume_step: Mapped[str | None] = mapped_column(String(20))
    __table_args__ = (
        CheckConstraint("step IN ('you', 'kids', 'home', 'benefits', 'banks')", name="ck_setup_step_step"),
        CheckConstraint("status IN ('done', 'skipped', 'doesnt_apply')", name="ck_setup_step_status"),
    )


class UserSetup(Base):
    """One person's own Profile marks: saw the welcome band, confirmed their name and birthday, and until when Home's
    profile line is hidden (Later, P5)."""
    __tablename__ = "user_setup"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)  # a directory user id; no foreign key across files (spec 2.2)
    seen_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    later_until: Mapped[datetime | None] = mapped_column(TZDateTime)


class HomeVisit(Base):
    """When one person last looked at Home in this book (Home spec, Since you last looked; P27, P28). seen_at is the
    newest full look's mark (10 seconds on screen), glanced_at the newest glance's (Home reached ready). Both are the
    server's own times, sent back by the web, and each only moves later. Per-person behaviour data: only its owner's
    row is read or written; it is never in another person's answer, the change record, the undo journal or a log
    line; no advisor module reads it."""
    __tablename__ = "home_visit"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)  # a directory user id; no foreign key across files (spec 2.2)
    seen_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    glanced_at: Mapped[datetime | None] = mapped_column(TZDateTime)


INVENTORY_KINDS: tuple[str, ...] = ("account", "income", "insurance", "document", "contact")
ITEM_STATUSES: tuple[str, ...] = ("confirmed", "needs_checking", "closed")
DATA_SOURCES: tuple[str, ...] = ("feed", "statement", "manual")
SUGGESTION_STATUSES: tuple[str, ...] = ("open", "added", "linked", "dismissed")
TAX_FORMS: tuple[str, ...] = ("1099-INT", "1099-DIV", "1099-R", "SSA-1099")


class InventoryItem(Base):
    """One thing a parent has (spec 3.1). full_number never leaves the item page's Show button (design pass 5);
    everything else shows last4. created_by/updated_by are directory user ids, None for the bank feed."""
    __tablename__ = "inventory_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(120))
    owner: Mapped[str] = mapped_column(String(40))
    institution: Mapped[str | None] = mapped_column(String(120))
    last4: Mapped[str | None] = mapped_column(String(4))
    full_number: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(14), index=True)
    check_reason: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str | None] = mapped_column(String(10))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"))
    details: Mapped[str] = mapped_column(Text, default="{}")
    login_kept_in: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(Integer)
    closed_on: Mapped[date | None] = mapped_column(Date)
    closed_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("account_id", name="uq_inventory_item_account"),
        CheckConstraint("kind IN ('account', 'income', 'insurance', 'document', 'contact')", name="ck_inventory_item_kind"),
        CheckConstraint("status IN ('confirmed', 'needs_checking', 'closed')", name="ck_inventory_item_status"),
        CheckConstraint("data_source IS NULL OR data_source IN ('feed', 'statement', 'manual')",
                        name="ck_inventory_item_data_source"),
    )


class StoredFile(Base):
    """An uploaded file's facts (spec 3.5). The bytes are encrypted at data/books/<slug>/files/<id>."""
    __tablename__ = "file"
    # AUTOINCREMENT: an id is never reused, so a backup's <id> ciphertext (AAD names the id) can't be swapped (review 10.1).
    __table_args__ = {"sqlite_autoincrement": True}
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_item.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(60))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    uploaded_by: Mapped[int] = mapped_column(Integer)


class ChangeRecord(Base):
    """Every manager write in a parent book (spec 5). user_id None is the bank feed or start-up (ruling 13).
    before/after hold changed fields as JSON, with numbers already masked to their last 4."""
    __tablename__ = "change_record"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(24))
    target_type: Mapped[str] = mapped_column(String(12))
    target_id: Mapped[int | None] = mapped_column(Integer)
    item_id: Mapped[int | None] = mapped_column(Integer, index=True)
    before: Mapped[str | None] = mapped_column(Text)
    after: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)


class Suggestion(Base):
    """A possible item found in the book's transactions or tax forms (spec 3.3), one per kind and payer."""
    __tablename__ = "suggestion"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    payer_key: Mapped[str] = mapped_column(String(120))
    payer_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(10), index=True)
    details: Mapped[str] = mapped_column(Text, default="{}")
    evidence: Mapped[str] = mapped_column(Text, default="{}")
    item_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_item.id"))
    undo: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    answered_by: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("kind", "payer_key", name="uq_suggestion_kind_payer"),
        CheckConstraint("status IN ('open', 'added', 'linked', 'dismissed')", name="ck_suggestion_status"),
    )


class TaxForm(Base):
    """A tax form typed in or imported from a CSV (spec 3.3). Amounts in boxes are cents; box_7 is text."""
    __tablename__ = "tax_form"
    id: Mapped[int] = mapped_column(primary_key=True)
    form: Mapped[str] = mapped_column(String(10))
    tax_year: Mapped[int] = mapped_column(Integer)
    recipient: Mapped[str] = mapped_column(String(40))
    payer: Mapped[str] = mapped_column(String(120))
    payer_key: Mapped[str] = mapped_column(String(120), index=True)
    last4: Mapped[str | None] = mapped_column(String(4))
    boxes: Mapped[str] = mapped_column(Text, default="{}")
    file_id: Mapped[int | None] = mapped_column(ForeignKey("file.id"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    created_by: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        CheckConstraint("form IN ('1099-INT', '1099-DIV', '1099-R', 'SSA-1099')", name="ck_tax_form_form"),
    )


FLAG_CHECKS: tuple[str, ...] = ("scam", "payee", "large", "unusual", "cash", "monthly", "duplicate", "deposit",
                                "premium", "account", "low")
FLAG_STATUSES: tuple[str, ...] = ("open", "checking", "expected", "handled", "arrived")
FLAG_EVENTS: tuple[str, ...] = ("flagged", "emailed", "summary", "email_failed", "paid", "arrived")
OUTBOX_KINDS: tuple[str, ...] = ("urgent", "summary")
OUTBOX_STATUSES: tuple[str, ...] = ("pending", "sent", "failed", "skipped")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Flag(Base):
    """Something the checks found (spec 4.1; watching decisions 3 and 6). One per transaction: the most serious check
    names it and the others are in `also` (JSON list of {check, detail}). `summary` is the fact after the check's
    name ("$500.00 gift card at CVS Pharmacy"); `facts` keeps what the page and the emails show, so a flag still reads
    right after its transaction is removed, which is why transaction_id has no foreign key."""
    __tablename__ = "flag"
    id: Mapped[int] = mapped_column(primary_key=True)
    check: Mapped[str] = mapped_column("check_name", String(10), index=True)
    severity: Mapped[str] = mapped_column(String(6))
    status: Mapped[str] = mapped_column(String(10), index=True)
    transaction_id: Mapped[int | None] = mapped_column(Integer)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_item.id"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"))
    due_on: Mapped[date | None] = mapped_column(Date)
    summary: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    facts: Mapped[str] = mapped_column(Text, default="{}")
    also: Mapped[str] = mapped_column(Text, default="[]")
    note: Mapped[str | None] = mapped_column(Text)
    status_by: Mapped[int | None] = mapped_column(Integer)    # directory user id of the last person to mark it
    status_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    resolved_by: Mapped[int | None] = mapped_column(Integer)  # None with resolved_at set: closed by the checks
    summarized_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    __table_args__ = (
        UniqueConstraint("transaction_id", name="uq_flag_transaction"),
        UniqueConstraint("check_name", "item_id", "due_on", name="uq_flag_due"),
        CheckConstraint(_in("check_name", FLAG_CHECKS), name="ck_flag_check"),
        CheckConstraint("severity IN ('urgent', 'normal')", name="ck_flag_severity"),
        CheckConstraint(_in("status", FLAG_STATUSES), name="ck_flag_status"),
    )


class FlagEvent(Base):
    """A line in a flag's History that no person wrote: flagged, emailed, in the daily summary, an email that failed,
    a late payment seen (README screen 8). user_ids is a JSON list of directory ids; detail is JSON."""
    __tablename__ = "flag_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    flag_id: Mapped[int] = mapped_column(ForeignKey("flag.id"), index=True)
    at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    kind: Mapped[str] = mapped_column(String(14))
    user_ids: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text, default="{}")
    __table_args__ = (CheckConstraint(_in("kind", FLAG_EVENTS), name="ck_flag_event_kind"),)


class WatchKnown(Base):
    """A known payee (decision 1), added by marking a flag Expected. low/high None means any amount. Removing one
    keeps the row with removed_at, so the change record can name it."""
    __tablename__ = "watch_known"
    id: Mapped[int] = mapped_column(primary_key=True)
    payee_key: Mapped[str] = mapped_column(String(120), index=True)
    payee_name: Mapped[str] = mapped_column(String(160))
    low_cents: Mapped[int | None] = mapped_column(Integer)
    high_cents: Mapped[int | None] = mapped_column(Integer)
    check: Mapped[str] = mapped_column("check_name", String(10))  # the check of the flag it came from
    flag_id: Mapped[int | None] = mapped_column(ForeignKey("flag.id"))
    added_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    added_by: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    removed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    removed_by: Mapped[int | None] = mapped_column(Integer)


class WatchState(Base):
    """Per-book settings and the watcher's own marks: large_cents, last_run, daily_on, summary_on, feed_accounts,
    low:<account id>. Values are text (JSON where steward.watch.store says so)."""
    __tablename__ = "watch_state"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class WatchRecipient(Base):
    """One person's email switches for this book (decision 4). No row: managers get both, viewers neither."""
    __tablename__ = "watch_recipient"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)   # a directory user id
    urgent: Mapped[bool] = mapped_column(Boolean)
    summary: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(Integer)


class MailOutbox(Base):
    """An email waiting to go, kept in the book so retries survive a restart (spec 8). Recipients (directory ids) and
    the rendered message are fixed at the first try; addresses are read from the directory at each try."""
    __tablename__ = "mail_outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))
    flag_id: Mapped[int | None] = mapped_column(ForeignKey("flag.id"))
    flag_ids: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(8), index=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    next_try_at: Mapped[datetime] = mapped_column(TZDateTime, index=True)
    tries: Mapped[int] = mapped_column(Integer, default=0)
    to_user_ids: Mapped[str | None] = mapped_column(Text)
    sent_to: Mapped[str] = mapped_column(Text, default="[]")
    subject: Mapped[str | None] = mapped_column(Text)
    text_body: Mapped[str | None] = mapped_column(Text)
    html_body: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    failed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    locked_since: Mapped[datetime | None] = mapped_column(TZDateTime)   # when the current streak of database locks began
    __table_args__ = (
        CheckConstraint(_in("kind", OUTBOX_KINDS), name="ck_mail_outbox_kind"),
        CheckConstraint(_in("status", OUTBOX_STATUSES), name="ck_mail_outbox_status"),
    )


ALIAS_KINDS: tuple[str, ...] = ("owner", "user", "child", "account", "payee")
OUTGOING_CHANNELS: tuple[str, ...] = ("chat", "mcp", "prewarm")
OUTGOING_PARTS: tuple[str, ...] = ("question", "tool_result", "merchant_rows", "system", "history_ref")
CHAT_ROLES: tuple[str, ...] = ("user", "assistant", "system")
CHAT_APPROVALS: tuple[str, ...] = ("approved", "declined", "viewer", "timeout")


class AdvisorAlias(Base):
    """What Claude calls a person, child, account or payee in this book (spec 4.2). Given once and never changed.
    target is text (owner keys and payee keys are strings; ruling 24). A household owner and the person who is that owner
    share one alias ("Person 1")."""
    __tablename__ = "advisor_alias"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))
    target: Mapped[str] = mapped_column(String(160))
    alias: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("kind", "target", name="uq_advisor_alias_target"),
                      CheckConstraint(_in("kind", ALIAS_KINDS), name="ck_advisor_alias_kind"))


class AdvisorOutgoing(Base):
    """One part of one request to Anthropic, written before it was sent (spec 4.6). seq is the request within the turn
    (ruling 9). payload is canonical JSON; sha256 and bytes are of exactly those bytes. The app never edits or deletes a
    row, and deleting a conversation keeps its rows."""
    __tablename__ = "advisor_outgoing"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)
    user_id: Mapped[int] = mapped_column(Integer)            # a directory user id
    conversation_id: Mapped[int | None] = mapped_column(Integer, index=True)
    turn_id: Mapped[str] = mapped_column(String(20), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(8))
    part: Mapped[str] = mapped_column(String(12))
    payload: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    bytes: Mapped[int] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(String(40))
    approved_by: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (CheckConstraint(_in("channel", OUTGOING_CHANNELS), name="ck_advisor_outgoing_channel"),
                      CheckConstraint(_in("part", OUTGOING_PARTS), name="ck_advisor_outgoing_part"))


class ChatConversation(Base):
    """One person's conversation in this book (spec 5.1). ended_at: a turn stopped between a tool request and its
    result, so the next question starts a new conversation (ruling 10). last_input_tokens is the last request's whole
    input (ruling 11)."""
    __tablename__ = "chat_conversation"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_input_tokens: Mapped[int] = mapped_column(Integer, default=0)


class ChatMessage(Base):
    """A message exactly as it was sent to or came from Anthropic, thinking blocks included, with the gateway's MAC
    (ruling 2). Conversations are append-only (spec 8.2)."""
    __tablename__ = "chat_message"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("chat_conversation.id"), index=True)
    turn_id: Mapped[str] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)               # the whole message as JSON
    mac: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(40))
    usage: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    __table_args__ = (CheckConstraint(_in("role", CHAT_ROLES), name="ck_chat_message_role"),)


class ChatTurn(Base):
    """One question and how it was answered (plan B ruling 1): what the person typed, what was sent, the replaced parts,
    the tools Claude used, how the turn ended with its time and cost, and any store-name approval. The typed text never
    leaves the NAS. Rows are written as the turn goes and kept when the conversation is deleted from the person's list."""
    __tablename__ = "chat_turn"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("chat_conversation.id"), index=True)
    turn_id: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[int] = mapped_column(Integer)
    asked: Mapped[str] = mapped_column(Text)
    sent: Mapped[str | None] = mapped_column(Text)
    chips: Mapped[str] = mapped_column(Text, default="[]")
    steps: Mapped[str] = mapped_column(Text, default="[]")
    stop: Mapped[str | None] = mapped_column(String(20))
    line: Mapped[str | None] = mapped_column(Text)
    cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    ms: Mapped[int] = mapped_column(Integer, default=0)
    approval: Mapped[str | None] = mapped_column(String(10))
    store_rows: Mapped[int] = mapped_column(Integer, default=0)
    approved_by: Mapped[int | None] = mapped_column(Integer)
    # What the question was asked about (Ask about this P9): the wire object, aliases and typed values only.
    about: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    __table_args__ = (UniqueConstraint("turn_id", name="uq_chat_turn_turn_id"),
                      CheckConstraint(_in("approval", CHAT_APPROVALS), name="ck_chat_turn_approval"))


class AdvisorState(Base):
    """Per-book chat settings: chat_on ("1" or "0"), with who changed it and when (ruling 16)."""
    __tablename__ = "advisor_state"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(Integer)


class ChatSeen(Base):
    """A person read the disclosure in this book (spec 5.4)."""
    __tablename__ = "chat_seen"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


BUSINESS_SOURCES: tuple[str, ...] = ("none", "manual", "rule", "account")
BUSINESS_RULE_KINDS: tuple[str, ...] = ("merchant", "account", "client")


class BusinessRule(Base):
    """'Charges from <merchant> on <account> are business (or N%)', '<payer> is a client', 'everything in <account> is
    business' (spec 5). pattern is a normalized description (merchant and client); account_id is set for merchant and
    account rules. line is a Schedule C line key or None for the category's default."""
    __tablename__ = "business_rule"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))
    pattern: Mapped[str | None] = mapped_column(String(200))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"), index=True)
    pct: Mapped[int] = mapped_column(Integer)
    line: Mapped[str | None] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(Integer)    # a directory user id; None for the demo seed
    __table_args__ = (CheckConstraint(_in("kind", BUSINESS_RULE_KINDS), name="ck_business_rule_kind"),
                      CheckConstraint("pct BETWEEN 1 AND 100", name="ck_business_rule_pct"))


class BusinessState(Base):
    """The household's business settings (ruling 12): type, home_office:<year>, car_method:<year>, miles:<year>,
    expect:<year>, s_corp. Values are text (JSON where steward.business.settings says so)."""
    __tablename__ = "business_state"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(Integer)


class CareSetup(Base):
    """Who Care is for and what it runs on (parent care plan ruling 3). One row, id 1."""
    __tablename__ = "care_setup"
    id: Mapped[int] = mapped_column(primary_key=True)
    person: Mapped[str] = mapped_column(String(40))                     # one of the book's owner keys, never "joint"
    birth_year: Mapped[int] = mapped_column(Integer)
    spouse_birth_year: Mapped[int | None] = mapped_column(Integer)      # set: a joint return, a household of two
    state: Mapped[str] = mapped_column(String(2))
    care_inflation_bp: Mapped[int] = mapped_column(Integer, default=400)
    spending_monthly_cents: Mapped[int | None] = mapped_column(Integer)  # typed in; None: from transactions
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (CheckConstraint("id = 1", name="ck_care_setup_one_row"),)


class CareScenario(Base):
    """One care scenario (spec 4.1): a level that starts now (start_year None) or in a year, and its levers."""
    __tablename__ = "care_scenario"
    id: Mapped[int] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String(16))
    start_year: Mapped[int | None] = mapped_column(Integer)
    hours_week: Mapped[int | None] = mapped_column(Integer)
    adult_day_days: Mapped[int | None] = mapped_column(Integer)
    room: Mapped[str | None] = mapped_column(String(8))
    sell_home_year: Mapped[int | None] = mapped_column(Integer)
    home_price_cents: Mapped[int | None] = mapped_column(Integer)
    home_basis_cents: Mapped[int | None] = mapped_column(Integer)
    selling_cost_bp: Mapped[int] = mapped_column(Integer, default=600)
    family_monthly_cents: Mapped[int] = mapped_column(Integer, default=0)
    spending_change_monthly_cents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (
        CheckConstraint("level IN ('at_home', 'in_home_help', 'assisted_living', 'memory_care', 'nursing_home')",
                        name="ck_care_scenario_level"),
        CheckConstraint("room IS NULL OR room IN ('shared', 'private')", name="ck_care_scenario_room"),
    )


class CareQuote(Base):
    """A family's quote for one care cost (spec 4.2); it replaces the typical figure."""
    __tablename__ = "care_quote"
    key: Mapped[str] = mapped_column(String(32), primary_key=True)     # one of steward.care.vocab.COST_KEYS
    cents: Mapped[int] = mapped_column(Integer)
    quoted_on: Mapped[date] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(Integer)



class TaxState(Base):
    """What the household enters for Taxes and the quarterly email's state (tax decisions ruling 21): return:<year>,
    withholding:<year>, payment:<transaction id>, email:<user id>, sent:<due date>. Values are text (JSON where
    steward.taxes.store says so)."""
    __tablename__ = "tax_state"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(Integer)


SPENDING_KINDS: tuple[str, ...] = ("everyday", "fixed", "commitment", "occasional")


class SpendingTarget(Base):
    """A category's kind and monthly target (phase 11b, Data; polish round P1). category is one Spending tracks
    (steward.services.spending.SPENDING_CATEGORIES); a category without a row takes its default kind and no target.
    Kinds as shown: everyday is Flexible, fixed a Bill, commitment a Commitment, occasional Once in a while.
    monthly_cents None means no target for a Flexible category and its usual for a Bill or a Commitment.
    check_after (P19): Keep on the monthly target check sets it to the first of the month three months on; the check
    asks about this category again from that day. Any change to the row clears it."""
    __tablename__ = "spending_target"
    category: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(12))
    monthly_cents: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(Integer)  # a directory user id; no foreign key across files (spec 2.2)
    check_after: Mapped[date | None] = mapped_column(Date)
    __table_args__ = (CheckConstraint("kind IN ('everyday', 'fixed', 'commitment', 'occasional')", name="ck_spending_target_kind"),
                      CheckConstraint("monthly_cents IS NULL OR monthly_cents >= 0", name="ck_spending_target_cents"))


class SpendingPrefs(Base):
    """When a category is running ahead (decision 12): more than warn_pct_bp above usual by today and at least
    warn_min_cents above it. One row, id 1; no row means the defaults."""
    __tablename__ = "spending_prefs"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    warn_pct_bp: Mapped[int] = mapped_column(Integer, default=1000)
    warn_min_cents: Mapped[int] = mapped_column(Integer, default=2500)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (CheckConstraint("id = 1", name="ck_spending_prefs_one_row"),)


SET_ASIDE_KINDS: tuple[str, ...] = ("yearly", "twice_yearly", "one_off")
MATCH_HOWS: tuple[str, ...] = ("auto", "hand", "refused", "skipped")
_SET_ASIDE_KIND_FIELDS = ("(kind = 'yearly' AND due_month IS NOT NULL AND due_day IS NOT NULL) OR "
                          "(kind = 'twice_yearly' AND due_month IS NOT NULL AND due_day IS NOT NULL "
                          "AND second_month IS NOT NULL AND second_day IS NOT NULL) OR "
                          "(kind = 'one_off' AND due_year IS NOT NULL AND due_month IS NOT NULL)")
_SET_ASIDE_MONTHS_DAYS = ("(due_month IS NULL OR due_month BETWEEN 1 AND 12) AND (due_day IS NULL OR due_day BETWEEN 1 AND 31) AND "
                          "(second_month IS NULL OR second_month BETWEEN 1 AND 12) AND (second_day IS NULL OR second_day BETWEEN 1 AND 31)")


class SetAside(Base):
    """A cost spread over the months until it is due (phase 11c spec, Kinds and Data). yearly: amount_cents a year on
    due_month/due_day; twice_yearly: amount_cents each on two dates; one_off: amount_cents once in due_year/due_month.
    first_month is the first of the month after it was added. estimate is JSON (steward.services.setasides): the item,
    installed year, model year and miles, lifespan and cost ranges, planned year, and whether a person confirmed it.
    Archived set-asides keep their matches for history and leave every total and the Plan."""
    __tablename__ = "set_aside"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(12))
    amount_cents: Mapped[int] = mapped_column(Integer)
    due_month: Mapped[int | None] = mapped_column(Integer)
    due_day: Mapped[int | None] = mapped_column(Integer)
    second_month: Mapped[int | None] = mapped_column(Integer)
    second_day: Mapped[int | None] = mapped_column(Integer)
    due_year: Mapped[int | None] = mapped_column(Integer)
    first_month: Mapped[date] = mapped_column(Date)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"), index=True)
    payee_key: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(40))
    estimate: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(Integer)   # a directory user id; no foreign key across files (spec 2.2)
    __table_args__ = (CheckConstraint(_in("kind", SET_ASIDE_KINDS), name="ck_set_aside_kind"),
                      CheckConstraint("amount_cents > 0", name="ck_set_aside_amount"),
                      CheckConstraint(_SET_ASIDE_KIND_FIELDS, name="ck_set_aside_kind_fields"),
                      CheckConstraint(_SET_ASIDE_MONTHS_DAYS, name="ck_set_aside_months_days"))


class SetAsideMatch(Base):
    """A payment matched to one installment (phase 11c, Matching). how: auto (Steward matched it), hand (a person
    did), refused (a person said "Not this one": the pairing is never offered again), skipped ("It was not due": no
    payment, the installment is settled). A payment has at most one row; an installment at most one unrefused row."""
    __tablename__ = "set_aside_match"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transaction.id"))
    set_aside_id: Mapped[int] = mapped_column(ForeignKey("set_aside.id"))
    due_on: Mapped[date] = mapped_column(Date)
    how: Mapped[str] = mapped_column(String(8))
    late: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (CheckConstraint(_in("how", MATCH_HOWS), name="ck_set_aside_match_how"),
                      CheckConstraint("(how = 'skipped' AND transaction_id IS NULL) OR (how <> 'skipped' AND transaction_id IS NOT NULL)",
                                      name="ck_set_aside_match_payment"),
                      Index("uq_set_aside_match_txn", "transaction_id", unique=True, sqlite_where=text("transaction_id IS NOT NULL")),
                      Index("uq_set_aside_match_due", "set_aside_id", "due_on", unique=True, sqlite_where=text("how <> 'refused'")))


class SetAsideDismissed(Base):
    """A suggestion a person said no to (phase 11c, Suggestions): that payee and category are not offered again
    until "Bring it back" deletes the row."""
    __tablename__ = "set_aside_dismissed"
    id: Mapped[int] = mapped_column(primary_key=True)
    payee_key: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("payee_key", "category", name="uq_set_aside_dismissed"),)


class AccountFeed(Base):
    """One SimpleFIN account that feeds a Steward account (same-account spec, Data): "sfin:<id>", unique in the book,
    and the connection's institution. name is the bank's own name for it, refreshed at each sync, so a person's rename
    (Account.name) doesn't hide a duplicate. An account has one feed, or several after a merge. Sync finds accounts by
    their feeds; Account.external_id stays the first feed's id for imports and older code."""
    __tablename__ = "account_feed"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(200), unique=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institution.id"))
    name: Mapped[str] = mapped_column(String(120))
    added_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class HeldFeed(Base):
    """A SimpleFIN account that looks like one already in the book (same-account spec, decision 2): it isn't ingested
    at all until a person answers. Its latest balance and up to 400 transactions wait here as JSON, in the book and
    encrypted like the rest; nothing sends them anywhere, and the advisor never reads this table. candidate_account_id
    is the account it looks like; if that account goes, the next sync brings this one in as a new account."""
    __tablename__ = "held_feed"
    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(200), unique=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institution.id"))
    name: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    candidate_account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id", ondelete="SET NULL"))
    balance_cents: Mapped[int] = mapped_column(Integer)
    balance_date: Mapped[date] = mapped_column(Date)
    payload: Mapped[str] = mapped_column(Text, default="[]")
    first_seen_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


SAME_ANSWERS: tuple[str, ...] = ("open", "different")


class SameAccountAnswer(Base):
    """A same-account question about two accounts already in the book, open until answered (the one-time check), or
    "they're different", remembered so Steward doesn't ask again. account_id is the older account (the one a merge
    keeps), other_account_id the newer. A held feed answered "different" keeps its held_external_id here too."""
    __tablename__ = "same_account_answer"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"))
    other_account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"))
    held_external_id: Mapped[str | None] = mapped_column(String(200))
    answer: Mapped[str] = mapped_column(String(10))
    match_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    answered_by: Mapped[int | None] = mapped_column(Integer)   # a directory user id; no foreign key across files
    __table_args__ = (CheckConstraint(_in("answer", SAME_ANSWERS), name="ck_same_account_answer"),
                      CheckConstraint("other_account_id IS NOT NULL OR held_external_id IS NOT NULL",
                                      name="ck_same_account_other"),
                      UniqueConstraint("account_id", "other_account_id", name="uq_same_account_pair"))


class FeedTxnAlias(Base):
    """A copy that was dropped because it matched a transaction already in the account (same-account spec, decision
    4): the copy's bank id, the feed it came from, and the transaction it copies. A copy matched once is never ingested
    again, even outside the 3-day window, and a transaction a feed's copy matched is not free for another copy from
    that feed. The advisor never reads this table."""
    __tablename__ = "feed_txn_alias"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"))
    feed_id: Mapped[int] = mapped_column(ForeignKey("account_feed.id", ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(String(200))
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transaction.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("account_id", "external_id", name="uq_feed_txn_alias"),)
