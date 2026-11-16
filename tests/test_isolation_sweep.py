"""Spec 11's isolation sweep. It lists every route in the app, so routes added later are swept without anyone
adding a case, and a book route that skips open_book fails the structure test."""
from steward import clock
import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute, iter_route_contexts

from steward.auth.sessions import COOKIE
from steward.books.sample_guard import SAMPLE_REFUSED
from steward.books.service import create_book
from steward.deps import NOT_IN_THIS_BOOK, NO_SUCH_BOOK, SAFE_METHODS, VIEWER_COPY, book_db, open_book, open_book_by_grant
from tests.factories import login, make_person

BOOK_SCOPED = ("/api/b/{slug}", "/api/books/{slug}")
TOP_LEVEL = {
    "/api/health", "/api/auth/login", "/api/auth/logout", "/api/auth/me", "/api/auth/sessions",
    "/api/auth/sessions/{sid}", "/api/auth/password", "/api/auth/forgot", "/api/auth/reset",
    "/api/auth/passkeys", "/api/auth/passkeys/{pid}", "/api/auth/passkeys/register/options",
    "/api/auth/passkeys/register/verify", "/api/auth/passkeys/login/options", "/api/auth/passkeys/login/verify",
    "/api/users", "/api/users/{uid}/reset-password", "/api/books",
    "/api/invites/accept", "/api/setup", "/api/setup/check",
    "/api/install/settings", "/api/install/settings/email", "/api/install/settings/backups",
    "/api/install/settings/general", "/api/install/email/test", "/api/install/gateway/pair",
    "/api/books/sample", "/api/books/sample/restore",
}


def api_routes(app):
    """(path, method, endpoint, dependency callables) for every API route, through included routers too."""
    for rc in iter_route_contexts(app.routes):
        if not isinstance(rc.original_route, APIRoute):
            continue
        calls = []

        def walk(dep):
            for d in dep.dependencies:
                calls.append(d.call)
                walk(d)
        walk(rc.dependant)
        for method in sorted(rc.methods):
            yield rc.path, method, rc.endpoint, calls


def uses_grant(calls) -> bool:
    """Claude Code's routes (spec 7) take a grant, never a session: they are swept with grants in
    tests/advisor/test_mcp_routes.py."""
    return open_book_by_grant in calls


def check_routes(app) -> None:
    for path, method, _, calls in api_routes(app):
        if path.startswith(BOOK_SCOPED):
            if uses_grant(calls):
                assert path.startswith("/api/b/{slug}/advisor/") and open_book not in calls, f"{method} {path}"
            else:
                assert open_book in calls, f"{method} {path} skips open_book"
        else:
            assert path in TOP_LEVEL, f"{method} {path} is neither a known top-level route nor under /api/b/{{slug}}"


def fill(path: str, slug: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda m: slug if m.group(0) == "{slug}" else "999999", path)


def test_every_api_route_is_top_level_or_goes_through_open_book(app):
    check_routes(app)


def test_the_check_notices_a_route_that_skips_open_book(app):
    from fastapi import APIRouter
    rogue = APIRouter()

    @rogue.get("/rogue")
    def _rogue():
        return {}
    app.include_router(rogue, prefix="/api/b/{slug}")
    with pytest.raises(AssertionError, match="rogue skips open_book"):
        check_routes(app)


def test_the_check_notices_a_new_top_level_route(app):
    @app.get("/api/rogue")
    def _rogue():
        return {}
    with pytest.raises(AssertionError, match="/api/rogue is neither"):
        check_routes(app)


SRC = Path(__file__).resolve().parents[1] / "src" / "steward"


def test_get_db_is_gone_and_no_route_reaches_a_book_database_but_through_book_db(app):
    """Controller addition: a book's database is reached only through open_book/book_db."""
    import steward.deps
    assert not hasattr(steward.deps, "get_db")
    for path in sorted(SRC.rglob("*.py")):
        assert not re.search(r"\bget_db\b", path.read_text()), f"{path.relative_to(SRC)} still mentions get_db"
    # No top-level (person or directory) route may take a book session.
    for path, method, _, calls in api_routes(app):
        if not path.startswith(BOOK_SCOPED):
            assert book_db not in calls, f"{method} {path} opens a book database without a book in its address"
    # In the API modules only the code behind open_book may name an engine or the book registry's openers.
    allowed = {"simplefin.py", "books.py"}   # simplefin takes the book from request.state.book (open_book set it); books.py reads the Profile marks of the books the person belongs to
    for path in sorted((SRC / "api").glob("*.py")):
        text = path.read_text()
        if path.name not in allowed:
            assert "engine_for" not in text, f"api/{path.name} opens a book engine itself"
    assert "request.state.book" in (SRC / "api" / "simplefin.py").read_text()


