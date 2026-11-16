"""The gateway's body cap (spec P29): counted as the body streams, before routing, per path; 1 MB by default."""
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from steward_gateway.bodycap import DEFAULT, BodyCap, limit_for


def _app():
    app = FastAPI()
    app.add_middleware(BodyCap)
    seen = []

    @app.post("/v1/statements/layout")
    async def layout(request: Request):
        seen.append(len(await request.body()))
        return {"ok": True}

    @app.post("/v1/categorize/batch")
    async def batch(request: Request):
        seen.append(len(await request.body()))
        return {"ok": True}
    return app, seen


def test_limits_by_path():
    assert limit_for("/v1/statements/layout") == 512 * 1024
    assert limit_for("/v1/categorize/batch") == DEFAULT == 1024 * 1024


def test_a_declared_length_over_the_cap_is_refused_before_the_route():
    app, seen = _app()
    with TestClient(app) as c:
        r = c.post("/v1/statements/layout", content=b"x" * (512 * 1024 + 1))
    assert (r.status_code, r.json()) == (413, {"error": "That request is too large."}) and seen == []


def test_a_chunked_body_is_counted_as_it_streams():
    app, seen = _app()
    with TestClient(app) as c:
        r = c.post("/v1/categorize/batch", content=(b"x" * 65536 for _ in range(17)))
    assert r.status_code == 413 and seen == []


def test_a_body_under_the_cap_passes():
    app, seen = _app()
    with TestClient(app) as c:
        assert c.post("/v1/statements/layout", content=b"x" * 1000).status_code == 200
    assert seen == [1000]
