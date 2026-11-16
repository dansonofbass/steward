import base64

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from typer.testing import CliRunner

from steward import cli
from steward.app import create_app
from steward.db.models import EventLog, Institution, SimplefinLink, Transaction
from steward.mail import FakeMailer
from steward.services.simplefin.client import SimplefinError, _cents, claim
from steward.services.simplefin.sync import run_sync
from tests.fake_simplefin import make_fake
from tests.test_sync import E, NOW as E_NOW
from tests.factories import make_user

TOKEN = base64.b64encode(b"http://testserver/claim/abc").decode()


@pytest.fixture
def signed_in(settings, books, db):
    """A signed-in client wired to a fake SimpleFIN server with one account."""
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    fake_app, state = make_fake()
    state.add_account("big", "Big Bank", "bigbank", "chk", 100_00, E(2026, 10, 12),
                      txns=[("t1", E(2026, 10, 1), -5_00, "X")])
    with TestClient(fake_app) as fake_http:
        app = create_app(settings, books, http=fake_http)
        with TestClient(app, base_url="https://nas.tail1234.ts.net") as c:
            c.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})
            yield c, app, state, fake_http


def test_link_sync_status_unlink(signed_in, db):
    c, _, _, _ = signed_in
    assert c.get("/api/b/ours/simplefin").json() == {"linked": False, "last_sync_at": None, "last_error": None}
    r = c.post("/api/b/ours/sync")
    assert r.status_code == 409 and r.json() == {"error": "SimpleFIN isn't linked yet."}
    r = c.post("/api/b/ours/simplefin/link", json={"setup_token": TOKEN})
    assert r.status_code == 201 and r.json()["linked"] is True
    assert r.json()["sync"] == {"institutions_ok": 1, "institutions_failed": 0, "accounts_new": 1,
                                "transactions_new": 1, "accounts_held": 0, "pairs_raised": 0, "errors": []}
    r = c.post("/api/b/ours/simplefin/link", json={"setup_token": TOKEN})
    assert r.status_code == 409 and r.json() == {"error": "SimpleFIN is already linked. Unlink it first."}
    st = c.get("/api/b/ours/simplefin").json()
    assert st["linked"] and st["last_sync_at"] and st["last_error"] is None
    assert c.post("/api/b/ours/sync").json()["transactions_new"] == 0
    assert c.delete("/api/b/ours/simplefin").status_code == 204
    assert c.get("/api/b/ours/simplefin").json()["linked"] is False
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Transaction)) == 1
    assert db.scalar(select(func.count()).select_from(Institution)) == 1
    assert c.delete("/api/b/ours/simplefin").status_code == 204  # unlinking twice is harmless


def test_bad_tokens(signed_in):
    c, _, _, _ = signed_in
    for bad in ("nope!", base64.b64encode(b"not a url").decode(),
                base64.b64encode(b"https://evil.example/claim/x").decode()):
        r = c.post("/api/b/ours/simplefin/link", json={"setup_token": bad})
        assert r.status_code == 422 and r.json() == {"error": "That setup token isn't valid."}


def test_claim_failure_is_502(signed_in):
    c, _, state, _ = signed_in
    state.claimed.add("abc")
    r = c.post("/api/b/ours/simplefin/link", json={"setup_token": TOKEN})
    assert r.status_code == 502 and "already used" in r.json()["error"]
    assert c.get("/api/b/ours/simplefin").json()["linked"] is False


def test_requires_sign_in(settings, books):
    with TestClient(create_app(settings, books), base_url="https://nas.tail1234.ts.net") as c:
        assert c.get("/api/b/ours/simplefin").status_code == 401
        assert c.post("/api/b/ours/sync").status_code == 401


def test_sync_refuses_while_another_runs(signed_in):
    c, app, _, _ = signed_in
    c.post("/api/b/ours/simplefin/link", json={"setup_token": TOKEN})
    with app.state.books.sync_lock(app.state.books.book("ours").id):
        r = c.post("/api/b/ours/sync")
    assert r.status_code == 409 and r.json() == {"error": "A sync is already running."}


class _Reply:
    status_code, text = 200, "https://evil.example/simplefin\n"


class _Http:
    def post(self, url):
        return _Reply()


def test_claim_rejects_access_url_off_allowlist():
    with pytest.raises(SimplefinError, match="isn't allowed"):
        claim(_Http(), "http://testserver/claim/abc", allowed_hosts=("testserver",))


def test_huge_amount_is_a_parse_error():
    with pytest.raises(ValueError):
        _cents("1e30")


def test_scheduler_job_syncs_and_swallows_errors(signed_in, db, monkeypatch):
    c, app, _, _ = signed_in
    app.state.sync_job()  # not linked: nothing happens, no error
    c.post("/api/b/ours/simplefin/link", json={"setup_token": TOKEN})
    app.state.sync_job()
    monkeypatch.setattr("steward.books.jobs.sync_now", lambda *a, **k: 1 / 0)
    app.state.sync_job()  # swallowed and logged
    assert app.state.books.sync_lock(app.state.books.book("ours").id).acquire(blocking=False)  # lock was released
    app.state.books.sync_lock(app.state.books.book("ours").id).release()


