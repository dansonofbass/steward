"""Spec 5: every manager write in a parent book is recorded. Like the isolation sweep, this lists every route, so a
write route added later fails until it is marked @recorded or @not_recorded("why")."""
from steward.deps import SAFE_METHODS, household_only
from tests.test_isolation_sweep import api_routes


def unmarked(app) -> list[str]:
    out = []
    for path, method, endpoint, calls in api_routes(app):
        if not path.startswith("/api/b/{slug}") or method in SAFE_METHODS or household_only in calls:
            continue
        if getattr(endpoint, "viewer_ok", False) and not hasattr(endpoint, "change_record"):
            continue   # changes nothing (plan 1 ruling 10)
        if not hasattr(endpoint, "change_record"):
            out.append(f"{method} {path}")
    return out


def test_every_write_a_parent_book_allows_is_recorded_or_says_why(app):
    assert unmarked(app) == []


def test_the_sweep_notices_an_unmarked_write(app):
    from fastapi import APIRouter, Depends
    from steward.deps import open_book
    rogue = APIRouter(dependencies=[Depends(open_book)])

    @rogue.post("/rogue")
    def _rogue():
        return {}
    app.include_router(rogue, prefix="/api/b/{slug}")
    assert "POST /api/b/{slug}/rogue" in unmarked(app)


def test_every_reason_is_a_sentence(app):
    for path, method, endpoint, _ in api_routes(app):
        reason = getattr(endpoint, "change_record", True)
        if reason is not True:
            assert isinstance(reason, str) and reason.endswith(".") and len(reason) > 20, (method, path)
