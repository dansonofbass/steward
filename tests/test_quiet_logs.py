"""Release spec 2026-11-05, section 6, claim P10: logs don't carry your money. Every record Steward's own code makes,
at any level, and every record uvicorn makes, goes through the one handler `steward serve` installs while the test
drives a search, a sync, an import, a category, a note, the setup link, failing scheduled jobs, a failing request,
SimpleFIN's own errors and a parent book named for a person. Nothing planted (a description, a note, an amount, a
query string, a setup token, a name) may be in what that handler wrote. A scan of every log call in src/ keeps names
and other programs' words out of the lines no test drives."""
import ast
import asyncio
import io
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from steward import clock, logs
from steward.auth import setup_link
from steward.db.models import SimplefinLink, Transaction
from steward.inventory.present import log_safe
from tests.factories import login, make_account, make_person
from tests.import_helpers import import_file

ROOT = Path(__file__).resolve().parents[1]

DESC = "ZQXWV PLANTED MERCHANT"
NOTE = "qjvnote about the planted vet bill"
QUERY = "zqxwvsearch"
TOKEN = "zqxwvtoken" + "t" * 33
PLANTED = ("zqxwv", "qjvnote", "8137", "813729")       # checked case-insensitively; 8137.29 is the planted amount


@pytest.fixture
def written():
    stream = io.StringIO()
    logs.configure(stream)
    logging.getLogger("steward").setLevel(logging.DEBUG)   # all of Steward's own lines, not only what serve shows
    return stream                                            # conftest's clean_logging puts every logger back


def planted(text: str) -> list[str]:
    return [p for p in PLANTED if p in text.lower()]


@pytest.fixture
def jr(client, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    return client


def test_requests_log_their_route_never_their_address(written, jr):
    assert jr.get(f"/api/b/ours/transactions?q={QUERY}").status_code == 200
    text = written.getvalue()
    assert "INFO:     GET /api/b/{slug}/transactions 200 " in text
    assert "INFO:     POST /api/auth/login 200 " in text
    assert planted(text) == [] and "?" not in text and "/ours/" not in text


def test_the_setup_token_never_reaches_a_log(written, client, ddb):
    setup_link.issue(ddb, clock.now())
    assert client.post("/api/setup/check", json={"token": TOKEN}).status_code == 400
    text = written.getvalue()
    assert "POST /api/setup/check 400 " in text and planted(text) == []


def test_a_sync_an_import_a_category_and_a_note_log_none_of_their_text(written, jr, db):
    from tests.fake_simplefin import make_fake
    from tests.test_sync import E, H, NOW
    from steward.services.simplefin.client import claim
    from steward.services.simplefin.sync import run_sync
    bank, state = make_fake()
    state.add_account("big", "Big Bank", "bigbank", "chk", 1450_00, E(2026, 10, 12),
                      txns=[("t1", E(2026, 10, 1), -813729, DESC)])
    with TestClient(bank) as http:
        link = SimplefinLink(access_url=claim(http, "http://testserver/claim/abc", allowed_hosts=H), claimed_at=NOW)
        db.add(link)
        db.commit()
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H)
    db.commit()
    account = make_account(db, "Checking")
    r = import_file(jr, "planted.csv", account.id, raw=f"Date,Description,Amount\n10/02/2026,{DESC} TWO,-8137.29\n".encode())
    assert r.status_code < 300, r.text
    tid = db.scalar(select(Transaction.id).where(Transaction.raw_description == DESC))
    assert jr.patch(f"/api/b/ours/transactions/{tid}", json={"category": "dining"}).status_code == 200
    assert jr.post(f"/api/b/ours/transactions/{tid}/notes", json={"body": NOTE}).status_code == 201
    assert jr.get(f"/api/b/ours/transactions?q={DESC}").status_code == 200
    text = written.getvalue()
    assert "PATCH /api/b/{slug}/transactions/{tid} 200 " in text
    assert planted(text) == []


