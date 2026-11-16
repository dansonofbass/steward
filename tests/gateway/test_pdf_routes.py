"""Opening PDFs for the NAS (remote-reading P57-P61): the pairing token, a raw PDF under a cap applied before routing,
health listing extract and render only while this machine's filter and wall hold, the same sandbox as the NAS's, one
child at a time; the PDF in memory only and never in a log."""
import ast
import asyncio
import logging
import tempfile
import threading
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from steward_gateway import cli
from steward_gateway.app import create_gateway_app
from steward_gateway.bodycap import limit_for
from steward_gateway.pdf import PDF_OFF, PdfReader
from steward_gateway.redact.patterns import PatternDetector
from steward_gateway.secrets import write_private
from steward_pdf import sandbox as S
from tests.gateway.fakes import FakeCategorizer, FakeStatementModel
from tests.statement_files import pdf

TOKEN = "p" * 64
AUTH = {"Authorization": f"Bearer {TOKEN}"}
RAW = {**AUTH, "Content-Type": "application/pdf"}
WALLED = {"confined": True, "seccomp": 2, "walled": True, "probe": "refused", "canary": "ok"}


def gateway(gw_cfg, reader):
    write_private(gw_cfg.token_path, TOKEN)
    return TestClient(create_gateway_app(gw_cfg, detectors=[PatternDetector()], client=None, categorizer=FakeCategorizer(),
                                         statements=FakeStatementModel(features=("layout",)), pdf=reader))


def never(*_a, **_k):
    raise AssertionError("a child ran")


def test_without_the_wall_the_gateway_neither_lists_nor_opens_pdfs(gw_cfg):
    for report in ({}, {**WALLED, "seccomp": 0}, {**WALLED, "walled": False}, {**WALLED, "probe": "allowed"},
                   {**WALLED, "canary": "failed"}):
        with gateway(gw_cfg, PdfReader(check=lambda r=report: r, extract=never, render=never)) as c:
            assert c.get("/v1/health", headers=AUTH).json()["statement_features"] == ["layout"], report
            r = c.post("/v1/statements/extract", content=b"%PDF-1.4", headers=RAW)
            assert (r.status_code, r.json()) == (503, {"error": PDF_OFF})
            assert c.post("/v1/statements/render?page=1", content=b"%PDF-1.4", headers=RAW).status_code == 503


def test_an_off_reader_answers_503_before_reading_the_body(gw_cfg):
    """A walled-off gateway never buffers a 15 MB PDF only to refuse it: the check comes before the body."""
    write_private(gw_cfg.token_path, TOKEN)
    inner = create_gateway_app(gw_cfg, detectors=[PatternDetector()], client=None, categorizer=FakeCategorizer(),
                               statements=FakeStatementModel(features=("layout",)),
                               pdf=PdfReader(check=lambda: {**WALLED, "walled": False}, extract=never, render=never))

    async def app(scope, receive, send):
        async def unread():
            raise AssertionError("the body was read")
        await inner(scope, unread if scope["type"] == "http" else receive, send)
    with TestClient(app) as c:
        r = c.post("/v1/statements/extract", content=b"%PDF-1.4", headers=RAW)
        assert (r.status_code, r.json()) == (503, {"error": PDF_OFF})
        r = c.post("/v1/statements/render?page=1", content=b"%PDF-1.4", headers=RAW)
        assert (r.status_code, r.json()) == (503, {"error": PDF_OFF})


def test_walled_it_lists_both_and_opens_a_statement_in_the_real_sandbox(gw_cfg):
    data = pdf("chase_checking")[0]
    with gateway(gw_cfg, PdfReader(check=lambda: WALLED)) as c:
        assert c.get("/v1/health", headers=AUTH).json()["statement_features"] == ["layout", "extract", "render"]
        r = c.post("/v1/statements/extract", content=data, headers=RAW)
        assert r.status_code == 200 and r.json() == {"pages": S.read_pdf(data)["pages"]}
        pic = c.post("/v1/statements/render?page=1", content=data, headers=RAW)
        assert pic.status_code == 200 and S.parse_render(pic.content, 1).error is None
        bad = c.post("/v1/statements/extract", content=b"%PDF-1.4 not really", headers=RAW)
        assert (bad.status_code, bad.json()) == (200, {"error": "unreadable"})


def test_the_routes_need_the_token_a_pdf_and_a_page(gw_cfg):
    with gateway(gw_cfg, PdfReader(check=lambda: WALLED, extract=never, render=never)) as c:
        assert c.post("/v1/statements/extract", content=b"%PDF-", headers={"Content-Type": "application/pdf"}).status_code == 401
        assert c.post("/v1/statements/extract", content=b"%PDF-", headers={**AUTH, "Content-Type": "application/json"}).status_code == 415
        assert c.post("/v1/statements/extract", content=b"", headers=RAW).status_code == 422
        for page in ("", "0", "61", "x", "1.5", "-1", "١"):
            assert c.post("/v1/statements/render", params={"page": page}, content=b"%PDF-", headers=RAW).status_code == 422, page


