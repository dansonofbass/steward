"""Phase 12 decision 18: notes are free text that can hold names, so nothing on the way to Claude reads them."""
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import steward.advisor
from steward.db.models import Account, AccountType, CategorySource, MerchantRule, Transaction, TransactionNote
from steward.demo import seed, seed_people
from steward_boundary import tools as T
from tests.advisor.helpers import call

import steward.advisor
import steward_boundary
import steward_gateway

WORDS = ("StatementStage", "StatementLayout", "statement_stage", "statement_layout", "statement_page", "period_start",
         "services.statements", "statements_wire", "steward_pdf", "came_from")
FORBIDDEN = ("TransactionNote", "transaction_note", "nickname", "note_by", "UndoText", "undo_text")
TODAY = date(2026, 10, 20)


def test_no_advisor_or_boundary_module_mentions_the_notes_table():
    roots = [Path(steward.advisor.__file__).parent, Path(steward_boundary.__file__).parent]
    hits = [str(p) for root in roots for p in root.rglob("*.py") if any(w in p.read_text() for w in FORBIDDEN)]
    assert hits == []


def test_no_advisor_boundary_or_turn_module_mentions_statements():
    """P52: no advisor, boundary or turn module reads the statement tables, the page, the period or the reading code."""
    gw = Path(steward_gateway.__file__).parent
    files = [*Path(steward.advisor.__file__).parent.rglob("*.py"), *Path(steward_boundary.__file__).parent.rglob("*.py"),
             gw / "loop.py", gw / "prompt.py", *(gw / "mcp").rglob("*.py")]
    hits = [str(p) for p in files if p.name != "statements_wire.py" and any(w in p.read_text() for w in WORDS)]
    assert hits == []


def test_no_advisor_module_reuses_the_web_transaction_list_or_row():
    """The web's search (api/transactions.py) matches note text and its rows carry note_count; no advisor path may use it."""
    root = Path(steward.advisor.__file__).parent
    hits = [str(p) for p in root.rglob("*.py")
            if any(w in p.read_text() for w in ("api.transactions", "list_transactions", "transaction_row", "note_count"))]
    assert hits == []


@pytest.fixture
def household(books, ours, engine):
    with Session(engine) as db:
        seed(db, years=1, seed=7)
    with Session(books.directory) as ddb:
        seed_people(ddb, ours.id)
    return next(p.id for p in books.people(ours.id) if p.username == "alex")


def test_a_merchant_search_never_matches_or_returns_a_note(books, ours, engine, household):
    """A note's words must not be inferable from which rows a tool returns, nor appear in its output."""
    with Session(engine) as db:
        acct = db.scalar(select(Account.id).where(Account.type == AccountType.checking).order_by(Account.id))
        t = Transaction(account_id=acct, posted_at=date(2026, 10, 18), amount_cents=-1599, raw_description="STREAMBOX",
                        merchant="StreamBox", category="subscriptions", category_source=CategorySource.none)
        db.add(t)
        db.flush()
        db.add(TransactionNote(transaction_id=t.id, author_id=household, author_name="Alex",
                               body="zorblax for Dr. Alvarez", created_at=datetime(2026, 10, 19, tzinfo=timezone.utc)))
        db.commit()
    base = {"reason": "Totals can't name them.", "start": "2026-10-01", "end": "2026-10-20", "category": None}
    for payees in (None, ["zorblax"]):
        r = call(engine, ours, books.people(ours.id), household, T.MERCHANT, {**base, "payees": payees}, TODAY)
        out = json.dumps(r)
        assert "zorblax" not in out and "Alvarez" not in out and "note_count" not in out
    r = call(engine, ours, books.people(ours.id), household, T.MERCHANT, {**base, "payees": None}, TODAY)
    assert r["error"] is None
    assert any(x["merchant"] == "StreamBox" for x in r["content"]["rows"])


