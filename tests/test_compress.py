"""Phase 18: API reads go out gzipped when the browser asks; writes, small answers, other paths and identity don't."""
import gzip
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from steward.api.compress import CompressReads

BIG = {"rows": ["x" * 40 for _ in range(100)]}


def _app():
    inner = FastAPI()

    @inner.get("/api/big")
    def big_get():
        return BIG

    @inner.post("/api/big")
    def big_post():
        return BIG

    @inner.get("/api/small")
    def small():
        return {"ok": True}

    @inner.get("/elsewhere/big")
    def elsewhere():
        return BIG

    return CompressReads(inner)


def _send(c, method, path, accept="gzip"):
    with c.stream(method, path, headers={"Accept-Encoding": accept}) as r:
        return r, b"".join(r.iter_raw())


def test_api_reads_go_out_gzipped_when_asked():
    with TestClient(_app()) as c:
        r, raw = _send(c, "GET", "/api/big")
    assert r.headers["content-encoding"] == "gzip" and json.loads(gzip.decompress(raw)) == BIG
    assert "accept-encoding" in r.headers["vary"].lower()


def test_writes_small_answers_other_paths_and_identity_go_out_as_they_are():
    with TestClient(_app()) as c:
        for method, path, accept in (("POST", "/api/big", "gzip"), ("GET", "/api/small", "gzip"),
                                     ("GET", "/elsewhere/big", "gzip"), ("GET", "/api/big", "identity"),
                                     ("GET", "/api/big", "gzip;q=0")):
            r, raw = _send(c, method, path, accept)
            assert "content-encoding" not in r.headers, (method, path, accept)
            assert json.loads(raw)


def test_the_app_gzips_a_signed_in_read(signed_in, db):
    from tests.factories import make_account
    for i in range(12):
        make_account(db, f"Account {i}")
    r, raw = _send(signed_in, "GET", "/api/b/ours/accounts")
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
    assert len(json.loads(gzip.decompress(raw))["accounts"]) == 12
