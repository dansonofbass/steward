"""Who did what, after a restore (CLI restore): a book keeps directory user ids without a foreign key (spec 2.2), and on
another NAS the same id can be someone else. A restore puts RESTORED_BY in every attribution column that holds one,
and the screens name it "Someone, before this book was restored"."""
import json
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from steward.app import create_app
from steward.books.history import names_for
from steward.books.people import RESTORED_BY, RESTORED_BY_NAME, RESTORED_NAME
from steward.db.engine import make_engine
from steward.db.keys import ensure_key
from steward.db.models import (AdvisorAlias, AdvisorOutgoing, Base, CategorySource, ChangeRecord, ImportBatch, ImportSet, MerchantRule,
                               Plan, SetupStep, StoredFile, TaxState, Transaction, TransactionNote)
from steward.demo_care import seed_care
from steward.demo_parent import seed_parent
from steward.demo_watching import seed_watching
from steward.inventory.suggestions import refresh
from steward.services import book_export as X
from steward.services import book_restore as R
from steward.settings import Settings
from tests.factories import login, make_account, make_person
from tests.import_helpers import import_file

TODAY = date(2026, 10, 30)
NOW = datetime(2026, 10, 30, 19, 0, tzinfo=timezone.utc)
PASS = "a long enough passphrase"
SOURCE_ID = 77                     # a directory user id on the NAS the backup came from
ID_COLUMN = re.compile(r"(_by|user_id|user_ids|author_id)$")


def test_every_attribution_column_is_in_stewards_schema():
    """A misspelt name would be skipped silently (an older backup lacks some columns, so a restore skips what's
    missing)."""
    tables = {t.name: t for t in Base.metadata.sorted_tables}
    assert [f"{t}.{c}" for t, cols in R.ATTRIBUTION.items() for c in cols
            if t not in tables or c not in tables[t].c] == []


def test_every_directory_user_id_column_is_cleared_or_never_restored():
    """A new column holding a directory user id must join ATTRIBUTION, or its table RESTORE_BLANKS."""
    missing = [f"{t.name}.{c.name}" for t in Base.metadata.sorted_tables for c in t.columns
               if ID_COLUMN.search(c.name) and t.name not in X.RESTORE_BLANKS
               and c.name not in R.ATTRIBUTION.get(t.name, ()) and (t.name, c.name) not in R.ATTRIBUTION_JSON]
    assert missing == []


@pytest.fixture
def other(tmp_path):
    """A different NAS: another data dir and another steward.key."""
    from steward.books.registry import open_books
    s = Settings(_env_file=None, data_dir=tmp_path / "other", base_url="https://nas.tail1234.ts.net", env="test",
                 simplefin_hosts="testserver", web_dir=tmp_path / "no-web")
    ensure_key(s.key_path)
    reg = open_books(s)
    yield reg
    reg.dispose()


def _more_rows(db: Session, by: int) -> None:
    """Rows the parent demo doesn't make: Past imports (a row came from the file), a note, a rule's note, a plan, the
    sent log, a Profile answer, an email switch, a file, and two "changed someone's emails" lines."""
    txn = db.scalar(select(Transaction))
    s = ImportSet(imported_at=NOW, imported_by=by)
    db.add(s)
    db.flush()
    batch = ImportBatch(account_id=txn.account_id, filename="march.csv", format="csv", row_count=1, imported_at=NOW,
                        imported_by=by, set_id=s.id)
    db.add(batch)
    db.flush()
    txn.import_batch_id = batch.id
    db.add(TransactionNote(transaction_id=txn.id, author_id=by, author_name="JR", body="Paid back", created_at=NOW))
    db.add(MerchantRule(pattern="corner store", merchant="Corner Store", source=CategorySource.correction,
                        note="Ask Robert", note_by=by, note_by_name="JR"))
    db.add(Plan(saved_at=NOW, saved_by=by, levers="{}", engine_version="1"))
    db.add(AdvisorOutgoing(at=NOW, user_id=by, turn_id="t_000000000000000a", seq=1, channel="chat", part="question",
                           payload="{}", sha256="0" * 64, bytes=2, approved_by=by))
    db.add(SetupStep(step="you", status="done", user_id=by, at=NOW))
    db.add(TaxState(key=f"email:{by}", value="on", updated_at=NOW, updated_by=by))
    db.add(TaxState(key="return:2025", value="{}", updated_at=NOW, updated_by=by))
    db.add(StoredFile(name="statement.pdf", content_type="application/pdf", size=20, sha256="0" * 64, uploaded_by=by))
    db.add(AdvisorAlias(kind="user", target=str(by), alias="Person 2", created_at=NOW))
    for target in (SOURCE_ID, 78):
        db.add(ChangeRecord(at=NOW, user_id=by, action="watch.emails", target_type="watch", target_id=target,
                            before="{}", after="{}"))


