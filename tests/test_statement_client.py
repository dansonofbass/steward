"""The NAS's statement client (spec, The NAS side): the paired gateway with its token, one request at a time, the
answer held to the schema again; never raises; nothing when unpaired."""
import base64
import io
import json
import logging

import httpx2
import pytest

from steward.services.statements.client import (AWAY, HttpStatementClient, NullStatementClient, remote_state,
                                                statement_client_for, statement_features)
from steward_pdf.sandbox import OUT_CAP, Outcome, Rendered
from tests.gateway.test_statements import GOOD, PAGES
from tests.gateway.test_statements_page import ANSWER


def _client(handler):
    return HttpStatementClient("https://gateway.tail1234.ts.net:8430", "t" * 64, transport=httpx2.MockTransport(handler))


def test_a_layout_goes_with_the_token_and_comes_back_checked():
    seen = []

    def handler(request):
        seen.append((request.url.path, request.headers["authorization"], json.loads(request.content)))
        return httpx2.Response(200, json={"layout": GOOD, "model": "qwen3.5:9b-q4_K_M"})
    c = _client(handler)
    assert c.layout(PAGES, None) == GOOD and c.last_model == "qwen3.5:9b-q4_K_M"
    assert seen == [("/v1/statements/layout", "Bearer " + "t" * 64, {"pages": PAGES, "hint": None})]


def test_every_failure_is_none_with_plain_words():
    for handler in (lambda r: httpx2.Response(503, json={"error": "x"}), lambda r: httpx2.Response(200, json={"layout": {"kind": "bank"}}),
                    lambda r: httpx2.Response(200, content=b"not json")):
        c = _client(handler)
        assert c.layout(PAGES, None) is None and c.last_error

    def boom(request):
        raise httpx2.ConnectTimeout("slow")
    c = _client(boom)
    assert c.layout(PAGES, None) is None and c.last_error == "The gateway took too long to answer"


def test_features_and_the_gateway_state():
    assert statement_features({"statement_features": ["layout", 3]}) == frozenset({"layout"})
    assert statement_features({"categorizer": True}) is None
    paired = _client(lambda r: httpx2.Response(200, json={}))
    assert remote_state(NullStatementClient(), {"statement_features": ["layout"]}) == "unpaired"
    assert remote_state(paired, None) == "waiting"
    assert remote_state(paired, {"categorizer": True}) == "old"
    assert remote_state(paired, {"statement_features": []}) == "waiting"
    assert remote_state(paired, {"statement_features": ["layout"]}) == "answering"


def test_a_page_goes_with_the_token_and_comes_back_checked():
    seen = []

    def handler(request):
        seen.append((request.url.path, request.headers["authorization"], json.loads(request.content)))
        return httpx2.Response(200, json={"page": ANSWER, "model": "qwen3.5-vl"})
    c = _client(handler)
    assert c.page(b"\x89PNG", 1, 2, 10, 20) == ANSWER and (c.last_model, c.last_error) == ("qwen3.5-vl", None)
    assert seen == [("/v1/statements/page", "Bearer " + "t" * 64,
                     {"page": 1, "of": 2, "image": "iVBORw==", "width_px": 10, "height_px": 20, "want": "rows"})]


def _timeout(request):
    raise httpx2.ReadTimeout("slow")


@pytest.mark.parametrize("handler, words", [
    (_timeout, "The gateway took too long to answer"),
    (lambda r: httpx2.Response(502, json={"page": ANSWER}), "The gateway answered with an error (HTTP 502)"),
    (lambda r: httpx2.Response(200, content=b"<html>not json"), "The gateway sent a reply that could not be read"),
    (lambda r: httpx2.Response(200, json={"page": None, "model": "x"}), "The gateway sent a reply that could not be read"),
    (lambda r: httpx2.Response(200, json=[ANSWER]), "The gateway sent a reply that could not be read"),
], ids=["timeout", "non-200", "non-json", "null-page", "not-an-object"])
def test_a_page_that_fails_is_none_with_plain_words(handler, words):
    c = _client(handler)
    assert c.page(b"\x89PNG", 1, 1, 10, 10) is None and c.last_error == words and c.last_model is None


def test_unpaired_settings_give_the_null_client(settings):
    assert isinstance(statement_client_for(settings), NullStatementClient)


PAGE = {"n": 1, "width": 612.0, "height": 792.0, "scan": False,
        "lines": [{"y": 100.0, "cells": [{"x0": 40.0, "x1": 120.0, "text": "Opening balance"}]}]}


def _png(w=100, h=200, mode="L") -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new(mode, (w, h), 255).save(buf, "PNG")
    return buf.getvalue()


def _pic(png=None, n=1, **over) -> bytes:
    png = _png() if png is None else png
    return json.dumps({"png": base64.b64encode(png).decode(), "width_px": 100, "height_px": 200, "n": n,
                       **over}).encode()


def _answers(body: bytes, status: int = 200):
    seen = []

    def handler(request):
        seen.append((request.url.path, request.url.query, request.headers["content-type"],
                     request.headers["authorization"], request.content))
        return httpx2.Response(status, content=body)
    return _client(handler), seen


