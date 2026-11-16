"""Get Steward ready's eight rows (guided setup spec 3.2, 3.3, 5)."""
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from steward.services import ready as r
from tests.factories import login, make_person

NOW = datetime(2026, 10, 30, 19, 0, tzinfo=timezone.utc)      # noon in Los Angeles (DEFAULT_NOW)
TODAY = date(2026, 10, 30)


def test_household_row():
    assert r.household_row(5, 5, 6, 6, None).as_dict() == {
        "key": "household", "status": "done", "detail": "Profile 5 of 5 · Plan 6 of 6", "go": None, "lines": [],
        "extra": {"next": None}}
    row = r.household_row(3, 5, 4, 6, "kids")
    assert (row.status, row.detail, row.go, row.extra) == ("needs", "Profile 3 of 5 · Plan 4 of 6", "Continue", {"next": "kids"})


def test_money_row_states():
    base = dict(money_in=True, linked=True, last_sync=NOW, sync_failed=False, accounts=4, last_import=None,
                waiting=12, today=TODAY)
    assert r.money_row(**base).detail == "Linked · updated today · 12 wait in Review"
    assert r.money_row(**base | {"linked": False, "accounts": 3, "waiting": 0,
                                 "last_import": datetime(2026, 10, 30, 1, tzinfo=timezone.utc)}).detail \
        == "3 accounts · last import Oct 29"
    assert (r.money_row(**base | {"sync_failed": True}).status, r.money_row(**base | {"sync_failed": True}).go) == ("needs", "Check")
    assert r.money_row(**base | {"money_in": False, "linked": False}).detail == "Nothing is in yet."


@pytest.mark.parametrize("kw,status,detail,go", [
    (dict(url=None, paired=False, reachable=None, state=None, chat_on=False), "optional", "Not set up.", None),
    (dict(url="http://gw:8430", paired=False, reachable=True, state=None, chat_on=False), "optional", "Not paired with the gateway.", "Pair"),
    (dict(url="http://gw:8430", paired=False, reachable=False, state=None, chat_on=False), "optional", "The gateway didn't answer at http://gw:8430.", "Pair"),
    (dict(url="http://gw:8430", paired=True, reachable=None, state="ok", chat_on=True), "done", "The gateway is answering. Ask is on.", None),
    (dict(url="http://gw:8430", paired=True, reachable=None, state="ok", chat_on=False), "optional", "Ask is off in this book.", "Turn on"),
    (dict(url="http://gw:8430", paired=True, reachable=None, state="not_set_up", chat_on=True), "needs", "The gateway has no Claude key.", "Check again"),
    (dict(url="http://gw:8430", paired=True, reachable=None, state="away", chat_on=True), "needs", None, "Check again"),
])
def test_ask_row_states(kw, status, detail, go):
    row = r.ask_row(**kw)
    assert (row.status, row.go) == (status, go) and (detail is None or row.detail == detail)
    if kw["url"] is None:
        assert [l.line for l in row.lines] == ["STEWARD_GATEWAY_URL=http://gateway:8430"]
    if kw["state"] == "not_set_up":
        assert row.lines[0].where == "gateway" and row.lines[0].line.startswith("ANTHROPIC_API_KEY=")


def test_ask_row_says_what_the_gateway_runs_on():
    ok = dict(url="http://gw:8430", paired=True, reachable=None, state="ok", chat_on=True)
    for value in ("cpu", "cuda", "rocm"):
        assert r.ask_row(**ok, accelerator=value).extra["accelerator"] == value
    for odd in (None, "mps", "", 3, "CUDA"):
        assert r.ask_row(**ok, accelerator=odd).extra["accelerator"] is None
    assert r.ask_row(**ok | {"state": "away"}, accelerator="cuda").extra["accelerator"] is None
    assert r.ask_row(**ok, accelerator="cpu").detail == "The gateway is answering. Ask is on."    # the row's words stay
    assert r.ask_row(**ok, accelerator="cpu").status == "done"


def test_email_row_states(books):
    from steward.app_settings import AppSettings
    from tests.test_app_settings import BY, EMAIL
    st = AppSettings(books.settings, books.directory, books.master)
    row = lambda: r.email_row(eff=st.effective(), configured=st.email() is not None, last=st.last_mail(),
                              version=st.email_version(), today=TODAY)
    assert (row().status, row().go) == ("optional", "Set up")
    st.save("email", EMAIL, **BY)
    assert (row().status, row().detail) == ("needs", "Send a test to check it.")
    st.record_mail(False, "auth")
    assert row().detail == "The server refused the user name or password."
    st.record_mail(True, None)
    assert row().status == "done"
    st.save("email", {**EMAIL, "password": None, "from": "Home <home@example.com>"}, **BY)
    assert row().detail == "Send a test to check it."                    # a change asks for a new test
    st.save("email", {**EMAIL, "password": None, "user": "u2@example.com"}, **BY)
    assert (row().status, row().detail, row().go) == ("needs", "Enter the email password again.", "Edit")   # let go
    from steward.db.keys import new_key
    other = AppSettings(st.settings, books.directory, new_key())
    unreadable = r.email_row(eff=other.effective(), configured=False, last=None, version=other.email_version(), today=TODAY)
    assert (unreadable.status, unreadable.detail) == ("needs", "Enter the email password again.")