def test_a_body_past_the_cap_is_refused_before_the_route(gw_cfg, monkeypatch):
    cap = 15 * 1024 * 1024 + 64 * 1024
    assert limit_for("/v1/statements/extract") == limit_for("/v1/statements/render") == cap
    monkeypatch.setattr("steward_gateway.app.read_pdf_body", never)
    with gateway(gw_cfg, PdfReader(check=lambda: WALLED, extract=never, render=never)) as c:
        assert c.post("/v1/statements/extract", content=b"0" * (cap + 1), headers=RAW).status_code == 413
        assert c.post("/v1/statements/render?page=1", content=b"0" * (cap + 1), headers=RAW).status_code == 413


def test_one_pdf_at_a_time():
    entered, go, started = threading.Event(), threading.Event(), []

    def slow(data, **_k):
        started.append(bytes(data))
        entered.set()
        go.wait()
        return S.Outcome([], None)

    async def run():
        reader = PdfReader(check=lambda: WALLED, extract=slow)
        first = asyncio.create_task(reader.extract(b"%PDF-1"))
        await asyncio.to_thread(entered.wait)
        second = asyncio.create_task(reader.extract(b"%PDF-2"))
        for _ in range(5):
            await asyncio.sleep(0)
        assert started == [b"%PDF-1"]
        assert not second.done() and reader._one.locked()
        go.set()
        await asyncio.gather(first, second)
        assert started == [b"%PDF-1", b"%PDF-2"]
    asyncio.run(run())


def test_the_gateway_runs_the_one_child_that_requires_the_wall():
    """P59: the check at startup can go stale, so the child itself refuses to read without the wall, on every machine
    (tests/test_pdf_wall.py); the gateway passes it nothing that could change that."""
    calls = []

    def extract(data, **k):
        calls.append(("extract", k))
        return S.Outcome([], None)

    def render(data, n, **k):
        calls.append(("render", k))
        return S.Rendered(None, 0, 0, "unreadable")

    async def run():
        reader = PdfReader(check=lambda: WALLED, extract=extract, render=render)
        await reader.extract(b"%PDF-1")
        await reader.render(b"%PDF-1", 1)
    asyncio.run(run())
    assert calls == [("extract", {}), ("render", {})]


def test_logs_carry_counts_and_times_never_a_word_or_the_pdf(gw_cfg, caplog):
    caplog.set_level(logging.INFO)
    data, truth = pdf("chase_checking")
    with gateway(gw_cfg, PdfReader(check=lambda: WALLED)) as c:
        c.post("/v1/statements/extract", content=data, headers=RAW)
        c.post("/v1/statements/render?page=1", content=data, headers=RAW)
    assert "statements.extract.done" in caplog.text and "statements.render.done" in caplog.text
    amount = f"{abs(truth.rows[0]['amount_cents']) / 100:,.2f}"
    for word in (truth.institution, truth.rows[0]["description"], amount, "%PDF"):
        assert word not in caplog.text


def test_nothing_is_left_on_disk(gw_cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    data = pdf("chase_checking")[0]
    with gateway(gw_cfg, PdfReader(check=lambda: WALLED)) as c:
        before = (sorted(p.name for p in tmp_path.glob("steward-pdf-*")), sorted(p.name for p in gw_cfg.state_dir.iterdir()))
        c.post("/v1/statements/extract", content=data, headers=RAW)
        c.post("/v1/statements/render?page=1", content=data, headers=RAW)
        after = (sorted(p.name for p in tmp_path.glob("steward-pdf-*")), sorted(p.name for p in gw_cfg.state_dir.iterdir()))
    assert after == before


def test_the_pdf_reader_imports_no_anthropic_client():
    import steward_gateway.pdf as P
    tree = ast.parse(Path(P.__file__).read_text())
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not any(x.split(".")[0] == "anthropic" for x in names)


def test_pdf_check_says_whether_gateway_opens_pdfs(monkeypatch):
    monkeypatch.setattr(S, "confinement", lambda **_k: dict(WALLED))
    r = CliRunner().invoke(cli.app, ["pdf-check"])
    assert r.exit_code == 0 and "This machine opens PDFs for Steward." in r.output
    monkeypatch.setattr(S, "confinement", lambda **_k: {**WALLED, "walled": False, "probe": "allowed"})
    r = CliRunner().invoke(cli.app, ["pdf-check"])
    assert r.exit_code == 1 and "Reads walled off (Landlock): off" in r.output and "docs/guides/gateway.md" in r.output


def test_pdf_check_says_it_cant_tell_without_a_probe_file(monkeypatch):
    """No /etc/passwd to try: the wall can't be shown to hold, so the check says so and PDFs stay off."""
    monkeypatch.setattr(S, "confinement", lambda **_k: {**WALLED, "probe": "missing"})
    r = CliRunner().invoke(cli.app, ["pdf-check"])
    assert r.exit_code == 1
    assert "Reads walled off (Landlock): can't tell (no probe file)" in r.output
    assert "Reads walled off (Landlock): off" not in r.output and "won't open PDFs" in r.output
