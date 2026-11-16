"""The sync scheduler (flaky-test audit P14): it runs its job, stops at once even mid-interval, and outlives a job
that raises. Each test waits for the event; none times anything."""
import threading

from steward.scheduler import Scheduler
from tests.waiting import CEILING


def test_scheduler_runs_its_job():
    ran = threading.Event()
    s = Scheduler(0.01, ran.set)
    s.start()
    try:
        assert ran.wait(CEILING)
    finally:
        s.stop()
    assert not s._thread.is_alive()


def test_stop_ends_the_wait_at_once():
    """An hour between runs: stop() must wake the thread, not wait out the interval. stop() joins for up to 5 s, so a
    thread that slept through its interval would still be alive afterwards."""
    s = Scheduler(3600, lambda: None)
    s.start()
    s.stop()
    assert not s._thread.is_alive()


def test_scheduler_survives_job_errors():
    calls, second = [], threading.Event()

    def job():
        calls.append(1)
        if len(calls) == 2:
            second.set()
        raise RuntimeError("boom")

    s = Scheduler(0.01, job)
    s.start()
    try:
        assert second.wait(CEILING), "the job didn't run again after it raised"
    finally:
        s.stop()
    assert not s._thread.is_alive()
