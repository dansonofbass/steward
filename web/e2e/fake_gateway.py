"""A fake gateway for the Playwright suite (spec 11.5): the real steward_gateway app, with stand-in detectors, in
front of the fake Anthropic server, both on 127.0.0.1. Nothing reaches Anthropic and no key is used. The scripted
model answers by the question's words. Test-only controls under /__e2e: away (every HTTP call answers 503, so the NAS
sees the gateway as away), spend (settled spending on this month's ledger, to reach the cap), pdf-calls (how many PDFs it
opened and pages it rendered) and reset.

Run by web/e2e/server.sh: python web/e2e/fake_gateway.py <port> <config_dir> <state_dir>, with PYTHONPATH at the
repository root so tests.gateway.fake_anthropic imports."""
from __future__ import annotations

import re
import sqlite3
import sys
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import Request

E2E_TOKEN = "e2e0" * 16
STORES = ("Bright Smile Ortho",)
from steward_gateway.categorize import CategorizerAway  # noqa: E402
from steward_gateway.pdf import PdfReader  # noqa: E402
from steward_gateway.redact import Span  # noqa: E402
from tests.gateway.fake_anthropic import FakeAnthropic, Reply, text, tool_use  # noqa: E402


class StoreNameDetector:
    """Tags the invented store names the way GLiNER tags an organization."""
    name = "gliner"

    def detect(self, value: str) -> list[Span]:
        return [Span(m.start(), m.end(), "[organization]", "gliner")
                for s in STORES for m in re.finditer(re.escape(s), value, re.IGNORECASE)]


class NoOllama:
    async def answering(self) -> bool:
        return False

    async def title(self, value: str) -> None:
        return None

    async def close(self) -> None:
        pass


class NoCategorizer:
    """No local model: every batch is away at once, so the NAS falls back to its rules, as on a machine with no
    Ollama. The real Categorizer would ask Ollama on 127.0.0.1, which on the gateway is the real model (about 7 s a
    batch), and where nothing listens a connection can hang until its 20 s timeout."""

    async def ready(self) -> bool:
        return False

    async def categorize(self, rows, examples=()) -> list:
        raise CategorizerAway()

    async def close(self) -> None:
        pass


