"""Rendering a page for the vision model (spec P8, P10, P26): in the sandbox, 200 DPI greyscale with the long side at
most 2,200 px and the PNG at most 3 MB (150 DPI when bigger, refused when still bigger); the scanned and mixed
fixtures are pictures with no text layer."""
import base64
import io
import json
import signal
import struct
import zlib

import pytest
from PIL import Image

from steward_pdf import sandbox as S
from steward_boundary.statements_wire import png_header
from steward_gateway.evals.statement_set import BANK_CARD
from tests.statement_files import pdf
from tests.test_statement_sandbox import FakeProc, NowTimer, _popen


def _img(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png))


def test_a_page_renders_greyscale_within_the_bounds():
    out = S.render_page(pdf("chase_checking")[0], 1)
    png = base64.b64decode(out["png"])
    assert png.startswith(S.PNG_SIGNATURE) and len(png) <= S.MAX_PNG
    img = _img(png)
    assert img.mode == "L" and max(img.size) <= S.MAX_PX and img.size == (out["width_px"], out["height_px"])


def test_the_child_renders_what_the_parent_would():
    data = pdf("boa_checking")[0]
    r = S.run_render(data, 1)
    assert r.error is None and r.png == base64.b64decode(S.render_page(data, 1)["png"])


@pytest.mark.parametrize("n", [0, 2, 61])
def test_a_page_the_file_doesnt_have_is_unreadable(n):
    with pytest.raises(S.Refused) as e:
        S.render_page(pdf("boa_checking")[0], n)
    assert e.value.key == "unreadable"


def test_a_password_pdf_wont_render():
    assert S.run_render(pdf("boa_checking", "password")[0], 1).error == "password"


def test_a_huge_page_is_refused_before_rendering():
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(6000, 6000), invariant=1)
    c.drawString(40, 40, "a very large page")
    c.showPage()
    c.save()
    with pytest.raises(S.Refused):
        S.render_page(buf.getvalue(), 1)


def test_the_scan_and_mixed_fixtures():
    scan = S.read_pdf(pdf("boa_checking", "scan")[0])["pages"]
    assert scan and all(p["scan"] for p in scan) and all(p["lines"] == [] for p in scan)
    mixed = S.read_pdf(pdf("capone_card", "mixed")[0])["pages"]
    assert mixed[0]["scan"] is True and all(not p["scan"] for p in mixed[1:]) and len(mixed) >= 2


def test_a_scan_is_byte_stable():
    from steward_gateway.evals.statement_set import build
    assert build("boa_checking", variant="scan")[0] == build("boa_checking", variant="scan")[0]


# ---- the parent re-checks what the child says (P8, P26) and never raises

def _png(size=(10, 10)) -> bytes:
    buf = io.BytesIO()
    Image.new("L", size, 255).save(buf, "PNG")
    return buf.getvalue()


def _body(png: bytes, w=10, h=10, n=1, **extra) -> bytes:
    return json.dumps({"png": base64.b64encode(png).decode(), "width_px": w, "height_px": h, "n": n, **extra}).encode()


def _render(out: bytes, code: int = 0, **kw):
    return S.run_render(b"%PDF-", 1, popen=_popen(FakeProc(out, code)), **kw)


def test_a_good_answer_is_accepted():
    r = _render(_body(_png()))
    assert (r.error, r.width, r.height) == (None, 10, 10) and r.png == _png()


def test_a_render_that_overruns_or_hits_the_cpu_limit_is_too_slow():
    assert S.run_render(b"%PDF-", 1, popen=_popen(FakeProc(_body(_png()))), timer=NowTimer).error == "too_slow"
    assert _render(b"", -signal.SIGXCPU).error == "too_slow"