def test_no_advisor_or_boundary_module_reads_undo_entries():
    """Sorting redesign, Undo: entries are never sent to Claude or the gateway."""
    roots = [Path(steward.advisor.__file__).parent, Path(steward_boundary.__file__).parent]
    hits = [str(p) for root in roots for p in root.rglob("*.py")
            if any(w in p.read_text() for w in ("UndoEntry", "undo_entry", "services.undo"))]
    assert hits == []


def test_no_advisor_boundary_or_gateway_module_reads_payers_or_trips():
    """Reimbursable spec, Privacy: payer names, trips and their cities never reach Claude, the gateway or the
    categorizer."""
    import steward_gateway
    from steward.services import categorizer_client
    roots = [Path(steward.advisor.__file__).parent, Path(steward_boundary.__file__).parent,
             Path(steward_gateway.__file__).parent]
    words = ("Reimburser", "reimburser", "ReimburseRule", "reimburse_rule", "ReimburseSettlement",
             "reimburse_settlement", "trip_id", "Trip(", "services.trips", "services.reimburse")
    files = [p for root in roots for p in root.rglob("*.py")] + [Path(categorizer_client.__file__)]
    assert [str(p) for p in files if any(w in p.read_text() for w in words)] == []


def test_payer_names_and_nicknames_reach_the_advisor_only_as_names_to_remove():
    """Public issue #2: steward.services.held_names reads payer names, set-asides and nicknames for the exact pass, so a
    question that types one has it replaced. The only advisor module that calls it is identifiers.py, and what it
    returns becomes "[payee]" or "[name]"; the text itself is never a tool's result or part of what is sent."""
    import steward
    from steward.advisor.identifiers import Identifier  # noqa: F401 - the one caller
    src = Path(steward.__file__).parent
    callers = sorted(str(p.relative_to(src)) for p in src.rglob("*.py")
                     if "held_names" in p.read_text() and p.name != "held_names.py")
    assert callers == ["advisor/identifiers.py"]
    text = (src / "advisor/identifiers.py").read_text()
    assert 'add(text, kind, "[payee]" if kind == "payee" else "[name]")' in text


def test_no_advisor_boundary_or_gateway_module_reads_held_feeds_or_copies():
    """Same-account spec, Privacy: held payloads stay in the book; the advisor never reads held_feed, feed_txn_alias,
    same_account_answer or account_feed."""
    import steward_gateway
    roots = [Path(steward.advisor.__file__).parent, Path(steward_boundary.__file__).parent,
             Path(steward_gateway.__file__).parent]
    words = ("HeldFeed", "held_feed", "FeedTxnAlias", "feed_txn_alias", "same_account", "SameAccountAnswer",
             "AccountFeed", "account_feed")
    assert [str(p) for root in roots for p in root.rglob("*.py") if any(w in p.read_text() for w in words)] == []


def test_no_advisor_boundary_or_gateway_module_reads_fund_overrides_or_positions_imports():
    """Investment views spec, Privacy: fund cost overrides, remembered column mappings and import file names never
    reach Claude or the gateway."""
    import steward_gateway
    roots = [Path(steward.advisor.__file__).parent, Path(steward_boundary.__file__).parent,
             Path(steward_gateway.__file__).parent]
    words = ("ExpenseRatioOverride", "expense_ratio_override", "PositionsMapping", "positions_mapping", "PositionsImport",
             "positions_import", "services.positions")
    assert [str(p) for root in roots for p in root.rglob("*.py") if any(w in p.read_text() for w in words)] == []


def test_the_categorizer_client_never_mentions_notes_names_or_old_text():
    """P39: the categorizer sees a rule's pattern and category and nothing else."""
    from steward.services import categorizer_client
    text = Path(categorizer_client.__file__).read_text()
    assert [w for w in FORBIDDEN if w in text] == []


