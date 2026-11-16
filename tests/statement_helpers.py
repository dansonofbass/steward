"""Driving statements from tests: raw PDF uploads, a deterministic stand-in for the gateway, and a remembered layout."""
from __future__ import annotations

import io
import json
from datetime import date, datetime, timezone
from urllib.parse import quote

from steward.db.models import StatementLayout
from steward.services.statements import layouts
from steward_gateway.evals.statement_set import BANK_CARD, HOLDINGS, LOANS
from tests.statement_files import pages, pdf


def upload(client, name: str, data: bytes, slug: str = "ours", batch: str | None = None):
    url = f"/api/b/{slug}/import/statements" + (f"?batch={batch}" if batch else "")
    return client.post(url, content=data, headers={"content-type": "application/pdf", "x-filename": quote(name)})


def truthful(sent, hint):
    """A perfect proposal, from the synthetic set's truth, chosen by the institution printed on the page."""
    for sid in BANK_CARD + HOLDINGS + LOANS:
        truth = pdf(sid)[1]
        if any(truth.institution in c["text"] for p in sent for ln in p["lines"] for c in ln["cells"]):
            return truth.layout
    return None


class StandIn:
    """The stand-in statement client: deterministic answers, and a count of every request (P23's "no layout request")."""
    paired = True
    last_error = None

    def __init__(self, answer=truthful, pages=None):
        self.answer, self.calls = answer, []
        self.pages, self.page_calls = pages, []

    def layout(self, sent, hint):
        self.calls.append(hint)
        return self.answer(sent, hint) if callable(self.answer) else self.answer

    def page(self, png, n, of, width, height, want="rows"):
        self.page_calls.append((n, of, want))
        assert png.startswith(b"\x89PNG") and max(width, height) <= 2200
        answers = self.pages(n) if callable(self.pages) else self.pages
        if answers is None:
            return None
        return answers[n - 1] if isinstance(answers, list) else answers

    def close(self):
        pass


def _words(d):
    return f"{d:%B} {d.day}, {d.year}"


def truth_answers(truth, slip_cents: int = 0) -> list[dict]:
    """What a perfect vision model reads off each page, as printed: page 1 carries the facts; each page its rows. A
    slip adds slip_cents to the first row's printed amount (a single misread digit)."""
    out = []
    for n in range(1, truth.pages + 1):
        rows = [{"date": f"{date.fromisoformat(r['date']):%m/%d}", "description": r["description"],
                 "amount": f"{abs(r['amount_cents']) / 100:,.2f}", "way": "in" if r["amount_cents"] > 0 else "out",
                 "section": r["section"]} for r in truth.rows if r["page"] == n]
        first = n == 1
        holdings = [{"symbol": x["symbol"], "name": x["name"],
                     "shares": f"{x['shares_milli'] / 1000:,.3f}" if x["shares_milli"] else None,
                     "value": f"{x['value_cents'] / 100:,.2f}"} for x in truth.holdings] if first else []
        out.append({"page_kind": "holdings" if holdings else "transactions" if rows else "summary",
                    "institution": truth.institution if first else None, "account_last4": truth.last4 if first else None,
                    "period": {"start": _words(truth.period[0]), "end": _words(truth.period[1])} if first else None,
                    "opening": f"{truth.opening_cents / 100:,.2f}" if first else None,
                    "closing": f"{truth.closing_cents / 100:,.2f}" if first else None,
                    "rows": rows, "holdings": holdings,
                    "total": f"{truth.total_cents / 100:,.2f}" if first and truth.total_cents is not None else None})
    if slip_cents:
        r = next(r for a in out for r in a["rows"])
        r["amount"] = f"{(float(r['amount'].replace(',', '')) * 100 + slip_cents) / 100:,.2f}"
    return out


def answering(app, client: StandIn, features=("layout",)) -> StandIn:
    """Pairs the app's reader with the stand-in and a gateway that answers with these features."""
    reader = app.state.statements
    reader.client = client
    health = {"statement_features": list(features)}
    reader.health = lambda: health
    reader.peek = lambda: health
    return client


def scanned_pdf() -> bytes:
    """A one-page PDF that is only a picture: no text layer (P10)."""
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    img = Image.new("L", (850, 1100), 255)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 792), invariant=1)
    c.drawImage(ImageReader(img), 0, 0, width=612, height=792)
    c.showPage()
    c.save()
    return buf.getvalue()


def remember(db, sid: str, account_id: int | None = None) -> StatementLayout:
    """A layout remembered as "Looks right" would save it, from the statement's truth."""
    from sqlalchemy import select
    truth = pdf(sid)[1]
    a = layouts.anchors(truth.layout, pages(sid))
    found = db.scalar(select(StatementLayout).where(StatementLayout.key == layouts.key_of(a)))
    if found is not None:
        return found
    row = StatementLayout(key=layouts.key_of(a), label=truth.institution[:60], kind=truth.kind, anchors=json.dumps(a),
                          rules=json.dumps(truth.layout), account_id=account_id, model="qwen3.5:9b-q4_K_M",
                          created_at=datetime(2026, 10, 1, tzinfo=timezone.utc), confirmed_by=1, uses=1)
    db.add(row)
    db.commit()
    return row


def chase_card_csv(truth) -> bytes:
    """The same month as a Chase card CSV download (the import round's known format: purchases negative)."""
    lines = ["Transaction Date,Post Date,Description,Category,Type,Amount,Memo"]
    for r in truth.rows:
        y, m, d = r["date"].split("-")
        lines.append(f'{m}/{d}/{y},{m}/{d}/{y},{r["description"]},Shopping,Sale,{r["amount_cents"] / 100:.2f},')
    return ("\n".join(lines) + "\n").encode()


def commit(client, statements: list[dict], files=(), batch: str | None = None, slug: str = "ours"):
    """Preview then commit: statements are {"id", "account_id", "include"}; files the import round's file choices."""
    body = {"batch": batch, "files": list(files), "statements": statements, "simplefin_include": []}
    p = client.post(f"/api/b/{slug}/import/batch/preview", json=body)
    assert p.status_code == 200, p.text
    return client.post(f"/api/b/{slug}/import/batch/commit", json={**body, "digest": p.json()["digest"]})


class RemoteStandIn(StandIn):
    """The gateway opening PDFs too (remote-reading P57): by default the child's own functions in this process, answered
    through the NAS's own checks; or a fixed answer (AWAY, None, an Outcome or a Rendered), or a function of the bytes."""

    def __init__(self, answer=truthful, pages=None, extract=None, render=None):
        super().__init__(answer, pages)
        self.extract_answer, self.render_answer = extract, render
        self.extract_calls, self.render_calls = [], []

    def extract(self, data):
        self.extract_calls.append(len(data))
        if self.extract_answer is not None:
            return self.extract_answer(data) if callable(self.extract_answer) else self.extract_answer
        from steward_pdf.sandbox import Refused, parse_extract, read_pdf
        try:
            body = read_pdf(bytes(data))
        except Refused as e:
            body = {"error": e.key}
        return parse_extract(json.dumps(body).encode())

    def render(self, data, n):
        self.render_calls.append(n)
        if self.render_answer is not None:
            return self.render_answer(data, n) if callable(self.render_answer) else self.render_answer
        from steward_pdf.sandbox import Refused, parse_render, render_page
        try:
            body = render_page(bytes(data), n)
        except Refused as e:
            body = {"error": e.key}
        return parse_render(json.dumps(body).encode(), n)


REMOTE = ("layout", "holdings", "scan", "extract", "render")