def test_the_childs_answer_is_checked_again_here():
    assert _render(b"{not json").error == "unreadable"
    assert _render(b"", -signal.SIGSEGV).error == "unreadable"
    assert _render(_body(_png()), 1).error == "unreadable"
    assert _render(b"x" * 101, out_cap=100).error == "unreadable"
    assert _render(b'{"error": "not a key"}').error == "unreadable"
    assert _render(b'{"error": "password"}').error == "password"
    assert _render(_body(b"not a png at all")).error == "unreadable"
    assert _render(_body(S.PNG_SIGNATURE + b"x" * S.MAX_PNG)).error == "unreadable"
    assert _render(_body(_png(), w=S.MAX_PX + 1)).error == "unreadable"
    assert _render(_body(_png(), h=0)).error == "unreadable"
    assert _render(b'{"png": "!!!", "width_px": 1, "height_px": 1, "n": 1}').error == "unreadable"
    assert _render(b"[1]").error == "unreadable"


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _ihdr_length(png: bytes, n: int) -> bytes:
    return png[:8] + struct.pack(">I", n) + png[12:]


def _mode(mode: str) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (10, 10)).save(buf, "PNG")
    return buf.getvalue()


@pytest.mark.parametrize("out", [
    _body(b"GIF89a" + b"\x00" * 40),                                            # not a PNG
    _body(_ihdr_length(_png(), 12)), _body(_ihdr_length(_png(), 14)),           # IHDR must be 13 bytes long
    _body(S.PNG_SIGNATURE + _chunk(b"tEXt", b"a\x00b") + _png()[8:]),          # IHDR must come first
    _body(_png()[:30] + bytes([_png()[30] ^ 1]) + _png()[31:]),                 # IHDR's CRC is wrong
    _body(_png((20, 20))),                                                      # really bigger than it says
    _body(_png((10, 20))),
    _body(_png((S.MAX_PX + 1, 10)), w=S.MAX_PX + 1),                            # really over 2,200 px, and says so
    _body(_png((10, S.MAX_PX + 1)), h=S.MAX_PX + 1),
    _body(_png() + b"\x00" * S.MAX_PNG),                                        # over 3 MB behind a good header
    _body(_mode("RGB")), _body(_mode("1")), _body(_mode("I;16")),               # not 8-bit greyscale
    _body(_png(), n=2), _body(_png(), n=True), _body(_png(), n="1"),            # not the page asked for
    _body(_png(), w=10.0), _body(_png(), h=True),
    _body(_png(), extra=1),
    json.dumps({"png": base64.b64encode(_png()).decode(), "width_px": 10, "height_px": 10}).encode(),
], ids=["gif", "ihdr-12", "ihdr-14", "ihdr-second", "ihdr-crc", "bigger", "taller", "wide", "tall", "over-3mb", "rgb",
        "1-bit", "16-bit", "page-2", "page-bool", "page-str", "w-float", "h-bool", "extra-key", "no-page"])
def test_a_render_off_in_any_way_is_unreadable(out):
    assert _render(out) == S.Rendered(None, 0, 0, "unreadable")


def test_only_the_checked_values_go_on():
    r = _render(_body(_png((7, 9)), w=7, h=9))
    assert r == S.Rendered(_png((7, 9)), 7, 9, None)


@pytest.mark.parametrize("sid", BANK_CARD)
def test_the_real_child_renders_every_page_of_the_scanned_set(sid):
    """pypdfium2's greyscale render, saved by PIL, is the 8-bit greyscale PNG the parent insists on."""
    data, truth = pdf(sid, "scan")
    for n in range(1, truth.pages + 1):
        r = S.run_render(data, n)
        head = png_header(r.png)
        assert r.error is None and (head.width, head.height) == (r.width, r.height) and max(r.width, r.height) <= S.MAX_PX
        assert (head.depth, head.colour, head.compression, head.filter, head.interlace) == (8, 0, 0, 0, 0)


def test_a_child_that_cannot_start_is_a_refusal_not_a_traceback():
    def broken(*a, **k):
        raise OSError("no process")
    assert S.run_render(b"%PDF-", 1, popen=broken).error == "unreadable"


def test_an_unconfined_child_never_renders(monkeypatch):
    from tests.test_pdf_wall import _main                       # the one in-process runner: every step stubbed

    def never(*_a):
        raise AssertionError("rendered without the filter")
    monkeypatch.setattr(S, "render_page", never)
    stdin = io.TextIOWrapper(io.BytesIO(pdf("chase_checking")[0]))
    assert _main(monkeypatch, ["--render", "1"], confined=False, stdin=stdin) == {"error": "unreadable"}