@pytest.fixture
def sweeper(app):
    """A client that answers a crashing route with its 500 instead of raising: the sweep judges isolation only."""
    from fastapi.testclient import TestClient
    with TestClient(app, base_url="https://nas.tail1234.ts.net", raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def tokens(sweeper, books, ddb, ours):
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret", "Joint"])
    make_person(ddb, "manager_a", [(ours.id, "manager")])
    make_person(ddb, "viewer_a", [(ours.id, "viewer")])
    make_person(ddb, "manager_b", [(mom.id, "manager")])
    make_person(ddb, "viewer_b", [(mom.id, "viewer")])
    make_person(ddb, "nobody")
    out = {}
    for who in ("manager_a", "viewer_a", "manager_b", "viewer_b", "nobody"):
        login(sweeper, who)
        out[who] = sweeper.cookies.get(COOKIE)
    sweeper.cookies.clear()
    return out


def _as(client, tokens, who):
    client.cookies.clear()
    if who:
        client.cookies.set(COOKIE, tokens[who])


def test_sweep_non_members_get_404_and_viewers_cannot_write(app, sweeper, tokens):
    client = sweeper
    routes = [(p, m, ep) for p, m, ep, calls in api_routes(app) if p.startswith(BOOK_SCOPED) and not uses_grant(calls)]
    assert len(routes) > 40
    for path, method, endpoint in routes:
        url = fill(path, "ours")
        _as(client, tokens, None)
        r = client.request(method, url)
        assert r.status_code == 401, (method, path, r.status_code)
        for who in ("nobody", "manager_b"):
            _as(client, tokens, who)
            r = client.request(method, url)
            assert (r.status_code, r.json()) == (404, {"error": NO_SUCH_BOOK}), (who, method, path, r.text)
        _as(client, tokens, "viewer_a")
        r = client.request(method, url)
        if method in SAFE_METHODS or getattr(endpoint, "viewer_ok", False):
            assert r.status_code != 403 and NO_SUCH_BOOK not in r.text, (method, path, r.text)
        else:
            assert (r.status_code, r.json()) == (403, {"error": VIEWER_COPY}), (method, path, r.text)


def test_a_person_outside_ours_gets_nothing_of_ours_from_the_top_level_routes(sweeper, tokens, books, ours, ddb):
    """/api/auth/me used to open ours for anyone signed in; now it reads ours only for a member."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from steward.db.directory_models import User
    from steward.db.models import UserSetup
    uid = ddb.scalar(select(User.id).where(User.username == "manager_b"))
    with Session(books.engine_for(ours)) as s:   # a row in ours under manager_b's id, as if the ids collided
        s.add(UserSetup(user_id=uid, seen_at=clock.now()))
        s.commit()
    _as(sweeper, tokens, "manager_b")
    r = sweeper.get("/api/auth/me")
    assert r.status_code == 200
    assert [b["slug"] for b in r.json()["books"]] == ["mom"]   # ours is not listed, and none of its marks come back
    _as(sweeper, tokens, "manager_a")   # a member of ours still gets ours' marks
    r = sweeper.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["books"][0]["profile"] == {"seen": False, "confirmed": False, "later_until": None}


def test_sweep_in_a_parent_book_viewers_cannot_write_and_others_get_404(app, sweeper, tokens):
    client = sweeper
    for path, method, endpoint, calls in api_routes(app):
        if not path.startswith("/api/b/{slug}") or uses_grant(calls):
            continue
        url = fill(path, "mom")
        _as(client, tokens, "manager_a")   # a member of ours only
        r = client.request(method, url)
        assert (r.status_code, r.json()) == (404, {"error": NO_SUCH_BOOK}), (method, path, r.text)
        _as(client, tokens, "viewer_b")
        r = client.request(method, url)
        if method in SAFE_METHODS or getattr(endpoint, "viewer_ok", False):
            assert r.status_code != 403, (method, path, r.text)
        else:
            assert (r.status_code, r.json()) == (403, {"error": VIEWER_COPY}), (method, path, r.text)


# Every route that reads or changes state belonging to the whole install (email, backups, the gateway, the key file,
# the chat budget). A new one goes here, and must take install_manager or install_household (the check below fails
# otherwise). Order matters for the household's own manager: the email is removed again before Send a test, so no
# test opens a mail connection.
INSTALL_WIDE = [
    ("GET", "/api/b/{slug}/ready", None),
    ("POST", "/api/b/{slug}/chat/budget", {"cap_dollars": 30}),
    ("GET", "/api/install/settings", None),
    ("PUT", "/api/install/settings/email", {"host": "smtp.example.com", "port": 465, "user": "steward@example.com",
                                            "password": "-".join(["sweep", "pw", "41"]), "from": "steward@example.com"}),
    ("DELETE", "/api/install/settings/email", None),
    ("PUT", "/api/install/settings/backups", {"at": "04:00"}),
    ("PUT", "/api/install/settings/general", {"gateway_name": "Den PC"}),
    ("POST", "/api/install/email/test", {}),
    ("POST", "/api/install/gateway/pair", {"code": "ABCDEF"}),
    ("POST", "/api/books/sample", None),   # a Sample's maker must be an install manager (plan D1)
]


def test_every_install_wide_route_is_in_the_table_and_guarded(app):
    from steward.deps import install_household, install_manager
    guarded = {(m, p) for p, m, _, calls in api_routes(app) if install_manager in calls or install_household in calls}
    assert guarded == {(m, p) for m, p, _ in INSTALL_WIDE}


def test_a_manager_of_a_legacy_second_household_book_gets_404_on_every_install_wide_route(sweeper, books, ddb, ours, monkeypatch):
    """An older install might hold a second household-kind book (none can be made now; the e2e "Solo" seed builds one
    this way). Its manager is a manager of a household book, but not of THE household (household_book_id)."""
    from steward.books.owners import HOUSEHOLD_OWNER_NAMES, to_json
    from steward.db.directory_models import Book
    monkeypatch.setattr("steward.books.sample.YEARS", 1)   # ours_boss's POST /api/books/sample makes a real Sample
    older = create_book(books, ddb, name="Older", kind="parent", owner_labels=["Lee"])
    row = ddb.get(Book, older.id)
    row.kind, row.owner_names = "household", to_json(HOUSEHOLD_OWNER_NAMES)
    ddb.commit()
    assert older.id > ours.id
    make_person(ddb, "older_boss", [(older.id, "manager")])
    make_person(ddb, "ours_boss", [(ours.id, "manager")])
    for method, path, body in INSTALL_WIDE:
        login(sweeper, "older_boss")
        r = sweeper.request(method, fill(path, older.slug), json=body)
        assert r.status_code == 404, (method, path, r.status_code, r.text)
        login(sweeper, "ours_boss")
        r = sweeper.request(method, fill(path, ours.slug), json=body)
        assert r.status_code not in (404, 500), (method, path, r.status_code, r.text)   # 409 or 503 without email or a gateway


def test_a_sample_never_gains_install_authority(sweeper, books, ddb, ours, monkeypatch):
    """Plan D1: the Sample's maker is a real install manager, but the Sample is never THE household book."""
    from steward.books.registry import household_book_id
    monkeypatch.setattr("steward.books.sample.YEARS", 1)
    make_person(ddb, "ours_boss", [(ours.id, "manager")])
    login(sweeper, "ours_boss")
    slug = sweeper.post("/api/books/sample").json()["book"]["slug"]
    ddb.rollback()
    assert household_book_id(ddb) == ours.id
    for method, path, body in INSTALL_WIDE:
        if "{slug}" in path:
            r = sweeper.request(method, fill(path, slug), json=body)
            # 404 where install_household answers; 403 where the router's real_book_only answers first (chat, grants)
            assert (r.status_code, r.json()) in ((404, {"error": NOT_IN_THIS_BOOK}),
                                                 (403, {"error": SAMPLE_REFUSED})), (method, path, r.status_code, r.text)
