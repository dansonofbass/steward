import gzip

from fastapi.testclient import TestClient

from steward.app import create_app
from steward.web import ASSET_CACHE

BASE = "https://nas.tail1234.ts.net"


def _dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>Steward</title><div id=root></div>")
    (d / "assets" / "app-abc123.js").write_text("console.log('hi')")
    (d / "favicon.svg").write_text("<svg/>")
    (d / "manifest.webmanifest").write_text('{"name": "Steward"}')
    (d / "apple-touch-icon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return d


def test_the_favicon_set_and_manifest_are_served_from_the_root(settings, books, tmp_path):
    """Vite copies web/public to the root of dist; the catch-all serves those files with their types, no sign-in."""
    settings.web_dir = _dist(tmp_path)
    with TestClient(create_app(settings, books), base_url="https://nas.tail1234.ts.net") as c:
        r = c.get("/favicon.svg")
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
        r = c.get("/manifest.webmanifest")
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
        assert r.json() == {"name": "Steward"} and r.headers["cache-control"] == "no-cache"
        r = c.get("/apple-touch-icon.png")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_spa_fallback_and_assets(settings, books, tmp_path):
    settings.web_dir = _dist(tmp_path)
    with TestClient(create_app(settings, books), base_url="https://nas.tail1234.ts.net") as c:
        for path in ("/", "/transactions", "/settings/import", "/login?next=%2Freview"):
            r = c.get(path)
            assert r.status_code == 200 and "<div id=root>" in r.text and r.headers["cache-control"] == "no-cache"
        r = c.get("/assets/app-abc123.js")
        assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert c.get("/favicon.svg").status_code == 200
        r = c.get("/api/nope")
        assert r.status_code == 404 and r.json() == {"error": "Not found."}
        assert c.get("/api/health").status_code == 200


def test_no_path_traversal(settings, books, tmp_path):
    settings.web_dir = _dist(tmp_path)
    (tmp_path / "secret.txt").write_text("no")
    with TestClient(create_app(settings, books), base_url="https://nas.tail1234.ts.net") as c:
        r = c.get("/../secret.txt")
        assert r.status_code == 200 and "<div id=root>" in r.text  # falls back to the SPA page, never the file
        r = c.get("/assets/../../secret.txt")
        assert r.status_code == 200 and "<div id=root>" in r.text


def test_without_a_build_the_api_still_works(settings, books, tmp_path):
    settings.web_dir = tmp_path / "missing"
    with TestClient(create_app(settings, books), base_url="https://nas.tail1234.ts.net") as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/").status_code == 404


def test_null_byte_paths_fall_back_to_the_spa(settings, books, tmp_path):
    settings.web_dir = _dist(tmp_path)
    with TestClient(create_app(settings, books), base_url="https://nas.tail1234.ts.net") as c:
        for path in ("/%00", "/assets/%00x"):
            r = c.get(path)
            assert r.status_code in (200, 404)
        r = c.get("/%00")
        assert r.status_code == 200 and "<div id=root>" in r.text


def test_other_methods_and_head(settings, books, tmp_path):
    settings.web_dir = _dist(tmp_path)
    with TestClient(create_app(settings, books), base_url="https://nas.tail1234.ts.net") as c:
        r = c.post("/api/nope")
        assert r.status_code == 404 and r.json() == {"error": "Not found."}
        r = c.post("/transactions")
        assert r.status_code == 404 and r.json() == {"error": "Not found."}
        assert c.head("/").status_code == 200


def test_missing_asset_is_a_clean_404(settings, books, tmp_path):
    settings.web_dir = _dist(tmp_path)
    with TestClient(create_app(settings, books), base_url="https://nas.tail1234.ts.net") as c:
        r = c.get("/assets/gone-123.js")
        assert r.status_code == 404 and r.json() == {"error": "Not found."}


def _packed_dist(tmp_path):
    d = _dist(tmp_path)
    body = b"console.log('hi');\n" * 200
    (d / "assets" / "app-abc123.js").write_bytes(body)
    (d / "assets" / "app-abc123.js.br").write_bytes(b"stand-in brotli")   # the server never decodes it
    (d / "assets" / "app-abc123.js.gz").write_bytes(gzip.compress(body))
    (d / "assets" / "tiny-abc123.css").write_text("a{}")                   # too small to have copies
    return d, body


def _raw(c, path, accept):
    with c.stream("GET", path, headers={"Accept-Encoding": accept}) as r:
        return r, b"".join(r.iter_raw())


def test_assets_go_out_precompressed_when_the_browser_takes_it(settings, books, tmp_path):
    """Phase 18: the 606 KB of JS and CSS went out uncompressed whatever the browser asked for."""
    d, body = _packed_dist(tmp_path)
    settings.web_dir = d
    with TestClient(create_app(settings, books), base_url=BASE) as c:
        r, raw = _raw(c, "/assets/app-abc123.js", "gzip, deflate, br, zstd")
        assert r.headers["content-encoding"] == "br" and raw == b"stand-in brotli"
        assert r.headers["content-type"].startswith("text/javascript")
        assert r.headers["cache-control"] == ASSET_CACHE and r.headers["vary"].lower() == "accept-encoding"
        r, raw = _raw(c, "/assets/app-abc123.js", "gzip")
        assert r.headers["content-encoding"] == "gzip" and gzip.decompress(raw) == body
        r, raw = _raw(c, "/assets/app-abc123.js", "br;q=0, gzip")
        assert r.headers["content-encoding"] == "gzip"
        r, raw = _raw(c, "/assets/app-abc123.js", "identity")
        assert "content-encoding" not in r.headers and raw == body
        r, raw = _raw(c, "/assets/tiny-abc123.css", "br, gzip")
        assert "content-encoding" not in r.headers and raw == b"a{}"


def test_accept_encoding_is_read_by_name_and_q():
    from steward.web import accepts
    assert accepts("gzip, deflate, br", "br") and accepts("BR;q=0.5", "br")
    assert not accepts("gzip", "br") and not accepts("br;q=0", "br") and not accepts("br; q=0.000", "br")
    assert not accepts("", "gzip")
