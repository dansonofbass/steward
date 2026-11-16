"""The page route (spec P25-P30): the token, a 5 MB cap before parsing, the PNG checked by its header, the answer held
to P25's schema, the vision model's context stepped down until it sits wholly on the GPU; the image in memory only."""
import ast
import asyncio
import base64
import json
import logging
import struct
import zlib
from pathlib import Path

import httpx2
from fastapi.testclient import TestClient

from steward_boundary.statements_wire import PAGE_SCHEMA, page_answer_errors, png_size
from steward_gateway import statements as S
from steward_gateway.app import create_gateway_app
from steward_gateway.pdf import PdfReader
from steward_gateway.redact.patterns import PatternDetector
from steward_gateway.secrets import write_private
from steward_gateway.statements import StatementModel, StatementsAway
from tests.gateway.fakes import FakeCategorizer, FakeStatementModel

TOKEN = "p" * 64
AUTH = {"Authorization": f"Bearer {TOKEN}"}
URL = "http://127.0.0.1:11434"
VISION = "gemma4:12b-it-qat"


def png(w: int = 1700, h: int = 2200) -> bytes:
    raw = b"".join(b"\x00" + b"\xff" * w for _ in range(4))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


ANSWER = {"page_kind": "transactions", "institution": "Harborview Bank", "account_last4": "3456",
          "period": {"start": "March 1, 2026", "end": "March 31, 2026"}, "opening": "5,320.77", "closing": "6,104.10",
          "rows": [{"date": "03/02/26", "description": "ZORBLAX PAYROLL", "amount": "2,418.00", "way": "in", "section": None}],
          "holdings": [], "total": None}


def body(image: bytes | None = None, **over):
    image = png() if image is None else image
    return {"page": 1, "of": 2, "image": base64.b64encode(image).decode(), "width_px": 1700, "height_px": 2200,
            "want": "rows", **over}


def client(gw_cfg, statements):
    write_private(gw_cfg.token_path, TOKEN)
    return TestClient(create_gateway_app(gw_cfg, detectors=[PatternDetector()], client=None, statements=statements,
                                         categorizer=FakeCategorizer(), pdf=PdfReader(check=dict)))


def test_the_route_answers_a_checked_page(gw_cfg):
    fake = FakeStatementModel(page=ANSWER)
    with client(gw_cfg, fake) as c:
        assert c.post("/v1/statements/page", json=body()).status_code == 401
        r = c.post("/v1/statements/page", json=body(), headers=AUTH)
    assert (r.status_code, r.json()) == (200, {"page": ANSWER, "model": "stand-in-vision"})


def test_bad_pages_are_422_and_never_reach_the_model(gw_cfg):
    fake = FakeStatementModel(page=ANSWER)
    with client(gw_cfg, fake) as c:
        for b in (body(image=b"GIF89a" + b"\x00" * 100), body(image=png(2401, 2200), width_px=2401),
                  body(width_px=1600), body(want="everything"), body(page=3), body(page=0), {**body(), "x": 1},
                  {**body(), "image": "not base64!"}):
            assert c.post("/v1/statements/page", json=b, headers=AUTH).status_code == 422, b.get("want")
        big = body(image=png() + b"\x00" * (3 * 1024 * 1024))
        assert c.post("/v1/statements/page", json=big, headers=AUTH).status_code == 422
    assert fake.page_calls == []


def test_a_body_over_5_mb_is_413_before_parsing(gw_cfg):
    fake = FakeStatementModel(page=ANSWER)
    with client(gw_cfg, fake) as c:
        r = c.post("/v1/statements/page", content=b"{" + b" " * (5 * 1024 * 1024),
                   headers={**AUTH, "content-type": "application/json"})
    assert r.status_code == 413 and fake.page_calls == []


def test_the_page_route_logs_counts_only_and_writes_nothing(gw_cfg, caplog):
    caplog.set_level(logging.INFO)

    def listing():
        return sorted(str(p) for d in (gw_cfg.state_dir, gw_cfg.config_dir) for p in Path(d).rglob("*"))
    with client(gw_cfg, FakeStatementModel(page=ANSWER)) as c:
        before = listing()                                   # after start-up, which makes the ledger
        c.post("/v1/statements/page", json=body(), headers=AUTH)
        assert listing() == before
    assert "statements.page.done" in caplog.text
    for word in ("ZORBLAX", "Harborview", "2,418.00", "3456", "iVBOR"):
        assert word not in caplog.text


def test_health_lists_scan_only_with_the_vision_model(gw_cfg):
    with client(gw_cfg, FakeStatementModel(features=("layout",))) as c:
        assert c.get("/v1/health", headers=AUTH).json()["statement_features"] == ["layout"]
    with client(gw_cfg, FakeStatementModel(features=("layout", "scan"))) as c:
        assert c.get("/v1/health", headers=AUTH).json()["statement_features"] == ["layout", "scan"]


def test_png_size_reads_the_header_only():
    assert png_size(png(1700, 2200)) == (1700, 2200)
    assert png_size(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8) is None
    assert png_size(b"GIF89a") is None
    good = png(1700, 2200)
    assert png_size(good[:8] + b"\x00\x00\x00\x0e" + good[12:]) is None          # an IHDR that isn't 13 bytes long
    assert png_size(good[:29] + bytes([good[29] ^ 1]) + good[30:]) is None        # its CRC is wrong