@pytest.fixture
def backup(books, margaret, mdb, mctx, settings, tmp_path) -> tuple[Path, dict[str, int]]:
    """Margaret's book, seeded as the demo seeds it and then some, with every attribution column holding SOURCE_ID.
    Returns the backup and how many values each column held."""
    seed_parent(mdb, TODAY, by=mctx.user_id)
    seed_watching(mdb, TODAY, by=mctx.user_id)
    seed_care(mdb, TODAY)
    refresh(mdb, TODAY)                                     # the suggestions
    _more_rows(mdb, SOURCE_ID)
    mdb.commit()
    for fid in mdb.scalars(select(StoredFile.id)):
        books.file_store(margaret).write(fid, b"%PDF-1.4 statement")
    held: dict[str, int] = {}
    c = mdb.connection()
    for t, cols in R.ATTRIBUTION.items():
        for col in cols:
            c.execute(text(f'UPDATE "{t}" SET "{col}" = {SOURCE_ID}'))
            held[f"{t}.{col}"] = c.execute(text(f'SELECT count(*) FROM "{t}"')).scalar()
    held["tax_state.updated_by"] -= 1                       # the email switch goes (asserted below)
    c.execute(text(f"UPDATE flag_event SET user_ids = '[{SOURCE_ID}, 78]'"))
    held["flag_event.user_ids"] = c.execute(text("SELECT count(*) FROM flag_event")).scalar()
    mdb.commit()
    made = X.make(books, margaret, PASS, settings, TODAY, NOW)
    keep = tmp_path / "margaret.steward-backup"
    shutil.copyfile(made.path, keep)
    return keep, held


def _restore(other, path: Path):
    with Session(other.directory) as ddb:
        me = make_person(ddb, "jr").id
    info, _ = R.restore(other, path, PASS, None, [me], NOW)
    return info


def test_a_restored_book_keeps_no_source_nas_user_id(backup, other):
    path, held = backup
    named = ("import_batch.imported_by", "import_set.imported_by", "transaction_note.author_id", "plan.saved_by",
             "merchant_rule.note_by", "advisor_outgoing.user_id", "advisor_outgoing.approved_by", "file.uploaded_by",
             "inventory_item.created_by", "flag.status_by", "flag.resolved_by", "flag_event.user_ids",
             "watch_known.added_by", "change_record.user_id", "suggestion.answered_by", "setup_step.user_id",
             "tax_state.updated_by", "care_scenario.created_by")
    assert [k for k in named if not held[k]] == []          # the walk below sees real values in each of these
    info = _restore(other, path)
    eng = make_engine(other.path_for(info), other.key_for(info))
    with eng.connect() as c:
        for t, cols in R.ATTRIBUTION.items():
            for col in cols:
                left = c.execute(text(f'SELECT count(*) FROM "{t}" WHERE "{col}" IS NOT NULL AND "{col}" != 0')).scalar()
                restored = c.execute(text(f'SELECT count(*) FROM "{t}" WHERE "{col}" = 0')).scalar()
                assert (left, restored) == (0, held[f"{t}.{col}"]), f"{t}.{col}"
        assert set(c.execute(text("SELECT user_ids FROM flag_event")).scalars()) == {json.dumps([RESTORED_BY])}
        assert c.execute(text("SELECT key FROM tax_state ORDER BY key")).scalars().all() == ["return:2025"]
        # "changed their own emails" stays so; another person's emails are "someone's", never a name
        assert c.execute(text("SELECT target_id FROM change_record WHERE action = 'watch.emails' ORDER BY id")
                         ).scalars().all() == [RESTORED_BY, None]
        assert c.execute(text("SELECT author_name FROM transaction_note")).scalars().all() == ["JR"]   # stored: kept
        # Claude's alias for an old NAS person keeps its number but never matches a person here (ruling: aliases
        # never change); no user alias is keyed by a bare directory id
        users = c.execute(text("SELECT target, alias FROM advisor_alias WHERE kind = 'user'")).all()
        assert users == [(f"restored:{SOURCE_ID}", "Person 2")]
        assert not [t for t, _ in users if t.isdigit()]
    eng.dispose()


