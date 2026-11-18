"""P17: no route in Steward changes or deletes the log of what was sent (spec 4.6). The sweep calls every API route, as
a manager and as a viewer, and checks the seeded rows field for field. The scan reads src/steward for code that could
write the log, function by function."""
import ast
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.advisor import grants as G
from steward.auth.cookies import HOST_SESSION as COOKIE
from steward.db.directory_models import User
from steward.db.models import AdvisorOutgoing, ChatConversation
from steward.deps import NO_SUCH_BOOK
from steward_boundary.canonical import canonical, sha256_hex
from tests.advisor.test_grant_door import bearer, pair
from tests.test_isolation_sweep import api_routes, fill, sweeper, tokens, uses_grant  # noqa: F401 (two are fixtures)

SRC = Path(__file__).resolve().parents[2] / "src" / "steward"
AT = datetime(2026, 10, 29, 18, 0, tzinfo=timezone.utc)
LOGOUT = ("POST", "/api/auth/logout")


def _seed(books, ours, manager_id: int, viewer_id: int) -> tuple[int, str]:
    """Three rows in ours: one request of two parts on a conversation manager_a owns, and a viewer's prewarm."""
    rows = [(manager_id, "seedturn1", 1, "chat", "question", {"text": "How much is in savings?"}),
            (manager_id, "seedturn1", 1, "chat", "system", {"text": "Today is Thursday, October 29, 2026."}),
            (viewer_id, "seedturn2", 1, "prewarm", "system", {"text": "warmup"})]
    with Session(books.engine_for(ours)) as s:
        conv = ChatConversation(user_id=manager_id, title="Savings", created_at=AT, updated_at=AT)
        s.add(conv)
        s.flush()
        for uid, turn, seq, channel, part, payload in rows:
            raw = canonical(payload)
            s.add(AdvisorOutgoing(at=AT, user_id=uid, conversation_id=conv.id if channel == "chat" else None,
                                  turn_id=turn, seq=seq, channel=channel, part=part, payload=raw.decode("utf-8"),
                                  sha256=sha256_hex(payload), bytes=len(raw), model="claude-opus-5-5"))
        s.commit()
        return conv.id, "seedturn1.1"


def _log(books, ours) -> dict[int, tuple]:
    """Every row of the log, every column, read afresh."""
    cols = [c.name for c in AdvisorOutgoing.__table__.columns]
    with Session(books.engine_for(ours)) as s:
        return {r.id: tuple(getattr(r, c) for c in cols) for r in s.scalars(select(AdvisorOutgoing))}


def test_no_route_changes_or_deletes_the_sent_log(app, sweeper, tokens, books, ddb, ours, settings, monkeypatch):
    monkeypatch.setattr("steward.books.sample.YEARS", 1)    # POST /api/books/sample makes a real Sample
    ids = {n: ddb.scalar(select(User.id).where(User.username == n)) for n in ("manager_a", "viewer_a")}
    cid, key = _seed(books, ours, ids["manager_a"], ids["viewer_a"])
    before = _log(books, ours)
    assert len(before) == 3
    # Claude Code's routes take a grant and the gateway's pairing token, never a session.
    pair(settings)
    grants = {who: G.issue(ddb, book_id=ours.id, slug="ours", user_id=uid, by=ids["manager_a"], now=AT)[1]
              for who, uid in ids.items()}
    ddb.commit()

    def url(path: str) -> str:
        # The log's own conversation and request are real, so the routes most likely to touch them see real rows.
        return fill(path.replace("{cid}", str(cid)).replace("{key}", key), "ours")

    routes = sorted({(m, p, uses_grant(calls)) for p, m, _, calls in api_routes(app)} - {(*LOGOUT, False)})
    assert len(routes) >= 40 and any(by_grant for _, _, by_grant in routes)
    reached = 0
    for who in ("manager_a", "viewer_a"):
        sweeper.cookies.clear()
        sweeper.cookies.set(COOKIE, tokens[who])
        for method, path, by_grant in routes:
            r = sweeper.request(method, url(path), json={}, headers=bearer(grants[who]) if by_grant else {})
            if r.status_code != 401 and not (r.status_code == 404 and NO_SUCH_BOOK in r.text):
                reached += 1
        assert sweeper.get("/api/auth/me").status_code == 200, who      # no call ended the session
        assert sweeper.post("/api/auth/logout").status_code == 204       # last, since it does
    assert reached >= 40
    after = _log(books, ours)
    assert {i: after.get(i) for i in before} == before                  # added rows are allowed