def test_scheduler_wiring(settings, books):
    assert create_app(settings, books).state.scheduler is None  # env=test
    prod = settings.model_copy(update={"env": "prod", "sync_hours": 6})
    with TestClient(create_app(prod, books, mailer=FakeMailer())) as c:
        sched = c.app.state.scheduler
        assert sched._thread.is_alive()
    assert not sched._thread.is_alive()
    off = settings.model_copy(update={"env": "prod", "sync_hours": 0})
    assert create_app(off, books, mailer=FakeMailer()).state.scheduler is None


def test_cli_sync(settings, books, db, monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    r = runner.invoke(cli.app, ["sync"])
    assert r.exit_code == 1 and "isn't linked" in r.output
    fake_app, state = make_fake()
    state.add_account("big", "Big Bank", "bigbank", "chk", 100_00, E(2026, 10, 12),
                      txns=[("t1", E(2026, 10, 1), -5_00, "X")])
    db.add(SimplefinLink(access_url="http://demo:demo@testserver/simplefin"))
    db.commit()
    with TestClient(fake_app) as fake_http:
        monkeypatch.setattr("httpx2.Client", lambda **k: fake_http)
        r = runner.invoke(cli.app, ["sync"])
    assert r.exit_code == 0, r.output
    assert "ours: 1 ok, 0 failed, 1 new accounts, 1 new transactions" in r.output


class _DownHttp:
    """Stands in for the network being unreachable."""
    def get(self, *a, **k):
        raise httpx2.ConnectError("down")

    def post(self, *a, **k):
        raise httpx2.ConnectError("down")


def _app_with(settings, books, http):
    return TestClient(create_app(settings, books, http=http), base_url="https://nas.tail1234.ts.net")


def _login(c):
    c.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})


def test_network_down_on_claim_is_502(settings, books, db):
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    with _app_with(settings, books, _DownHttp()) as c:
        _login(c)
        r = c.post("/api/b/ours/simplefin/link", json={"setup_token": TOKEN})
        assert r.status_code == 502 and "Couldn't reach SimpleFIN" in r.json()["error"]


def test_network_down_on_first_sync_still_links(settings, books, db):
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    fake_app, _ = make_fake()
    with TestClient(fake_app) as good, _app_with(settings, books, good) as c:
        _login(c)
        # claim works over the real fake; only the fetch fails
        class Mixed(_DownHttp):
            def post(self, *a, **k):
                return good.post(*a, **k)
        c.app.state.http = Mixed()
        r = c.post("/api/b/ours/simplefin/link", json={"setup_token": TOKEN})
        assert r.status_code == 201 and "Couldn't reach SimpleFIN" in r.json()["sync"]["errors"][0]
        r = c.post("/api/b/ours/sync")
        assert r.status_code == 200 and "Couldn't reach SimpleFIN" in r.json()["errors"][0]
        assert "Couldn't reach" in c.get("/api/b/ours/simplefin").json()["last_error"]
        # the network comes back: the unreachable event resolves and the link error clears
        c.app.state.http = good
        r = c.post("/api/b/ours/sync")
        assert r.status_code == 200 and r.json()["errors"] == []
        assert c.get("/api/b/ours/simplefin").json()["last_error"] is None
        db.rollback()
        ev = db.scalars(select(EventLog).where(EventLog.message.like("Couldn't reach SimpleFIN%"))).all()
        assert ev and all(e.resolved_at is not None for e in ev)


def test_claim_returning_off_list_address_is_502(signed_in, monkeypatch):
    c, app, _, _ = signed_in
    monkeypatch.setattr("steward.api.simplefin.claim", lambda http, url, hosts: claim(_Http(), url, hosts))
    r = c.post("/api/b/ours/simplefin/link", json={"setup_token": TOKEN})
    assert r.status_code == 502 and r.json() == {"error": "That SimpleFIN address isn't allowed."}


def test_scheduled_job_skips_while_lock_held(signed_in, monkeypatch):
    _, app, _, _ = signed_in
    calls = []
    monkeypatch.setattr("steward.books.jobs.sync_now", lambda *a, **k: calls.append(1))
    with app.state.books.sync_lock(app.state.books.book("ours").id):
        app.state.sync_job()
    assert calls == []
    app.state.sync_job()
    assert calls == [1]


def test_cli_sync_exits_1_when_every_bank_fails(settings, books, db, monkeypatch):
    fake_app, state = make_fake()
    state.add_account("big", "Big Bank", "bigbank", "chk", 100_00, E(2026, 10, 12))
    db.add(SimplefinLink(access_url="http://demo:demo@testserver/simplefin"))
    db.commit()
    with TestClient(fake_app) as fake_http:  # a first good sync, so Big Bank is a bank Steward knows with an account
        run_sync(db, fake_http, db.scalar(select(SimplefinLink)), E_NOW, model=None, allowed_hosts=("testserver",))
        db.commit()
    state.fail_conn = "big"
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    with TestClient(fake_app) as fake_http:
        monkeypatch.setattr("httpx2.Client", lambda **k: fake_http)
        r = CliRunner().invoke(cli.app, ["sync"])
    assert r.exit_code == 1 and "ours: 0 ok, 1 failed" in r.output
