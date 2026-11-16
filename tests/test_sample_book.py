import shutil
import threading
from pathlib import Path
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward import clock
from steward.books.people import SAMPLE_PEOPLE
from steward.books.registry import household_book_id, household_name
from steward import demo
from steward.books.registry import BookInfo
from steward.books.sample_guard import SAMPLE_REFUSED, SampleRefused
from steward.deps import real_book_only
from steward.books.sample import HAS_SAMPLE, NO_SAMPLE, SAMPLE_FAILED, SAMPLE_GONE, sweep_removed
from steward.books.service import ONE_HOUSEHOLD, BookRefused, create_book
from steward.db.directory_models import Book, Membership, User
from steward.db.keys import book_key
from steward.db.models import BalanceSnapshot, Transaction
from tests.factories import login, make_person
from tests.test_isolation_sweep import api_routes, fill


def _sample(books, ddb, user_id):
    """A Sample's directory row and empty file, without the demo data (Task 3 adds the seeding route)."""
    return create_book(books, ddb, name="Sample", kind="household", by=user_id, sample_of=user_id)


def test_a_sample_is_never_the_household_book(books, ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    s = _sample(books, ddb, jr.id)
    assert s.sample and s.kind == "household" and s.key_scheme == "derived"
    assert household_book_id(ddb) == ours.id and household_name(ddb) == "Ours"
    ddb.get(Book, ours.id).archived_at = ddb.get(Book, ours.id).created_at   # with no household at all, still not the Sample
    ddb.commit()
    assert household_book_id(ddb) is None and household_name(ddb) == "the household book"


def test_books_leaves_samples_out_unless_asked(books, ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    s = _sample(books, ddb, jr.id)
    assert s.id not in {b.id for b in books.books()}
    assert s.id in {b.id for b in books.books(include_samples=True)}
    assert books.book(s.slug).sample is True                          # by its address it is still found


def test_only_the_sample_path_bypasses_the_one_household_rule(books, ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    _sample(books, ddb, jr.id)
    for kw in ({}, {"allow_household": True}):
        with pytest.raises(BookRefused, match=ONE_HOUSEHOLD):
            create_book(books, ddb, name="Second", kind="household", **kw)
    with pytest.raises(BookRefused):
        create_book(books, ddb, name="Odd", kind="parent", owner_labels=["Lee"], sample_of=jr.id)   # a Sample is household


def test_post_books_still_never_makes_a_household_book(client, books, ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    _sample(books, ddb, jr.id)
    login(client, "jr")
    r = client.post("/api/books", json={"name": "Mine", "kind": "household", "sample_of": jr.id})
    assert (r.status_code, r.json()) == (422, {"error": ONE_HOUSEHOLD})
    assert ddb.scalar(select(Book.id).where(Book.name == "Mine")) is None


@pytest.fixture
def fast_sample(monkeypatch):
    monkeypatch.setattr("steward.books.sample.YEARS", 1)     # plan D17: the same logic, half the rows


@pytest.fixture
def boss(client, ddb, ours, fast_sample):
    u = make_person(ddb, "boss", [(ours.id, "manager")])
    login(client, "boss")
    return u


def _make(client):
    r = client.post("/api/books/sample")
    assert r.status_code in (200, 201), r.text
    return r.json()["book"]


def test_the_sample_has_its_own_key_file_and_figures_that_end_today(client, books, ours, boss):
    info = books.book(_make(client)["slug"])
    assert info.sample and info.file == f"books/{info.slug}/book.db" and books.path_for(info).exists()
    assert books.key_for(info) == book_key(books.master, info.id) != books.key_for(ours)
    with Session(books.engine_for(info)) as s:
        assert s.scalar(select(func.max(BalanceSnapshot.as_of))) == date(2026, 10, 30)
        assert s.scalar(select(func.max(Transaction.posted_at))) <= date(2026, 10, 30)


def test_no_person_is_made_and_its_maker_is_its_only_member_already_welcomed(client, books, ddb, boss):
    people = ddb.scalar(select(func.count()).select_from(User))
    info = books.book(_make(client)["slug"])
    ddb.rollback()
    assert ddb.scalar(select(func.count()).select_from(User)) == people
    assert ddb.scalar(select(User.id).where(User.username.in_(("jr", "spouse")))) is None   # no demo password exists
    rows = ddb.scalars(select(Membership).where(Membership.book_id == info.id)).all()
    assert [(m.user_id, m.role) for m in rows] == [(boss.id, "manager")] and rows[0].welcome_seen_at is not None


def test_one_per_person_and_only_its_maker_sees_it(client, books, ddb, ours, boss):
    first = _make(client)
    again = client.post("/api/books/sample")
    assert again.status_code == 200 and again.json()["book"]["slug"] == first["slug"]
    make_person(ddb, "pat", [(ours.id, "manager")])
    login(client, "pat")
    assert first["slug"] not in [b["slug"] for b in client.get("/api/auth/me").json()["books"]]
    assert _make(client)["slug"] != first["slug"]


def test_its_household_people_are_alex_and_sam(client, books, boss):
    book = _make(client)
    assert {o["key"]: o["label"] for o in book["owners"]}["jr"] == "Alex"
    assert {o["key"]: o["label"] for o in book["owners"]}["spouse"] == "Sam"
    assert books.people(books.book(book["slug"]).id)[:2] == SAMPLE_PEOPLE


def test_remove_archives_it_and_undo_brings_it_back_within_15_minutes(client, books, fake_clock, boss):
    slug = _make(client)["slug"]
    r = client.delete("/api/books/sample")
    assert r.json() == {"removed": slug, "household": "ours"}
    assert client.get(f"/api/b/{slug}/accounts").status_code == 404
    fake_clock.advance(timedelta(minutes=14))
    assert client.post("/api/books/sample/restore").json()["book"]["slug"] == slug
    assert client.get(f"/api/b/{slug}/accounts").status_code == 200


def test_undo_after_15_minutes_or_after_the_sweep_is_refused(app, client, books, ddb, fake_clock, boss):
    info = books.book(_make(client)["slug"])
    client.delete("/api/books/sample")
    fake_clock.advance(timedelta(minutes=16))
    r = client.post("/api/books/sample/restore")
    assert (r.status_code, r.json()) == (404, {"error": SAMPLE_GONE})
    app.state.watch_job()                                   # the watcher's tick sweeps it
    assert not books.path_for(info).parent.exists()
    ddb.rollback()
    assert ddb.get(Book, info.id).archived_at is not None    # the row stays, for membership_change's keys
    assert sweep_removed(books, clock.now()) == 0


def test_undo_while_a_new_sample_exists_is_refused(client, boss):
    _make(client)
    client.delete("/api/books/sample")
    _make(client)
    r = client.post("/api/books/sample/restore")
    assert (r.status_code, r.json()) == (409, {"error": HAS_SAMPLE})


def test_the_sample_routes_never_read_a_slug(client, books, ddb, ours, boss):
    parent = create_book(books, ddb, name="Sample", kind="parent", owner_labels=["Lee"], by=boss.id)
    assert parent.slug == "sample"
    assert _make(client)["slug"] == "sample-2"
    client.delete("/api/books/sample")
    ddb.rollback()
    assert ddb.get(Book, parent.id).archived_at is None
    assert client.patch("/api/books/sample", json={"name": "Lee's book"}).json()["book"]["name"] == "Lee's book"


def test_a_sample_whose_file_is_gone_is_archived_at_start(client, books, ddb, ours, boss):
    info = books.book(_make(client)["slug"])
    books.close(info.id)
    shutil.rmtree(books.path_for(info).parent)
    books.upgrade_all()
    assert info.id not in books.unavailable and ours.id not in books.unavailable
    ddb.rollback()
    assert ddb.get(Book, info.id).archived_at is not None


def test_remove_or_undo_with_no_sample_is_404(client, boss):
    r = client.delete("/api/books/sample")
    assert (r.status_code, r.json()) == (404, {"error": NO_SAMPLE})
    assert client.post("/api/books/sample/restore").status_code == 404


def test_only_an_install_manager_makes_a_sample(client, books, ddb, fast_sample):
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret"])
    make_person(ddb, "momsmgr", [(mom.id, "manager")])
    login(client, "momsmgr")
    r = client.post("/api/books/sample")
    assert (r.status_code, r.json()) == (404, {"error": "Only a manager of the household can see this."})


def test_a_second_press_during_the_seed_waits_and_gets_the_finished_sample(books, ddb, ours, boss, monkeypatch):
    import threading

    from steward.books import sample as sample_mod
    real_seed = demo.seed
    inner = {}

    def seed(db, **kw):
        def second():
            with Session(books.directory) as s:
                inner["got"] = sample_mod.make_sample(books, s, boss.id, clock.today(), clock.now())
        t = threading.Thread(target=second)
        t.start()
        t.join(0.5)
        inner["blocked_during_seed"] = t.is_alive()      # it must not answer with the half-seeded book
        inner["thread"] = t
        real_seed(db, **kw)

    monkeypatch.setattr("steward.books.sample.demo.seed", seed)
    info, made = sample_mod.make_sample(books, ddb, boss.id, clock.today(), clock.now())
    inner["thread"].join(30)
    assert made and inner["blocked_during_seed"] is True
    got, made2 = inner["got"]
    assert got.id == info.id and made2 is False
    with Session(books.engine_for(info)) as s:
        assert s.scalar(select(func.count(Transaction.id))) > 0


def test_a_failed_seed_cleans_up_while_a_second_press_holding_the_write_lock_waits(books, ours, boss, monkeypatch):
    """A POST's directory session is BEGIN IMMEDIATE and the route has already read in it, so a second press reaches
    make_sample holding the directory write lock. It must let go before it waits for the first press, or the first
    press's failure cleanup (archive the book, remove its folder) can't write and ends in a 500."""
    import threading

    from sqlalchemy import update

    from steward.books import sample as sample_mod
    from steward.db.engine import WRITE
    holding = threading.Event()
    inner = {}

    def second():
        with Session(books.directory.execution_options(**WRITE)) as s:
            s.execute(update(Book).where(Book.id == -1).values(name=Book.name))   # takes the write lock, as a POST has
            holding.set()
            try:
                sample_mod.make_sample(books, s, boss.id, clock.today(), clock.now())
            except Exception as e:  # noqa: BLE001 - the test reads what it was
                inner["second"] = e

    def boom(db, **kw):
        if "thread" not in inner:
            inner["thread"] = t = threading.Thread(target=second)
            t.start()
            assert holding.wait(30)
        raise ValueError("seed broke")

    monkeypatch.setattr("steward.books.sample.demo.seed", boom)
    with Session(books.directory.execution_options(**WRITE)) as first:
        with pytest.raises(RuntimeError) as failed:
            sample_mod.make_sample(books, first, boss.id, clock.today(), clock.now())
    assert str(failed.value) == SAMPLE_FAILED
    inner["thread"].join(30)
    assert not inner["thread"].is_alive()
    assert str(inner["second"]) == SAMPLE_FAILED                       # it waited, then tried again on its own
    with Session(books.directory) as s:
        rows = s.scalars(select(Book).where(Book.sample_of == boss.id).order_by(Book.id)).all()
    assert len(rows) == 2 and all(r.archived_at is not None for r in rows)
    assert not any(books.path_for(BookInfo.of(r)).parent.exists() for r in rows)


class _RecordingLock:
    """Stands in for sample._MAKING: on each acquire it records whether the watched session had a transaction open."""

    def __init__(self, watched):
        self._lock, self._watched, self.open_at_acquire = threading.Lock(), watched, []

    def __enter__(self):
        self.open_at_acquire.append(self._watched["ddb"].in_transaction())
        return self._lock.__enter__()

    def __exit__(self, *exc):
        return self._lock.__exit__(*exc)


def test_make_sample_holds_no_directory_transaction_when_it_takes_the_lock(books, ours, boss, monkeypatch):
    """A second press must never hold the directory write lock while it waits on _MAKING, whatever its session did
    before; deterministic, no threads: the lock itself records the session's state at the moment it is taken."""
    from sqlalchemy import update

    from steward.books import sample as sample_mod
    from steward.db.engine import WRITE
    monkeypatch.setattr("steward.books.sample.demo.seed", lambda db, **kw: None)
    with Session(books.directory.execution_options(**WRITE)) as s:
        s.execute(update(Book).where(Book.id == -1).values(name=Book.name))   # holds the write lock, as a POST can
        assert s.in_transaction()
        lock = _RecordingLock({"ddb": s})
        monkeypatch.setattr(sample_mod, "_MAKING", lock)
        _, made = sample_mod.make_sample(books, s, boss.id, clock.today(), clock.now())
    assert made and lock.open_at_acquire == [False]


def test_the_sample_route_holds_no_directory_transaction_when_it_takes_the_lock(client, boss, monkeypatch):
    from steward.api import books as books_api
    from steward.books import sample as sample_mod
    monkeypatch.setattr("steward.books.sample.demo.seed", lambda db, **kw: None)
    watched = {}
    real = books_api.make_sample

    def spy(books, ddb, *a):
        watched["ddb"] = ddb
        return real(books, ddb, *a)

    monkeypatch.setattr(books_api, "make_sample", spy)
    lock = _RecordingLock(watched)
    monkeypatch.setattr(sample_mod, "_MAKING", lock)
    assert client.post("/api/books/sample").status_code == 201
    assert client.post("/api/books/sample").status_code == 200   # the second press, which finds the first's Sample
    assert lock.open_at_acquire == [False, False]


def test_a_failed_seed_archives_the_book_removes_the_folder_and_a_retry_makes_a_fresh_one(client, books, ddb, ours, boss, monkeypatch):
    real_seed = demo.seed

    def boom(*a, **kw):
        raise ValueError("seed broke")

    monkeypatch.setattr("steward.books.sample.demo.seed", boom)
    r = client.post("/api/books/sample")
    assert (r.status_code, r.json()) == (503, {"error": SAMPLE_FAILED})
    ddb.rollback()
    row = ddb.scalar(select(Book).where(Book.sample_of == boss.id))
    assert row.archived_at is not None
    assert not books.path_for(BookInfo.of(row)).parent.exists()
    monkeypatch.setattr("steward.books.sample.demo.seed", real_seed)
    fresh = _make(client)
    assert fresh["slug"] != row.slug and books.book(fresh["slug"]).id != row.id
    assert books.path_for(books.book(fresh["slug"])).exists()


def test_sweep_never_removes_a_folder_not_named_for_the_book(client, books, ddb, ours, boss):
    info = books.book(_make(client)["slug"])
    client.delete("/api/books/sample")
    ddb.rollback()
    ddb.get(Book, info.id).file = "books/book.db"                      # a folder not named for its slug
    ddb.commit()
    books.close(info.id)
    assert sweep_removed(books, clock.now() + timedelta(minutes=16)) == 0
    assert books.settings.books_dir.exists() and books.path_for(ours).parent.exists()


REFUSED = {"error": SAMPLE_REFUSED}
GUARDED = ("/api/b/{slug}/simplefin", "/api/b/{slug}/sync", "/api/b/{slug}/chat", "/api/b/{slug}/import",
           "/api/b/{slug}/export")
SAMPLE_OK = {("GET", "/api/b/{slug}/simplefin"), ("GET", "/api/b/{slug}/chat")}


def test_every_route_that_reaches_a_bank_claude_a_file_or_a_person_is_guarded(app):
    """Spec 8.3 layer 2, as a class: a route added under these later fails here until it takes real_book_only."""
    found = set()
    for path, method, endpoint, calls in api_routes(app):
        if path.startswith(GUARDED) and (method, path) not in SAMPLE_OK:
            assert real_book_only in calls, f"{method} {path}"
            found.add(path)
        if (method, path) in SAMPLE_OK:
            assert getattr(endpoint, "sample_ok", False), path
    assert {"/api/b/{slug}/simplefin/link", "/api/b/{slug}/chat/ask", "/api/b/{slug}/import/files",
            "/api/b/{slug}/import/statements", "/api/b/{slug}/export/backup", "/api/b/{slug}/chat/grants"} <= found
    assert real_book_only in next(c for p, m, _, c in api_routes(app) if (m, p) == ("POST", "/api/books/{slug}/members"))


def test_every_guarded_route_answers_403_in_the_sample(app, client, boss):
    slug = _make(client)["slug"]
    for path, method, endpoint, calls in api_routes(app):
        if real_book_only in calls:
            r = client.request(method, fill(path, slug), json={})
            if getattr(endpoint, "sample_ok", False):       # the two status reads Home and Ask need (D11)
                assert r.status_code == 200, (method, path, r.text)
            else:
                assert (r.status_code, r.json()) == (403, REFUSED), (method, path, r.text)


def test_the_choke_points_refuse_a_sample_engine(client, books, boss):
    from steward.advisor.state import chat_on, set_chat_on
    from steward.services.simplefin.sync import sync_now
    from steward.db.models import AdvisorState
    info = books.book(_make(client)["slug"])
    eng = books.engine_for(info)
    with pytest.raises(SampleRefused):
        sync_now(eng, http=None, model=None, now=clock.now())
    with Session(eng) as s:
        s.add(AdvisorState(key="chat_on", value="1", updated_at=clock.now(), updated_by=boss.id))   # even if a row says on
        s.commit()
        assert chat_on(s) is False
        with pytest.raises(SampleRefused):
            set_chat_on(s, True, boss.id, clock.now())


def test_asking_is_refused_before_any_gateway_call(client, books, boss):
    from steward.advisor.turn import AskEnv
    info = books.book(_make(client)["slug"])
    with pytest.raises(SampleRefused):
        AskEnv(bind=books.engine_for(info), directory=books.directory, book=info, user_id=boss.id, people=lambda: (),
               plan_cache=books.plan_cache(info.id), gateway=object(), now=clock.now, today=clock.today)


def test_the_categorizer_is_the_null_client_in_a_sample(client, books, boss):
    from types import SimpleNamespace
    from steward import deps
    from steward.services.categorizer_client import NullModelClient
    info = books.book(_make(client)["slug"])
    ctx = deps.BookContext(info, "manager", boss.id, ())
    req = SimpleNamespace(state=SimpleNamespace(book=ctx), app=SimpleNamespace(state=SimpleNamespace(model=object())))
    assert isinstance(deps.model(req), NullModelClient)


def test_a_grant_never_opens_a_sample(settings, client, books, ddb, boss):
    from steward.advisor import grants as G
    from tests.advisor.test_grant_door import bearer, pair
    info = books.book(_make(client)["slug"])
    _, text = G.issue(ddb, book_id=info.id, slug=info.slug, user_id=boss.id, by=boss.id, now=clock.now())
    ddb.commit()
    pair(settings)
    r = client.get(f"/api/b/{info.slug}/advisor/tools", headers=bearer(text))
    assert (r.status_code, r.json()) == (403, REFUSED)


def test_jobs_never_see_a_sample(client, books, tmp_path, boss):
    from steward.books.jobs import sync_all_books
    from steward.db.models import SimplefinLink
    from steward.services.backup import backup_all
    info = books.book(_make(client)["slug"])
    with Session(books.engine_for(info)) as s:                        # layer 1 holds even with a link planted
        s.add(SimplefinLink(access_url="https://testserver/simplefin", claimed_at=clock.now()))
        s.commit()

    class NoNetwork:
        def __getattr__(self, name):
            raise AssertionError("the Sample reached the network")
    assert info.slug not in sync_all_books(books, NoNetwork(), None, clock.now(), ("testserver",))
    written, _ = backup_all(books, tmp_path / "copies")
    assert not any(info.slug in p.name for p in written)


def test_only_start_up_migrate_and_book_list_ask_for_samples():
    """Spec 8.3 layer 1, as a class: every job walks books(), and only these three ask for Samples too."""
    src = Path(__file__).resolve().parents[1] / "src" / "steward"
    hits = {str(p.relative_to(src)): p.read_text().count("include_samples=True") for p in src.rglob("*.py")
            if "include_samples=True" in p.read_text()}
    assert hits == {"books/registry.py": 1, "cli.py": 2}


def test_the_household_name_for_ask_is_never_the_samples(app, client, boss):
    from types import SimpleNamespace
    from steward.api.chat import _household_name
    _make(client)
    assert _household_name(SimpleNamespace(app=app)) == "Ours"