def test_a_pdf_goes_raw_with_the_token_and_comes_back_through_the_childs_checks():
    c, seen = _answers(json.dumps({"pages": [PAGE]}).encode())
    assert c.extract(b"%PDF-1.4 x") == Outcome([PAGE], None)
    assert seen == [("/v1/statements/extract", b"", "application/pdf", "Bearer " + "t" * 64, b"%PDF-1.4 x")]


def _page(**over):
    return {**PAGE, **over}


def _cell(text="x"):
    return {"x0": 1.0, "x1": 2.0, "text": text}


BAD_PAGES = [
    b"not json", b'{"pages": [NaN]}', b'{"pages": [], "pages": []}',
    json.dumps({"pages": [PAGE], "more": 1}).encode(),
    json.dumps({"pages": [_page(n=2)]}).encode(),
    json.dumps({"pages": [_page(n=k) for k in range(1, 62)]}).encode(),
    json.dumps({"pages": [_page(lines=[PAGE["lines"][0]] * 401)]}).encode(),
    json.dumps({"pages": [_page(lines=[{"y": 1.0, "cells": [_cell()] * 33}])]}).encode(),
    json.dumps({"pages": [_page(lines=[{"y": 1.0, "cells": [_cell("x" * 201)]}])]}).encode(),
    json.dumps({"pages": [_page(lines=[{"y": 1.0, "cells": [_cell("a\x07b")]}])]}).encode(),
    json.dumps({"pages": [_page(width=0)]}).encode(),
    json.dumps({"error": "not_a_key"}).encode(),
    json.dumps({"error": "password", "pages": []}).encode(),
]


@pytest.mark.parametrize("body", BAD_PAGES)
def test_every_check_on_the_childs_output_applies_to_gateway_answers(body):
    c, _ = _answers(body)
    assert c.extract(b"%PDF-") == Outcome(None, "unreadable")


def test_an_answer_past_16_mb_is_unreadable():
    c, _ = _answers(b" " * (OUT_CAP + 1))
    assert c.extract(b"%PDF-") == Outcome(None, "unreadable")


def test_a_word_past_the_page_edge_comes_back_on_the_page():
    off = _page(lines=[{"y": 800.0, "cells": [{"x0": 600.0, "x1": 640.0, "text": "Total"}]}])
    c, _ = _answers(json.dumps({"pages": [off]}).encode())
    assert c.extract(b"%PDF-").pages[0]["lines"] == [{"y": 792.0, "cells": [{"x0": 600.0, "x1": 612.0, "text": "Total"}]}]


def test_a_verdict_is_the_files_own_line():
    for key in ("password", "too_many_pages", "not_pdf", "too_slow", "unreadable", "too_big"):
        c, _ = _answers(json.dumps({"error": key}).encode())
        assert c.extract(b"%PDF-") == Outcome(None, key)


def test_a_page_picture_comes_back_through_the_childs_checks():
    png = _png()
    c, seen = _answers(_pic(png, n=3))
    assert c.render(b"%PDF-", 3) == Rendered(png, 100, 200, None)
    assert seen[0][:3] == ("/v1/statements/render", b"page=3", "application/pdf")


@pytest.mark.parametrize("body", [
    lambda: _pic(n=2),                                            # another page than the one asked for
    lambda: _pic(_png(mode="RGB")),                               # not 8-bit greyscale
    lambda: _pic(width_px=101),                                   # a size the header doesn't say
    lambda: _pic(_png(2201, 10), width_px=2201, height_px=10),    # past 2,200 px
    lambda: json.dumps({"png": "not base64!", "width_px": 100, "height_px": 200, "n": 1}).encode(),
    lambda: _pic(more=1),
    lambda: b"[]",
])
def test_every_check_on_a_picture_applies_to_gateway_answers(body):
    c, _ = _answers(body())
    assert c.render(b"%PDF-", 1) == Rendered(None, 0, 0, "unreadable")


def test_away_and_errors_are_never_a_verdict():
    for status, want in ((503, AWAY), (500, None), (401, None), (413, None)):
        c, _ = _answers(b"{}", status)
        assert c.extract(b"%PDF-") == want and c.render(b"%PDF-", 1) == want and c.last_error

    def slow(request):
        raise httpx2.ReadTimeout("slow")

    def gone(request):
        raise httpx2.ConnectError("refused")
    for handler, words in ((slow, "The gateway took too long to answer"), (gone, "could not reach the gateway")):
        c = _client(handler)
        assert c.extract(b"%PDF-") == AWAY and c.last_error == words
    assert NullStatementClient().extract(b"%PDF-") == AWAY and NullStatementClient().render(b"%PDF-", 1) == AWAY


def test_the_client_logs_nothing_of_the_pdf(caplog):
    caplog.set_level(logging.DEBUG)
    c, _ = _answers(json.dumps({"pages": [PAGE]}).encode())
    c.extract(b"%PDF-1.4 ZORBLAXQUILL")
    assert "ZORBLAXQUILL" not in caplog.text and "Opening balance" not in caplog.text