def test_failing_jobs_log_the_type_and_place_never_the_message(written, client, monkeypatch):
    def boom(*a, **k):
        raise ValueError(f"{DESC} cost 8137.29")
    monkeypatch.setattr("steward.app.watch_tick", boom)
    monkeypatch.setattr("steward.app.sync_all_books", boom)
    client.app.state.watch_job()                 # the watcher's every-minute job: logs and carries on
    client.app.state.sync_job()
    logging.getLogger("steward.watch").error("The watch tick failed for book %s: %s", "ours", log_safe(ValueError(DESC)))
    try:
        raise RuntimeError(NOTE) from ValueError(DESC)
    except RuntimeError:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application")   # the real server's 500 path
    text = written.getvalue()
    assert "ERROR:     The watch tick failed" in text and "ERROR:     Scheduled SimpleFIN sync failed" in text
    assert "ValueError (message not logged)" in text and "RuntimeError <- ValueError (message not logged)" in text
    assert 'File "' in text and planted(text) == []


def test_a_request_that_raises_is_logged_as_a_500_without_its_message(written):
    async def app(scope, receive, send):
        raise ValueError(DESC)

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        pass

    with pytest.raises(ValueError):
        asyncio.run(logs.RequestLog(app)({"type": "http", "method": "GET", "path": "/api/x",
                                          "query_string": f"q={QUERY}".encode()}, receive, send))
    text = written.getvalue()
    assert "GET - 500 " in text and planted(text) == []


def test_serve_turns_off_uvicorns_access_log_and_logs_through_the_quiet_handler(settings, monkeypatch):
    import uvicorn
    from steward.cli import app as cli_app
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda asgi, **kw: seen.update(kw))
    runner = CliRunner()
    assert runner.invoke(cli_app, ["init-key"]).exit_code == 0 and runner.invoke(cli_app, ["migrate"]).exit_code == 0
    assert runner.invoke(cli_app, ["serve"]).exit_code == 0
    assert seen["access_log"] is False and seen["log_config"] is None
    assert any(isinstance(f, logs.QuietExceptions) for h in logging.getLogger().handlers for f in h.filters)
    assert not logging.getLogger("uvicorn.access").isEnabledFor(logging.CRITICAL)
    assert logging.getLogger("uvicorn.error").isEnabledFor(logging.INFO)     # "Uvicorn running on …" still shows


def test_the_start_line_says_where_pdf_statements_are_opened():
    """Install gate INS-11: where.resolve's line is at INFO, under the root's WARNING, so serve's handler shows it."""
    from steward.services.statements import where
    stream = io.StringIO()
    logs.configure(stream)
    walled = {"confined": True, "seccomp": 2, "walled": True, "probe": "refused", "canary": "ok"}
    assert where.resolve("auto", probe=True, check=lambda: walled) == "local"
    assert where.resolve("auto", probe=True, check=lambda: {"confined": False}) == "gateway"
    assert stream.getvalue().splitlines() == ["INFO:     PDF statements are opened on this machine",
                                              "INFO:     PDF statements are opened on the gateway"]


# PRIV-11: SimpleFIN's own words, as it sends them: an institution named for a person, an email address, a web address
# and an account number. The log keeps the code and the scrubbed words, never the name.
SF_WORDS = "Sign in again as zqxwv.ellis@example.com at https://bank.example/zqxwv for account 813729440"


def test_simplefin_errors_log_their_code_and_scrubbed_words(written, db):
    from tests.fake_simplefin import make_fake
    from tests.test_sync import E, H, NOW
    from steward.services.simplefin.client import claim
    from steward.services.simplefin.sync import run_sync
    bank, state = make_fake()
    state.add_account("zqxwv-cu", "Zqxwv Credit Union", "zqxwvcu", "chk", 1450_00, E(2026, 10, 12))
    state.add_account("big", "Big Bank", "bigbank", "chk2", 10_00, E(2026, 10, 12))
    state.errlist += [{"code": "con.auth", "msg": SF_WORDS, "conn_id": "zqxwv-cu"},
                      {"code": "gen.auth", "msg": SF_WORDS + "\nsecond line", "conn_id": None},
                      {"code": "gen.range", "msg": "Requested date range exceeds recommended range for zqxwv@example.com",
                       "conn_id": None}]
    with TestClient(bank) as http:
        link = SimplefinLink(access_url=claim(http, "http://testserver/claim/abc", allowed_hosts=H), claimed_at=NOW)
        db.add(link)
        db.commit()
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H)
    text = written.getvalue()
    assert "SimpleFIN error con.auth for institution " in text and "SimpleFIN reported a link-level problem gen.auth" in text
    assert "Sign in again as (address) at (web address) for account •9440" in text and "second line" not in text
    assert "SimpleFIN range notice: Requested date range exceeds recommended range for (address)" in text
    assert planted(text) == []