@pytest.mark.parametrize("at,last,newest_h,status,detail", [
    ("03:00", None, None, "done", "First copy at 3:00 AM"),
    ("", None, None, "needs", "Backups are off, and there's no copy yet."),
    ("03:00", {"at": "x", "ok": True, "why": None, "ping_ok": None}, 9, "done", "Last copy today at 3:00 AM · next 3:00 AM"),
    ("", None, 9, "done", "Last copy today at 3:00 AM · made outside Steward's schedule"),     # JR's DSM task
    ("03:00", None, 33, "done", "Last copy Oct 29 at 3:00 AM · next 3:00 AM"),                 # D4: a missed night waits
    ("03:00", None, 57, "needs", "The newest copy is from Oct 28 at 3:00 AM."),
    ("03:00", {"at": "x", "ok": False, "why": "disk error", "ping_ok": True}, 9, "needs", "The last backup didn't work."),
    ("03:00", {"at": "x", "ok": True, "why": None, "ping_ok": False}, 9, "needs", "The backup ping didn't go through."),
])
def test_backups_row_states(at, last, newest_h, status, detail):
    newest = NOW - timedelta(hours=newest_h) if newest_h is not None else None
    row = r.backups_row(at=at, last=last, newest=newest, now=NOW, folder="/data/backups")
    assert (row.status, row.detail, row.extra) == (status, detail, {"dir": "/data/backups"})


def test_files_written_outside_stewards_schedule_count(tmp_path):
    assert r.newest_copy(tmp_path / "missing") is None
    (tmp_path / "steward-directory-20261030-030000.db").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")
    stamp = (NOW - timedelta(hours=9)).timestamp()
    os.utime(tmp_path / "steward-directory-20261030-030000.db", (stamp, stamp))
    assert r.newest_copy(tmp_path) == NOW - timedelta(hours=9)


def test_someone_row():
    assert (r.someone_row(["Mom", "Dad"]).status, r.someone_row(["Mom", "Dad"]).detail) == ("done", "Mom and Dad")
    assert (r.someone_row([]).status, r.someone_row([]).go) == ("optional", "Add their book")


@pytest.mark.parametrize("base,scheme,origin,status,names", [
    ("https://nas.example.ts.net", "https", "https://nas.example.ts.net", "done", []),
    ("http://localhost:8441", "http", "http://localhost:8441", "done", []),
    ("http://nas.lan:8420", "http", "http://nas.lan:8420", "needs", ["STEWARD_BASE_URL"]),
    ("https://nas.example.ts.net", "https", "https://other.example.ts.net", "needs", ["STEWARD_BASE_URL"]),
    ("https://nas.example.ts.net", "http", "https://nas.example.ts.net", "needs", ["STEWARD_TRUSTED_PROXIES"]),
    ("https://nas.example.ts.net", "https", None, "needs", []),     # no origin proves nothing (INS-22)
])
def test_address_row_states(base, scheme, origin, status, names):
    row = r.address_row(base_url=base, trusted_proxies="127.0.0.1,::1", scheme=scheme, origin=origin, peer="172.18.0.4")
    assert row.status == status and [l.name for l in row.lines] == names
    if origin is None:
        assert row.detail == "Couldn't tell which address this page is on."
    if "STEWARD_TRUSTED_PROXIES" in names:
        assert row.lines[0].line == "STEWARD_TRUSTED_PROXIES=127.0.0.1,::1,172.18.0.4" and row.lines[0].running == "127.0.0.1,::1"
    if names == ["STEWARD_BASE_URL"] and origin.startswith("https"):
        assert row.lines[0].line == f"STEWARD_BASE_URL={origin}" and row.lines[0].running == base


def test_key_row_states(tmp_path):
    dev = lambda d: (lambda p: SimpleNamespace(st_dev=d(p)))
    same = r.key_row(key_file=None, key_path=tmp_path / "steward.key", data_dir=tmp_path, stat=dev(lambda p: 1))
    assert same.status == "optional" and same.lines[0].line == "STEWARD_KEY_FILE=/run/secrets/steward_key"
    apart = r.key_row(key_file=Path("/mnt/key/k"), key_path=Path("/mnt/key/k"), data_dir=tmp_path,
                      stat=dev(lambda p: 2 if str(p).startswith("/mnt") else 1))
    assert apart.status == "done"
    secret = r.key_row(key_file=Path("/run/secrets/steward_key"), key_path=Path("/run/secrets/steward_key"),
                       data_dir=tmp_path, stat=dev(lambda p: 1))
    assert secret.status == "done"


def test_the_route_answers_eight_rows_for_a_manager_and_404_for_others(client, ddb, books, ours):
    make_person(ddb, "pat", [(ours.id, "manager")])
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "vee")
    assert client.get("/api/b/ours/ready").status_code == 404
    login(client, "pat")
    body = client.get("/api/b/ours/ready", params={"origin": "https://nas.tail1234.ts.net"}).json()
    assert [row["key"] for row in body["rows"]] == ["household", "money", "ask", "email", "backups", "someone",
                                                    "address", "key"]
    assert body["need"] == sum(row["status"] == "needs" for row in body["rows"])
    assert body["rows"][6]["status"] == "done"          # the address, from the running base URL and HTTPS


def test_check_again_answers_from_the_running_process(app, books, ddb, ours, client):
    from steward.auth.sessions import COOKIE
    make_person(ddb, "pat", [(ours.id, "manager")])
    login(client, "pat")                                       # the session cookie is Secure: only an https client sends it
    token = client.cookies.get(COOKIE)
    with TestClient(app, base_url="http://nas.tail1234.ts.net") as c:     # Steward sees plain HTTP
        row = c.get("/api/b/ours/ready", params={"origin": "https://nas.tail1234.ts.net"},
                    headers={"Cookie": f"{COOKIE}={token}"}).json()["rows"][6]
        assert row["lines"][0]["line"].endswith(",testclient")             # request.client.host