def test_came_from_and_the_sent_log_say_someone_before_the_restore(backup, other):
    """The screens name the old NAS's people for what they are here: unknown."""
    info = _restore(other, backup[0])
    eng = make_engine(other.path_for(info), other.key_for(info))
    with Session(eng) as db:
        tid = db.scalar(select(Transaction.id).where(Transaction.import_batch_id.is_not(None)))
    eng.dispose()
    with TestClient(create_app(other.settings, other), base_url="https://nas.tail1234.ts.net") as c:
        login(c, "jr")
        came = c.get(f"/api/b/{info.slug}/transactions/{tid}/came-from").json()["came_from"]
        assert (came["label"], came["by"]) == ("march.csv", RESTORED_BY_NAME)    # "imported Oct 30 by someone, ..."
        sent = c.get(f"/api/b/{info.slug}/chat/sent").json()["requests"]
        assert [r["who"] for r in sent] == [RESTORED_NAME]
        one = c.get(f"/api/b/{info.slug}/chat/sent/{sent[0]['key']}").json()
        assert (one["who"], one["approved_by"]) == (RESTORED_NAME, RESTORED_NAME)


def test_mid_sentence_the_wording_is_lowercase(db, ddb, ours):
    """"Plan saved by someone, before this book was restored": capitalized only where it starts a line."""
    from steward.books.people import attach_people
    from steward.services.plan import plan_out
    attach_people(db, lambda: ())
    p = Plan(saved_at=NOW, saved_by=RESTORED_BY, levers="{}", engine_version="1")
    db.add(p)
    db.flush()
    assert plan_out(db, p, True)["saved_by"]["name"] == RESTORED_BY_NAME == "someone, before this book was restored"


def test_names_for_names_a_restored_id(books, ddb):
    jr = make_person(ddb, "jr")
    assert names_for(books.directory, [jr.id, RESTORED_BY, None]) == {jr.id: "Jr", RESTORED_BY: RESTORED_NAME}
    assert names_for(books.directory, [jr.id]) == {jr.id: "Jr"}


def test_a_normal_book_still_names_its_people(client, db, ddb, ours):
    """Nothing restored: Came from names the person who imported the file, as before."""
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    card = make_account(db, "Card", type="credit")
    bid = import_file(client, "chase-card.csv", card.id).json()["batch_ids"][0]
    db.rollback()
    tid = db.scalar(select(Transaction.id).where(Transaction.import_batch_id == bid).limit(1))
    assert client.get(f"/api/b/ours/transactions/{tid}/came-from").json()["came_from"]["by"] == "Jr"


def test_after_a_restore_the_asker_is_never_told_they_are_an_old_alias(books, ours, engine, settings, other, tmp_path):
    """The old NAS's spouse had the id the asker has here. Claude must hear the asker as their own owner alias
    (Person 1, JR), never the old spouse's Person 2."""
    from steward.advisor.aliases import Aliases
    from steward.advisor.state import set_chat_on
    from steward.advisor.turn import AskEnv, run_turn, start_turn
    from steward.books.people import attach_people
    from steward.demo import seed, seed_people
    from tests.advisor.stubs import StubGateway
    with Session(engine) as db:
        seed(db, years=1, seed=7)
    with Session(books.directory) as ddb:
        seed_people(ddb, ours.id)
    old = {p.username: p.id for p in books.people(ours.id)}
    with Session(engine) as db:
        attach_people(db, lambda: books.people(ours.id))
        a = Aliases(db, ours, books.people(ours.id))
        assert (a.user(old["alex"]), a.user(old["spouse"])) == ("Person 1", "Person 2")
        set_chat_on(db, True, None, NOW)
        db.commit()
    path = tmp_path / "ours.steward-backup"
    shutil.copyfile(X.make(books, ours, PASS, settings, TODAY, NOW).path, path)
    with Session(other.directory) as ddb:                    # here, jr's id is the old spouse's
        for i in range(old["spouse"] - 1):
            make_person(ddb, f"filler{i}")
        me = make_person(ddb, "jr").id
    assert me == old["spouse"]
    info, _ = R.restore(other, path, PASS, None, [me], NOW)
    gw = StubGateway([{"type": "done", "stop": "end_turn", "line": None, "check": None, "path": None, "requests": 1,
                       "cost_nd": 0, "last_input_tokens": 0}])
    env = AskEnv(bind=other.engine_for(info).execution_options(immediate=True), directory=other.directory, book=info,
                 user_id=me, people=lambda: other.people(info.id), plan_cache=other.plan_cache(info.id), gateway=gw,
                 now=lambda: NOW, today=lambda: TODAY)
    list(run_turn(env, start_turn(env, "What's our net worth?", None)))
    assert gw.ws.sent[0]["context"]["asker"] == "Person 1"