def test_the_answer_is_held_to_p25():
    assert page_answer_errors(ANSWER) == []
    for bad in ({**ANSWER, "rows": [ANSWER["rows"][0]] * 151}, {**ANSWER, "x": 1}, {**ANSWER, "page_kind": "other stuff"},
                {**ANSWER, "rows": [{**ANSWER["rows"][0], "way": "sideways"}]},
                {**ANSWER, "rows": [{**ANSWER["rows"][0], "description": "x" * 201}]},
                {**ANSWER, "account_last4": "12345"}):
        assert page_answer_errors(bad), bad


def _ollama(ps_sizes: list[tuple[int, int]], seen: list):
    """A stand-in Ollama: each /api/ps answers the next (size, size_vram); generate records what it was asked."""
    sizes = list(ps_sizes)

    async def handler(request):
        if request.url.path == "/api/show":
            return httpx2.Response(200, json={"capabilities": ["completion", "vision"]})
        if request.url.path == "/api/ps":
            size, vram = sizes.pop(0) if sizes else (10, 10)
            return httpx2.Response(200, json={"models": [{"name": VISION, "size": size, "size_vram": vram}]})
        b = json.loads(request.content)
        seen.append(b)
        return httpx2.Response(200, json={"response": json.dumps(ANSWER)} if b.get("prompt") else {"response": ""})
    return StatementModel(URL, "qwen3.5:9b-q4_K_M", vision_model=VISION,
                          http=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))


def test_the_context_steps_down_until_it_fits_or_refuses():
    seen: list = []
    m = _ollama([(14, 10), (12, 12)], seen)
    assert asyncio.run(m.page(body())) == ANSWER
    loads = [(b.get("options", {}).get("num_ctx"), b.get("keep_alive")) for b in seen if not b.get("prompt")]
    assert loads == [(16384, "5m"), (None, 0), (12288, "5m")]
    asked = next(b for b in seen if b.get("prompt"))
    assert asked["options"]["num_ctx"] == 12288 and asked["format"] == PAGE_SCHEMA and asked["images"]
    seen2: list = []
    never = _ollama([(14, 10), (14, 10), (14, 10)], seen2)
    try:
        asyncio.run(never.page(body()))
        raise AssertionError("no StatementsAway")
    except StatementsAway:
        pass
    assert not any(b.get("prompt") for b in seen2)                      # never ran half on the CPU


def test_the_module_still_imports_no_anthropic_client():
    tree = ast.parse(Path(S.__file__).read_text())
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not any(n.split(".")[0] in ("anthropic", "tempfile", "shutil") for n in names)


def _vision_ollama(answer: dict, events: list | None = None, wait_idle=None):
    async def handler(request):
        if request.url.path == "/api/show":
            return httpx2.Response(200, json={"capabilities": ["completion", "vision"]})
        if request.url.path == "/api/ps":
            return httpx2.Response(200, json={"models": [{"name": VISION, "size": 10, "size_vram": 10}]})
        b = json.loads(request.content)
        if not b.get("prompt"):
            return httpx2.Response(200, json={"response": ""})
        if events is not None:
            events.append("start")
            await asyncio.sleep(0)
            events.append("end")
        return httpx2.Response(200, json={"response": json.dumps(answer)})
    return StatementModel(URL, "qwen3.5:9b-q4_K_M", vision_model=VISION, wait_idle=wait_idle,
                          http=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))


def test_a_page_waits_for_the_categorizer_and_for_the_one_lock():
    events: list[str] = []

    async def wait_idle():
        events.append("idle")
    m = _vision_ollama(ANSWER, events, wait_idle)

    async def go():
        await m._one.acquire()                                       # a layout is running
        task = asyncio.create_task(m.page(body()))
        for _ in range(10):                                          # let it run as far as it can
            await asyncio.sleep(0)
        assert events == []                                          # the page waits behind it, and for no one else
        m._one.release()
        await task
    asyncio.run(go())
    assert events == ["idle", "start", "end"]                        # the categorizer first, then the page


def test_an_answer_off_the_schema_is_away_and_503_at_the_route(gw_cfg):
    m = _vision_ollama({**ANSWER, "page_kind": "poetry"})
    try:
        asyncio.run(m.page(body()))
        raise AssertionError("no StatementsAway")
    except StatementsAway:
        pass
    with client(gw_cfg, FakeStatementModel(page=None)) as c:
        r = c.post("/v1/statements/page", json=body(), headers=AUTH)
    assert r.status_code == 503 and r.json() == {"error": S.STATEMENTS_AWAY}


def test_features_lists_scan_only_when_the_vision_model_is_pulled():
    def model(names):
        async def handler(request):
            return httpx2.Response(200, json={"models": [{"name": n} for n in names]})
        return StatementModel(URL, "qwen3.5:9b-q4_K_M", vision_model=VISION,
                              http=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    assert asyncio.run(model(["qwen3.5:9b-q4_K_M"]).features()) == ["layout", "holdings"]
    assert asyncio.run(model(["qwen3.5:9b-q4_K_M", VISION]).features()) == ["layout", "holdings", "scan"]
    assert asyncio.run(model([VISION]).features()) == ["holdings", "scan"]
