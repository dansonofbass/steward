"""Phase 18: Plan's first open after a restart (1.6 s on the NAS, 4.8 s on the phone) finds its answer worked out:
services/plan_warm, and single-flight solves (PlanCache.once)."""
import threading

from steward.services import plan as svc
from steward.services import plan_warm
from steward.services.plan_cache import PlanCache
from tests.factories import make_ready_household, make_user
from tests.waiting import CEILING, wait_until


def _count_solves(monkeypatch) -> list:
    calls = []
    real = svc.solve

    def counted(*a, **k):
        calls.append(1)
        return real(*a, **k)
    monkeypatch.setattr("steward.services.plan.solve", counted)
    return calls


def test_a_warmed_plan_opens_without_solving_again(frozen, signed_in, db, app, monkeypatch):
    make_user(db, "sam", "sam@x.com", "Sam")
    make_ready_household(db)
    calls = _count_solves(monkeypatch)
    books = app.state.books
    assert plan_warm.warm_book(books, books.book("ours")) is True
    assert len(calls) == 1
    r = signed_in.get("/api/b/ours/plan")
    assert r.status_code == 200 and r.json()["result"]["comfortable_age"] is not None
    assert len(calls) == 1                                       # the open found the warmed answer


def test_a_book_with_setup_unfinished_is_skipped(frozen, signed_in, app, monkeypatch):
    calls = _count_solves(monkeypatch)
    books = app.state.books
    assert plan_warm.warm_book(books, books.book("ours")) is False and calls == []


def test_a_parent_book_is_skipped(books, margaret):
    assert plan_warm.warm_book(books, margaret) is False


def test_a_failure_is_logged_and_the_next_book_still_warms(books, ours, margaret, monkeypatch, caplog):
    seen = []

    def warm_book(_books, book):
        seen.append(book.slug)
        if book.id == ours.id:
            raise RuntimeError("boom")
        return False
    monkeypatch.setattr(plan_warm, "warm_book", warm_book)
    plan_warm.warm_all(books, threading.Event())
    assert seen == [ours.slug, margaret.slug] and "Couldn't warm the plan" in caplog.text


def test_a_second_caller_waits_for_the_first_solve_instead_of_solving_again():
    cache = PlanCache()
    key = ("solve", "k")
    entered, release, missed = threading.Event(), threading.Event(), threading.Event()
    real_get = cache.results.get

    def get(k):
        found = real_get(k)
        if threading.current_thread().name == "second":
            missed.set()                                         # the second caller looked, before the first finished
        return found
    cache.results.get = get

    def first():
        entered.set()
        release.wait(CEILING)
        return "answer"
    again, out = [], {}
    a = threading.Thread(target=lambda: out.__setitem__("a", cache.once(key, first)))
    b = threading.Thread(target=lambda: out.__setitem__("b", cache.once(key, lambda: again.append(1) or "again")),
                         name="second")
    a.start()
    assert entered.wait(CEILING)
    b.start()
    assert missed.wait(CEILING)
    release.set()
    a.join(CEILING)
    b.join(CEILING)
    assert out == {"a": "answer", "b": "answer"} and again == []
    assert (cache.results.hits, cache.results.misses) == (0, 2)  # once() counts one look per caller


def test_a_kick_while_warming_runs_one_more_pass_not_one_per_kick(monkeypatch):
    passes, started, release = [], threading.Event(), threading.Event()

    def warm_all(_books, _stop):
        passes.append(1)
        started.set()
        release.wait(CEILING)
    monkeypatch.setattr(plan_warm, "warm_all", warm_all)
    w = plan_warm.PlanWarmer(books=None)
    w.kick()
    assert started.wait(CEILING)
    w.kick()
    w.kick()                                                     # both while the first pass runs
    release.set()
    wait_until(lambda: not w.running, "the warmer to finish")
    assert len(passes) == 2


def test_a_pass_that_raises_does_not_stop_later_kicks(monkeypatch, caplog):
    passes = []

    def warm_all(_books, _stop):
        passes.append(1)
        if len(passes) == 1:
            raise RuntimeError("directory locked")
    monkeypatch.setattr(plan_warm, "warm_all", warm_all)
    w = plan_warm.PlanWarmer(books=None)
    w.kick()
    wait_until(lambda: not w.running, "the failed pass to end")
    w.kick()
    wait_until(lambda: len(passes) == 2 and not w.running, "a second pass to run")
    assert "Couldn't warm the plan" in caplog.text


def test_an_unreadable_directory_is_logged_and_warms_nothing(caplog):
    class Books:
        def books(self):
            raise RuntimeError("directory locked")
    plan_warm.warm_all(Books(), threading.Event())
    assert "Couldn't warm the plan" in caplog.text


def test_a_kick_just_as_the_warmer_decides_to_stop_still_gets_its_pass(monkeypatch):
    """The stop decision and clearing `running` are one step: a kick landing right after the decision starts a pass."""
    passes, fired, kicked = [], threading.Event(), threading.Event()
    monkeypatch.setattr(plan_warm, "warm_all", lambda _books, _stop: passes.append(1))
    w = plan_warm.PlanWarmer(books=None)
    real = w._lock

    class KickOnDecision:
        """The warmer's lock; the first release on the warmer's thread (its stop decision) is followed by a kick."""

        def __enter__(self):
            return real.__enter__()

        def __exit__(self, *exc):
            real.__exit__(*exc)
            if threading.current_thread().name == "steward-plan-warm" and passes and not fired.is_set():
                fired.set()
                w.kick()                                         # lands after the decision, before the thread ends
                kicked.set()
    w._lock = KickOnDecision()
    w.kick()
    wait_until(lambda: kicked.is_set() and not w.running, "the kick and any pass it started")
    assert len(passes) == 2