def test_a_book_is_named_by_its_id_never_its_slug(written, books, ddb, ours, monkeypatch):
    """PRIV-11: a parent book made with the parent's name has that name as its slug. Its failing sync, watch tick and
    open are logged by id."""
    from steward.books import jobs
    from steward.books.service import create_book
    from steward.watch import tick
    parent = create_book(books, ddb, name="Zqxwv Ellis", kind="parent", owner_labels=["Parent", "Joint"])
    assert parent.slug.startswith("zqxwv")
    with Session(books.engine_for(parent)) as s:
        s.add(SimplefinLink(access_url="http://demo:demo@testserver/simplefin", claimed_at=clock.now()))
        s.commit()

    def boom(*a, **k):
        raise RuntimeError(f"{parent.slug} is down")
    monkeypatch.setattr(jobs, "sync_now", boom)
    monkeypatch.setattr(tick, "watch_book", boom)
    assert jobs.sync_all_books(books, None, None, clock.now(), ("testserver",), only=parent.slug)[parent.slug] == "failed"
    assert tick.watch_tick(books, None, None, clock.now())[parent.slug] == "failed"
    books.close(parent.id)
    books.path_for(parent).unlink()
    books.upgrade_all()
    assert parent.id in books.unavailable
    text = written.getvalue()
    for line in (f"Scheduled SimpleFIN sync failed for book {parent.id}", f"The watch tick failed for book {parent.id}",
                 f"Book {parent.id} can't be opened: The book's file is missing."):
        assert line in text, line
    assert planted(text) == []


def test_outside_text_drops_an_origin_an_address_and_all_but_four_digits():
    reason = 'Unexpected client data origin "https://zqxwv.example", expected "https://zqxwv-family.example:8443"'
    assert logs.outside_text(reason) == 'Unexpected client data origin "(web address)", expected "(web address)"'
    assert logs.outside_text("x" * 500 + "\nmore") == "x" * logs.OUTSIDE_CAP
    assert logs.outside_text(ValueError("card 4111111111111111 for a@b.co")) == "card •1111 for (address)"


# The class guard. A log call's arguments may not reach for a name-like value (a book's slug, an institution's or a
# file's name, SimpleFIN's message, an origin, a rule's pattern, a person's email), whether as a field (book.slug), a
# local that holds one (slug = book.slug; name; book_name) or inside an f-string or str(); and may not hold an
# exception anywhere (e, f"{e}", str(e)) except as type(e).__name__: an exception goes through log_safe() or
# outside_text(), and a book is named by its id.
LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
NAME_FIELDS = {"slug", "name", "msg", "origin", "pattern", "email", "username", "display_name", "description",
               "raw_description", "note", "body", "payee", "memo", "title", "label", "access_url", "base_url", "args"}
EXCEPTIONS = {"e", "ex", "exc", "err", "error"}
SCRUBBERS = {"outside_text", "log_safe"}                    # what they return is fit for a log
# (file, enclosing function, what the scan found): each is a name Steward itself chose, never one a person typed.
ALLOWED = {
    ("src/steward/books/bootstrap.py", "ensure_directory", "backup.name"),   # a file name Steward makes from the time
    ("src/steward/advisor/tools/__init__.py", "run_call", "name"),           # a tool's name, checked against T.BY_NAME
    ("src/steward/services/statements/where.py", "resolve", "gateway_name"),  # the gateway machine's name (spec 7)
}


def _is_logger(node: ast.expr) -> bool:
    return "log" in ast.unparse(node).lower()          # log, logger, _log, logging, logging.getLogger("…")