# Modules that name the log today. A new one fails here until it's read and added.
NAME_THE_LOG = {
    "advisor/history.py", "advisor/monitor.py", "advisor/outgoing.py", "advisor/turn.py", "api/chat.py",
    "db/models.py", "services/book_export.py", "services/book_restore.py",
    "db/alembic/versions/0012_advisor.py", "db/alembic/versions/0013_chat_turn.py",
}
# The one writer besides the recorder. It runs only from the CLI (cli.py), never a route.
OTHER_WRITERS = {
    ("services/book_restore.py", "_clear_attribution"):
        "relabels who asked (user_id, approved_by) in a restored copy of a book, through ATTRIBUTION",
}
LOG = re.compile(r"\bAdvisorOutgoing\b|\badvisor_outgoing\b")
SQL_WRITE = re.compile(r"\b(DELETE|UPDATE)\b")
COLUMNS = {c.name for c in AdvisorOutgoing.__table__.columns}


def _walk(node):
    """ast.walk without decorators: a route's @router.delete(...) isn't a write."""
    todo = [node]
    while todo:
        n = todo.pop()
        yield n
        skip = set(map(id, getattr(n, "decorator_list", [])))
        todo.extend(c for c in ast.iter_child_nodes(n) if id(c) not in skip)


def _names(node) -> set[str]:
    return {n.id for n in _walk(node) if isinstance(n, ast.Name)}


def _writes(node) -> list[tuple[int, str]]:
    """Calls to delete or update, SQL that deletes or updates, and assignments to a column of the log's rows."""
    out = []
    for n in _walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if name in ("delete", "update"):
                out.append((n.lineno, f"{name}("))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and SQL_WRITE.search(n.value):
            out.append((n.lineno, SQL_WRITE.search(n.value).group(1)))
        elif isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            for t in n.targets if isinstance(n, ast.Assign) else [n.target]:
                if isinstance(t, ast.Attribute) and t.attr in COLUMNS:
                    out.append((n.lineno, f".{t.attr} ="))
    return out


def log_writers(root: Path) -> tuple[set[str], list[tuple[str, str, int, str]]]:
    """(the modules that name the log, each write in a function that names it as (module, function, line, what)). A
    name the module binds to a value that names the log, such as a table list, counts as naming it wherever it's
    used."""
    naming, found = set(), []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text()
        if not LOG.search(text):
            continue
        rel = path.relative_to(root).as_posix()
        naming.add(rel)
        tree = ast.parse(text)
        carriers = set()
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and LOG.search(ast.get_source_segment(text, node) or ""):
                carriers |= {t.id for t in (node.targets if isinstance(node, ast.Assign) else [node.target])
                             if isinstance(t, ast.Name)}
        top = ast.Module(body=[n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                                             ast.ClassDef))], type_ignores=[])
        scopes = [("<module>", top)] + [(n.name, n) for n in ast.walk(tree)
                                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for name, scope in scopes:
            source = "\n".join(ast.get_source_segment(text, n) or "" for n in getattr(scope, "body", []))
            if not (LOG.search(source) or _names(scope) & carriers):
                continue
            found += [(rel, name, line, what) for line, what in _writes(scope)]
    return naming, found


def constructed_in(root: Path) -> set[str]:
    """The modules that build an AdvisorOutgoing row."""
    out = set()
    for path in sorted(root.rglob("*.py")):
        for n in ast.walk(ast.parse(path.read_text())):
            if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", None)) == "AdvisorOutgoing":
                out.add(path.relative_to(root).as_posix())
    return out


def test_only_the_recorder_writes_the_sent_log():
    naming, found = log_writers(SRC)
    assert naming == NAME_THE_LOG
    assert [f"{rel}:{line} {fn}: {what}" for rel, fn, line, what in found if (rel, fn) not in OTHER_WRITERS] == []
    # The exception is real, so the scan sees a write made through a table list.
    assert {(rel, fn) for rel, fn, _, _ in found} == set(OTHER_WRITERS)
    importers = {p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py")
                 if re.search(r"import book_restore\b|book_restore import", p.read_text())}
    assert importers == {"cli.py"}
    assert constructed_in(SRC) == {"advisor/outgoing.py"}


def test_the_writer_scan_notices_a_delete(tmp_path):
    cases = {
        "purge.py": "def purge(db):\n    db.execute(delete(AdvisorOutgoing))\n",
        "drop_one.py": "def drop(db, i):\n    row = db.get(AdvisorOutgoing, i)\n    db.delete(row)\n",
        "edit.py": "def edit(db, i):\n    row = db.get(AdvisorOutgoing, i)\n    row.payload = '{}'\n",
        "raw.py": "def raw(c):\n    c.execute('DELETE FROM advisor_outgoing')\n",
        "listed.py": "TABLES = ('advisor_outgoing',)\n\ndef wipe(c):\n    for t in TABLES:\n"
                     "        c.execute(f'DELETE FROM {t}')\n",
    }
    for name, code in cases.items():
        (tmp_path / name).write_text(code)
    naming, found = log_writers(tmp_path)
    assert naming == set(cases)
    assert {rel for rel, _, _, _ in found} == set(cases)
    (tmp_path / "rows.py").write_text("def make():\n    return AdvisorOutgoing(part='question')\n")
    assert constructed_in(tmp_path) == {"rows.py"}