def _texts(m: dict) -> list[str]:
    c = m.get("content")
    return [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"] if isinstance(c, list) else []


def _question(body: dict) -> tuple[str, list[dict]]:
    msgs = body["messages"]
    idx = [i for i, m in enumerate(msgs) if m["role"] == "user" and _texts(m)]
    if not idx:  # the gateway's prewarm sends a placeholder with no text blocks
        return "", []
    qi = max(idx)
    results = [b for m in msgs[qi:] if m["role"] == "user" and isinstance(m["content"], list)
               for b in m["content"] if b.get("type") == "tool_result"]
    return " ".join(_texts(msgs[qi])).lower(), results


def script(body: dict, n: int) -> Reply:
    q, results = _question(body)
    today = date.today()
    if "dining" in q:
        if not results:
            return Reply([tool_use(f"toolu_{n}_1", "spending_by_category",
                                   {"start": (today - timedelta(days=90)).isoformat(), "end": today.isoformat(),
                                    "compare_previous": True})], stop_reason="tool_use")
        return Reply([text("Yes. Dining came to **$9,184** over the last 12 months, up $1,412. About 60% of it is on "
                           "Person 2's cards.")])
    if "subscriptions" in q or "anything odd" in q:
        if not results:
            first = ("recurring", {}) if "subscriptions" in q else ("flags", {"include_done": False})
            return Reply([tool_use(f"toolu_{n}_1", *first)], stop_reason="tool_use")
        if len(results) == 1:
            return Reply([tool_use(f"toolu_{n}_2", "merchant_detail", {
                "reason": "Totals show the monthly payments but not what they are.",
                "start": (today - timedelta(days=31)).isoformat(), "end": today.isoformat(), "category": None,
                "payees": None})], stop_reason="tool_use")
        if results[-1].get("is_error"):
            return Reply([text("From totals: the monthly payments come to $93.98. Without store names I can't say "
                               "which services they are.")])
        return Reply([text("Here they are by store, from the rows you approved.")])
    return Reply([text("Net worth is about $1.2 million, most of it in Person 1's retirement accounts.")])


class CountingPdf(PdfReader):
    """The real sandbox, counted (remote-reading P72): the e2e NAS runs in gateway mode and opens every PDF here. Its
    check always passes; the child still confines and walls itself, and refuses the PDF if it can't."""
    WALLED = {"confined": True, "seccomp": 2, "walled": True, "probe": "refused", "canary": "ok"}

    def __init__(self):
        super().__init__(check=lambda: dict(self.WALLED))
        self.calls = {"extract": 0, "render": 0}

    async def extract(self, data):
        self.calls["extract"] += 1
        return await super().extract(data)

    async def render(self, data, n):
        self.calls["render"] += 1
        return await super().render(data, n)


class FakeStatements:
    """The statement model for the e2e (spec, e2e): a perfect layout from the synthetic set's truth, chosen by the
    institution printed on the page, and a count of layout requests."""
    layout_model = "e2e-stand-in"
    vision_model = "e2e-stand-in-vision"

    def __init__(self):
        self.calls = 0
        self.scan_truth: tuple[str, str, int] | None = None      # (sid, end, slip), named by the test

    async def features(self):
        return ["layout", "holdings", "scan"]

    async def page(self, request):
        """Answers as a perfect vision model would for the statement the test named (it can't read the image)."""
        from datetime import date as day

        from steward_gateway.evals.statement_set import build
        from steward_gateway.statements import StatementsAway
        from tests.statement_helpers import truth_answers
        if self.scan_truth is None:
            raise StatementsAway()
        sid, end, slip = self.scan_truth
        answers = truth_answers(build(sid, end=day.fromisoformat(end))[1], slip_cents=slip)
        return answers[request["page"] - 1]

    async def layout(self, pages, hint):
        from steward_gateway.evals.statement_set import BANK_CARD, HOLDINGS, LOANS, build
        from steward_gateway.statements import StatementsAway
        self.calls += 1
        for sid in (*BANK_CARD, *HOLDINGS, *LOANS):
            truth = build(sid)[1]
            if any(truth.institution in c["text"] for p in pages for ln in p["lines"] for c in ln["cells"]):
                return truth.layout
        raise StatementsAway()

    async def close(self):
        pass


def main() -> None:
    import anthropic
    import uvicorn
    from fastapi.responses import JSONResponse

    from steward_gateway.app import create_gateway_app
    from steward_gateway.config import GatewayConfig
    from steward_gateway.ledger import Ledger
    from steward_gateway.pairing import arm
    from steward_gateway.redact.patterns import PatternDetector
    from steward_gateway.secrets import write_private

    port, config_dir, state_dir = int(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    for d in (config_dir, state_dir):
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
    cfg = GatewayConfig(config_dir, state_dir, mcp=True)   # JR's gateway has Claude Code on; the shots keep it
    write_private(cfg.token_path, E2E_TOKEN)
    fake = FakeAnthropic(script)
    threading.Thread(target=uvicorn.run, args=(fake.app(),),
                     kwargs={"host": "127.0.0.1", "port": port + 1, "log_level": "warning"}, daemon=True).start()
    client = anthropic.AsyncAnthropic(api_key="test-key-not-real", base_url=f"http://127.0.0.1:{port + 1}", max_retries=0)
    fake_statements = FakeStatements()
    fake_pdf = CountingPdf()
    ledger = Ledger(cfg.ledger_path, cfg.timezone, cfg.default_cap_cents, cfg.max_cap_cents, cfg.default_model)
    app = create_gateway_app(cfg, client=client, ledger=ledger, detectors=[PatternDetector(), StoreNameDetector()],
                             ollama=NoOllama(), categorizer=NoCategorizer(), statements=fake_statements, pdf=fake_pdf)
    state = {"away": False}

    @app.middleware("http")
    async def away(request: Request, call_next):
        if state["away"] and not request.url.path.startswith("/__e2e"):
            return JSONResponse({"error": "{gateway} is away (e2e)."}, status_code=503)
        return await call_next(request)

    @app.post("/__e2e/away")
    async def set_away(request: Request):
        state["away"] = bool((await request.json()).get("away"))
        return {"away": state["away"]}

    @app.post("/__e2e/arm")
    async def arm_pairing(request: Request):
        arm(cfg, (await request.json())["code"], datetime.now(timezone.utc))
        return {"ok": True}

    @app.post("/__e2e/spend")
    async def spend(request: Request):
        cents = int((await request.json())["cents"])
        rid = ledger.reserve(now=datetime.now(timezone.utc), book_id=None, user_id=None, turn_id=None, channel="check",
                             model=cfg.default_model, estimate_nd=0)
        ledger.settle(rid, cents * 10_000_000)
        return {"ok": True}

    @app.get("/__e2e/statement")
    async def statement_pdf(sid: str, end: str, variant: str | None = None):
        """A synthetic statement PDF for the browser to drop (never written to disk)."""
        from fastapi.responses import Response
        from steward_gateway.evals.statement_set import build
        data, _ = build(sid, end=date.fromisoformat(end), variant=variant)
        return Response(data, media_type="application/pdf")

    @app.get("/__e2e/statement-calls")
    async def statement_calls():
        return {"calls": fake_statements.calls}

    @app.get("/__e2e/pdf-calls")
    async def pdf_calls():
        return dict(fake_pdf.calls)

    @app.post("/__e2e/scan-truth")
    async def scan_truth(request: Request):
        b = await request.json()
        fake_statements.scan_truth = (b["sid"], b["end"], int(b.get("slip", 0)))
        return {"ok": True}

    @app.post("/__e2e/reset")
    async def reset():
        state["away"] = False
        fake_statements.calls = 0
        fake_pdf.calls = {"extract": 0, "render": 0}
        fake_statements.scan_truth = None
        with sqlite3.connect(cfg.ledger_path) as c:
            c.execute("DELETE FROM spend")
        return {"ok": True}

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