def _name_like(word: str) -> bool:
    """slug, name, msg …, and a compound of one: book_slug, inst_name, error_msg."""
    return word in NAME_FIELDS or word.rsplit("_", 1)[-1] in NAME_FIELDS - {"args"}


def _is_type_name(node: ast.AST) -> bool:
    """type(x).__name__: the exception's class, never its message."""
    return (isinstance(node, ast.Attribute) and node.attr == "__name__" and isinstance(node.value, ast.Call)
            and getattr(node.value.func, "id", None) == "type")


def _unscrubbed(node: ast.AST, parent: ast.AST | None = None):
    """(node, its parent) for node and everything under it, except what a scrubber's call or type(…).__name__ holds."""
    if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) in SCRUBBERS:
        return
    if _is_type_name(node):
        return
    yield node, parent
    for child in ast.iter_child_nodes(node):
        yield from _unscrubbed(child, node)


def _calls_by_function(node: ast.AST, function: str = ""):
    """(the enclosing function's name, call) for every call under node."""
    for child in ast.iter_child_nodes(node):
        inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
        if isinstance(child, ast.Call):
            yield function, child
        yield from _calls_by_function(child, inner)


def names_in_log_calls(root: Path) -> list[str]:
    hits = []
    for path in sorted((root / "src").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        for function, node in _calls_by_function(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node.func, ast.Attribute)
                    and node.func.attr in LOG_METHODS and _is_logger(node.func.value)):
                continue
            # exc_info hands the traceback to QuietExceptions, which keeps its places and types, never its message
            for arg in (*node.args, *(k.value for k in node.keywords if k.arg != "exc_info")):
                for sub, parent in _unscrubbed(arg):
                    if isinstance(sub, ast.Attribute) and _name_like(sub.attr):
                        found = ast.unparse(sub)
                    elif isinstance(sub, ast.Name) and _name_like(sub.id):
                        found = sub.id
                    elif (isinstance(sub, ast.Name) and sub.id in EXCEPTIONS
                          and not (isinstance(parent, ast.Attribute) and parent.value is sub)):
                        found = f"{sub.id} logged as itself"    # e, f"{e}", str(e); e.code is judged as a field
                    else:
                        continue
                    if (rel, function, found) not in ALLOWED:
                        hits.append(f"{rel}:{node.lineno}: {found}")
    return hits


def test_no_log_call_names_a_book_by_slug_or_logs_another_programs_words_raw():
    assert len(list((ROOT / "src").rglob("*.py"))) > 300, "the scan found too few files to mean anything"
    assert names_in_log_calls(ROOT) == []


def test_the_log_call_scan_notices_a_slug_a_message_and_a_raw_exception(tmp_path):
    (tmp_path / "src/pkg").mkdir(parents=True)
    (tmp_path / "src/pkg/m.py").write_text(
        'log.error("Sync failed for book %s", book.slug)\n'
        'logging.getLogger("x").warning(f"SimpleFIN said {err.msg}")\n'
        'logger.info("failed: %s", e)\n'
        'log.error("Sync failed for %s", name)\n'           # the line simplefin/sync.py had before PRIV-11
        'slug = book.slug; log.error("book %s", slug)\n'
        'log.error(f"failed: {e}")\n'
        'log.error("failed: %s", str(e))\n'
        'log.info("%s for %s", e.args, book_name)\n'
        'log.info("book %s: %s", book.id, log_safe(e))\n'
        'log.warning("SimpleFIN %s: %s", err.code, outside_text(err.msg), exc_info=e)\n'
        'log.warning("failed (%s)", type(e).__name__)\n'
        'print(book.slug)\n')
    assert names_in_log_calls(tmp_path) == [
        "src/pkg/m.py:1: book.slug", "src/pkg/m.py:2: err.msg", "src/pkg/m.py:3: e logged as itself",
        "src/pkg/m.py:4: name", "src/pkg/m.py:5: slug", "src/pkg/m.py:6: e logged as itself",
        "src/pkg/m.py:7: e logged as itself", "src/pkg/m.py:8: e.args", "src/pkg/m.py:8: book_name"]