def test_a_nickname_and_a_rule_note_never_reach_the_advisor(books, ours, engine, household):
    """Polish round, Privacy: a row named "zorblax" and a rule note naming a doctor never surface, and naming a row
    doesn't make the merchant tool find it by that name."""
    base = {"reason": "Totals can't name them.", "start": "2026-10-01", "end": "2026-10-20", "category": None}
    ask = lambda payees: call(engine, ours, books.people(ours.id), household, T.MERCHANT, {**base, "payees": payees}, TODAY)   # noqa: E731
    with Session(engine) as db:
        acct = db.scalar(select(Account.id).where(Account.type == AccountType.checking).order_by(Account.id))
        t = Transaction(account_id=acct, posted_at=date(2026, 10, 18), amount_cents=-1599, raw_description="STREAMBOX",
                        merchant="StreamBox", category="subscriptions", category_source=CategorySource.none)
        db.add(t)
        db.commit()
        tid = t.id
    before = ask(["zorblax"])
    with Session(engine) as db:
        db.get(Transaction, tid).nickname = "zorblax"
        db.add(MerchantRule(pattern="STREAMBOX", merchant="StreamBox", category="subscriptions",
                            source=CategorySource.correction, note="for Dr. Alvarez", note_by=household, note_by_name="Alex"))
        db.commit()
    for payees in (None, ["zorblax"]):
        out = json.dumps(ask(payees))
        assert "zorblax" not in out and "Alvarez" not in out
    assert ask(["zorblax"])["content"] == before["content"]


def test_no_advisor_module_or_the_categorizer_reads_home_visits():
    """Home spec, Privacy: when someone last looked at Home is per-person behaviour data; nothing on the way to Claude,
    the gateway or the gateway reads it."""
    from steward.services import categorizer_client
    files = list(Path(steward.advisor.__file__).parent.rglob("*.py")) + [Path(categorizer_client.__file__)]
    words = ("HomeVisit", "home_visit", "home_since")
    assert [str(p) for p in files if any(w in p.read_text() for w in words)] == []


ABOUT_WORDS = ("title", "summary", "note", "merchant", "raw_description", "display_name", "nickname")


def about_files() -> list[Path]:
    return [Path(steward_boundary.__file__).parent / "about.py", Path(steward.advisor.__file__).parent / "about.py"]


def test_the_about_modules_never_mention_a_free_text_field():
    """Ask about this, Privacy tests: what a question is about is built from typed columns only."""
    assert [(str(f), w) for f in about_files() for w in ABOUT_WORDS if w in f.read_text()] == []


def test_no_advisor_boundary_or_gateway_module_reads_import_layouts_or_hints():
    """Import/export spec, Privacy: the advisor never reads import_layout or import_hint (a layout's header and an
    OFX account's last digits)."""
    import steward_gateway
    roots = [Path(steward.advisor.__file__).parent, Path(steward_boundary.__file__).parent,
             Path(steward_gateway.__file__).parent]
    words = ("ImportLayout", "import_layout", "ImportHint", "import_hint", "import_staging")
    assert [(str(p), w) for root in roots for p in root.rglob("*.py") for w in words if w in p.read_text()] == []


def test_no_advisor_boundary_or_gateway_module_reaches_the_export():
    """Import/export spec, Privacy: the advisor never reads the export services."""
    import steward_gateway
    roots = [Path(steward.advisor.__file__).parent, Path(steward_boundary.__file__).parent,
             Path(steward_gateway.__file__).parent]
    words = ("book_export", "book_restore", "export_csv", "api.exports")
    assert [(str(p), w) for root in roots for p in root.rglob("*.py") for w in words if w in p.read_text()] == []


def test_no_advisor_boundary_or_gateway_module_reads_where_a_row_came_from():
    """Came from (JR, Oct 31): the line and the file's name never reach the advisor, Ask's About or the gateway."""
    import steward_gateway
    roots = [Path(steward.advisor.__file__).parent, Path(steward_boundary.__file__).parent,
             Path(steward_gateway.__file__).parent]
    words = ("came_from", "came-from", "ImportBatch", "import_batch")
    assert [(str(p), w) for root in roots for p in root.rglob("*.py") for w in words if w in p.read_text()] == []
