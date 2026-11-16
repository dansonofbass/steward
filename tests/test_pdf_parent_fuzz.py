"""Spec section 6: the PDF parent trusts nothing its child prints. parse_extract and parse_render each get 2,000
mutated outputs from a fixed seed. They must answer every one without raising, and accept only what the child's own
shape and caps allow. The work is counted, never timed. The bases are built by hand, as the parent never imports
pdfplumber or pypdfium2.

parse_render judges a PNG by its header alone (sandbox.py's docstring). A truncated body, a lying IDAT or a zlib bomb
behind a sound IHDR may pass; these tests hold it to that stated contract and no more."""
from __future__ import annotations

import base64
import copy
import json
import math
import random
import struct
import zlib
from collections import Counter
from functools import cache

from steward_pdf.lines import CELL_CHARS, CELLS_PER_LINE, LINES_PER_PAGE
from steward_pdf.sandbox import (ERRORS, MAX_AT, MAX_PAGES, MAX_PNG, MAX_PNG_B64, MAX_PX, MAX_SIDE, MAX_TEXT_PAGE,
                                 PAGE_KEYS, Outcome, Rendered, parse_extract, parse_render)

SEED = 2026
CASES = 2000
DEPTH = 10_000
SIGNATURE = b"\x89PNG\r\n\x1a\n"
HEAD = 33                                               # signature, IHDR length and type, 13 bytes, CRC


class Raw(str):
    """JSON text written as is: a number Python can't print (over 4,300 digits), or a literal json.dumps won't make."""


def encode(v, dup: int | None = None) -> str:
    """JSON as the child writes it, except NaN and Infinity pass through, and the dict whose id is dup repeats its
    first key."""
    if isinstance(v, Raw):
        return str(v)
    if isinstance(v, dict):
        items = [f"{json.dumps(k)}: {encode(x, dup)}" for k, x in v.items()]
        if id(v) == dup and items:
            items.insert(0, items[0])
        return "{" + ", ".join(items) + "}"
    if isinstance(v, list):
        return "[" + ", ".join(encode(x, dup) for x in v) + "]"
    return json.dumps(v)


def finite(v) -> bool:
    return type(v) in (int, float) and math.isfinite(v)


NUMBERS = (0, -0.0, 1, -1, 0.5, MAX_AT, -MAX_AT, MAX_AT + 0.001, -MAX_AT - 1, MAX_SIDE, MAX_SIDE + 0.1, 1e308, -1e308,
           10 ** 18, -(10 ** 18), 2 ** 64, math.nan, math.inf, -math.inf, Raw("1e400"), Raw("-1e400"), Raw("1" * 5000),
           Raw("-0"), True, False)
TEXTS = ("", "Coffee", "w" * CELL_CHARS, "w" * (CELL_CHARS + 1), "tab\there", "line\nbreak", "\x00", "\ud800",
         "​", " ", "café", "\U0001f4b0")
ODD = ("", "1", "x", [], [1], {}, {"x0": 1}, True, False, None, 0, 1.5, [[]], {"y": 1, "cells": []})
INVALID_UTF8 = (b"\xff", b"\x80", b"\xc3\x28", b"\xed\xa0\x80", b"\xf8\x88\x80\x80\x80", b"\xe2\x82")
DEEP = (b"[" * DEPTH + b"]" * DEPTH,
        b'{"pages": ' + b"[" * DEPTH + b"]" * DEPTH + b"}",
        b'{"a": ' * DEPTH + b"1" + b"}" * DEPTH,
        b'{"pages": [{"n": 1, "width": 612, "height": 792, "scan": false, "lines": '
        + b"[" * DEPTH + b"]" * DEPTH + b"}]}")


def mutate_bytes(b: bytes, rng: random.Random) -> bytes:
    """Truncate, flip, cut or insert, 1 to 3 times."""
    b = bytearray(b)
    for _ in range(rng.randint(1, 3)):
        op = rng.choice(("truncate", "flip", "invalid_utf8", "cut", "insert"))
        at = rng.randrange(len(b) + 1)
        if op == "truncate":
            del b[at:]
        elif op == "flip" and b:
            b[min(at, len(b) - 1)] ^= rng.randrange(1, 256)
        elif op == "invalid_utf8":
            b[at:at] = rng.choice(INVALID_UTF8)
        elif op == "cut":
            del b[at:at + rng.randint(1, 16)]
        else:
            b[at:at] = bytes(rng.randrange(256) for _ in range(rng.randint(1, 4)))
    return bytes(b)


def slots(v, out: list) -> list:
    """Every (container, key) in a JSON tree."""
    if isinstance(v, dict):
        for k, x in v.items():
            out.append((v, k))
            slots(x, out)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            out.append((v, i))
            slots(x, out)
    return out


def mutate_tree(doc, rng: random.Random) -> int | None:
    """One change at one place: delete, duplicate, swap the type, set a hostile number or text, or add. Returns the id
    of a dict whose first key the encoding should repeat."""
    places = slots(doc, [])
    if not places:                                      # an earlier change emptied it
        return None
    c, k = rng.choice(places)
    op = rng.choice(("delete", "duplicate", "swap", "number", "text", "add"))
    if op == "delete":
        del c[k]
    elif op == "duplicate":
        if isinstance(c, dict):
            return id(c)
        c.insert(k, copy.deepcopy(c[k]))
    elif op == "swap":
        c[k] = copy.deepcopy(rng.choice(ODD))
    elif op == "number":
        c[k] = rng.choice(NUMBERS)
    elif op == "text":
        c[k] = rng.choice(TEXTS)
    elif isinstance(c, dict):
        c[rng.choice(("extra", "error", "N", "pages"))] = copy.deepcopy(rng.choice(ODD))
    else:
        c.append(copy.deepcopy(c[k]))
    return None


# ---------------------------------------------------------------- extract

def line(y, texts, x: float = 20.0) -> dict:
    cells = []
    for t in texts:
        cells.append({"x0": x, "x1": x + 6.0 * len(t), "text": t})
        x += 6.0 * len(t) + 12
    return {"y": y, "cells": cells}


def page(n: int, lines=()) -> dict:
    return {"n": n, "width": 612.0, "height": 792.0, "scan": False, "lines": list(lines)}


def base_pages() -> list[dict]:
    """read_pdf's shape: floats and ints, a word just past the right edge (moved back onto the page), a scanned page
    with no lines."""
    return [{"n": 1, "width": 612.0, "height": 792.0, "scan": False,
             "lines": [line(72.0, ["Statement period", "Oct 1 - Oct 31"]),
                       line(140.5, ["10/03", "Coffee", "-4.50"]),
                       line(152, ["10/04", "Rent", "-1,200.00"], x=520),
                       line(800.5, ["Page 1 of 2"])]},
            {"n": 2, "width": 612, "height": 792, "scan": True, "lines": []}]


def size_case(rng: random.Random) -> tuple[dict, bool]:
    """A document at one of the caps, or one past it."""
    over = rng.random() < 0.5
    extra = int(over)
    which = rng.choice(("pages", "lines", "cells", "text", "chars"))
    if which == "pages":
        pages = [page(i, [line(50.0, ["x"])]) for i in range(1, MAX_PAGES + 1 + extra)]
    elif which == "lines":
        pages = [page(1, [line(10.0 + i, ["x"]) for i in range(LINES_PER_PAGE + extra)])]
    elif which == "cells":
        pages = [page(1, [{"y": 50.0, "cells": [{"x0": float(i), "x1": i + 0.5, "text": "x"}
                                                for i in range(CELLS_PER_LINE + extra)]}])]
    elif which == "text":
        pages = [page(1, [{"y": 50.0, "cells": [{"x0": 1.0, "x1": 2.0, "text": "w" * (CELL_CHARS + extra)}]}])]
    else:
        lines = [{"y": float(i), "cells": [{"x0": 1.0, "x1": 2.0, "text": "w" * CELL_CHARS}]}
                 for i in range(MAX_TEXT_PAGE // CELL_CHARS)]
        if over:
            lines[0]["cells"].append({"x0": 3.0, "x1": 4.0, "text": "w"})
        pages = [page(1, lines)]
    return {"pages": pages}, over


def refusal_case(rng: random.Random) -> tuple[bytes, str]:
    """A refusal on its own is believed; mixed with pages, or off in any way, it's unreadable."""
    e = rng.choice(ERRORS)
    body, want = rng.choice((
        ({"error": e}, e),
        ({"error": e, "pages": base_pages()}, "unreadable"),
        ({"pages": base_pages(), "error": e}, "unreadable"),
        (Raw(f'{{"error": "{e}", "error": "{e}"}}'), "unreadable"),
        ({"error": "nope"}, "unreadable"),
        ({"error": e.upper()}, "unreadable"),
        ({"error": [e]}, "unreadable"),
        ({"error": None}, "unreadable"),
        ({"error": ""}, "unreadable"),
        ({}, "unreadable"),
        ([], "unreadable"),
        (e, "unreadable"),
        (None, "unreadable"),
        (True, "unreadable"),
    ))
    return encode(body).encode(), want


def extract_case(rng: random.Random) -> tuple[str, bytes, str | None]:
    """(kind, the child's stdout, the outcome it must get or None when only the contract applies)."""
    kind = rng.choices(("tree", "bytes", "size", "deep", "refusal", "bom"), weights=(50, 25, 10, 4, 8, 3))[0]
    if kind == "tree":
        doc, dup = {"pages": base_pages()}, None
        for _ in range(rng.randint(1, 3)):
            dup = mutate_tree(doc, rng) or dup
        return kind, encode(doc, dup).encode(), None
    if kind == "bytes":
        return kind, mutate_bytes(encode({"pages": base_pages()}).encode(), rng), None
    if kind == "size":
        doc, over = size_case(rng)
        return kind, encode(doc).encode(), "unreadable" if over else "accepted"
    if kind == "deep":
        return kind, rng.choice(DEEP), "unreadable"
    if kind == "refusal":
        out, want = refusal_case(rng)
        return kind, out, want
    return kind, b"\xef\xbb\xbf" + encode({"pages": base_pages()}).encode(), "unreadable"


def check_extract(got, out: bytes) -> str:
    """The contract: an Outcome; a refusal from the list, or pages under every cap with every value finite and every
    position (before and after it's moved onto its page) within MAX_AT. Returns "accepted" or the refusal."""
    assert isinstance(got, Outcome)
    if got.error is not None:
        assert got.pages is None and got.error in ERRORS
        return got.error
    raw = json.loads(out.decode("utf-8"))["pages"]     # the strict read already passed, so this reads the same
    pages = got.pages
    assert isinstance(pages, list) and 1 <= len(pages) <= MAX_PAGES and len(raw) == len(pages)
    for n, (p, rp) in enumerate(zip(pages, raw), 1):
        assert p.keys() == PAGE_KEYS and type(p["n"]) is int and p["n"] == n and type(p["scan"]) is bool
        w, h = p["width"], p["height"]
        assert finite(w) and finite(h) and 0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE
        assert isinstance(p["lines"], list) and len(p["lines"]) <= LINES_PER_PAGE
        assert len(p["lines"]) == len(rp["lines"])
        chars = 0
        for ln, rln in zip(p["lines"], rp["lines"]):
            assert ln.keys() == {"y", "cells"}
            assert finite(rln["y"]) and abs(rln["y"]) <= MAX_AT and finite(ln["y"]) and 0 <= ln["y"] <= h
            assert isinstance(ln["cells"], list) and 1 <= len(ln["cells"]) <= CELLS_PER_LINE
            for c, rc in zip(ln["cells"], rln["cells"]):
                assert c.keys() == {"x0", "x1", "text"}
                for at in ("x0", "x1"):
                    assert finite(rc[at]) and abs(rc[at]) <= MAX_AT
                    assert finite(c[at]) and 0 <= c[at] <= w and c[at] == min(max(rc[at], 0.0), w)
                t = c["text"]
                assert isinstance(t, str) and 0 < len(t) <= CELL_CHARS and t.isprintable()
                chars += len(t)
        assert chars <= MAX_TEXT_PAGE
    return "accepted"


def test_the_unmutated_bases_are_accepted():
    got = parse_extract(encode({"pages": base_pages()}).encode())
    assert got.error is None and [p["n"] for p in got.pages] == [1, 2]
    assert got.pages[0]["lines"][2]["cells"][2]["x1"] == 612.0     # it ends at 652: moved back onto the page
    assert got.pages[0]["lines"][3]["y"] == 792.0                  # 800.5, likewise
    for w, h in SIZES:
        for n in (1, MAX_PAGES):
            r = parse_render(render_out(base_png(w, h), w, h, n), n)
            assert r == Rendered(base_png(w, h), w, h, None)


def test_parse_extract_never_raises_and_keeps_its_bounds():
    rng = random.Random(SEED)
    seen, kinds = Counter(), Counter()
    for i in range(CASES):
        kind, out, want = extract_case(rng)
        got = check_extract(parse_extract(out), out)
        if want is not None:
            assert got == want, (i, kind, out[:200])
        seen["accepted" if got == "accepted" else "refused"] += 1
        kinds[kind] += 1
    assert seen["accepted"] >= 100 and seen["refused"] >= 100, seen
    assert set(kinds) == {"tree", "bytes", "size", "deep", "refusal", "bom"}, kinds


# ---------------------------------------------------------------- render

SIZES = ((40, 30), (1, 1), (MAX_PX, 1), (1, MAX_PX))
PAGES = (1, 2, 7, MAX_PAGES)


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def ihdr(w: int, h: int, depth: int = 8, colour: int = 0, compression: int = 0, filter_: int = 0,
         interlace: int = 0) -> bytes:
    return chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, colour, compression, filter_, interlace))


@cache
def base_png(w: int, h: int) -> bytes:
    """What render_page saves: 8-bit greyscale, not interlaced, one filter byte a row."""
    rows = b"".join(b"\x00" + bytes((x * 7 + y) % 256 for x in range(w)) for y in range(h))
    return SIGNATURE + ihdr(w, h) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")


@cache
def bomb_idat() -> bytes:
    """An IDAT that inflates to 8 MB, far past any IHDR here and past MAX_PNG."""
    return chunk(b"IDAT", zlib.compress(bytes(8 * 1024 * 1024), 9))


@cache
def padded_png(size: int) -> bytes:
    """The 40 x 30 base grown to exactly size bytes by a tEXt chunk before IEND."""
    head = base_png(40, 30)[:-12]
    data = b"Comment\x00" + b"w" * (size - len(head) - 12 - 12 - 8)
    return head + chunk(b"tEXt", data) + chunk(b"IEND", b"")


def body(png: bytes, w, h, n) -> dict:
    return {"png": base64.b64encode(png).decode("ascii"), "width_px": w, "height_px": h, "n": n}


def render_out(png: bytes, w, h, n) -> bytes:
    return encode(body(png, w, h, n)).encode()


@cache
def big_out(size: int, n: int) -> bytes:
    return render_out(padded_png(size), 40, 30, n)


def lie(png: bytes, w: int, h: int, crc: bool) -> bytes:
    """The PNG with its IHDR's size changed, the CRC fixed or left stale."""
    if crc:
        return png[:8] + ihdr(w, h) + png[HEAD:]
    return png[:16] + struct.pack(">II", w, h) + png[24:]


def png_case(rng: random.Random, png: bytes, w: int, h: int) -> tuple[str, bytes, int, int, bool | None]:
    """(kind, the PNG, the size to report, whether the contract must refuse it: True, or None when either answer
    keeps the contract)."""
    kind = rng.choice(("truncate", "lie", "bomb", "chunk", "format", "foreign", "cap"))
    if kind == "truncate":
        k = rng.randrange(len(png))
        return kind, png[:k], w, h, True if k < HEAD else None
    if kind == "lie":
        w2, h2 = rng.choice((1, w + 1, max(w - 1, 0), MAX_PX, MAX_PX + 1, 2 ** 31, 2 ** 32 - 1, 0)), \
            rng.choice((1, h + 1, max(h - 1, 0), MAX_PX, MAX_PX + 1, 0))
        crc, told = rng.random() < 0.7, rng.choice(((w2, h2), (w, h)))
        sound = crc or (w2, h2) == (w, h)                                   # an unchanged IHDR keeps its own CRC
        fits = 1 <= w2 <= MAX_PX and 1 <= h2 <= MAX_PX and told == (w2, h2)
        return kind, lie(png, w2, h2, crc), *told, None if sound and fits else True
    if kind == "bomb":
        return kind, png[:HEAD] + bomb_idat() + chunk(b"IEND", b""), w, h, None
    if kind == "chunk":
        extra = rng.choice((chunk(b"tEXt", b"Comment\x00hi"), chunk(b"abCd", b"\x00" * 9), chunk(b"IDAT", b"junk"),
                            ihdr(w, h, colour=2)))
        if rng.random() < 0.5:
            return kind, png[:8] + extra + png[8:], w, h, True              # IHDR must come first
        return kind, png[:HEAD] + extra + png[HEAD:], w, h, None
    if kind == "format":
        field = rng.choice(({"depth": rng.choice((1, 2, 4, 16))}, {"colour": rng.choice((2, 3, 4, 6))},
                            {"compression": 1}, {"filter_": 1}, {"interlace": 1}))
        return kind, png[:8] + ihdr(w, h, **field) + png[HEAD:], w, h, True
    if kind == "foreign":
        return kind, rng.choice((b"", SIGNATURE, SIGNATURE + b"\x00" * 30, b"GIF89a" + b"\x00" * 40,
                                 b"\xff\xd8\xff\xe0" + b"\x00" * 40, png[8:], bytes(rng.randrange(256) for _ in
                                                                                    range(64)))), w, h, True
    return kind, png, w, h, None                                           # "cap": render_case swaps in the big ones


def render_case(rng: random.Random) -> tuple[str, bytes, int, str | None]:
    """(kind, the child's stdout, the page asked for, the outcome it must get or None when only the contract
    applies)."""
    n = rng.choice(PAGES)
    w, h = rng.choice(SIZES)
    png = base_png(w, h)
    kind = rng.choices(("png", "page", "base64", "size", "keys", "refusal", "bytes", "deep"),
                       weights=(40, 10, 10, 10, 8, 7, 12, 3))[0]
    if kind == "png":
        sub, bad, tw, th, refuse = png_case(rng, png, w, h)
        if sub == "cap":
            over = rng.random() < 0.5
            return "png-cap", big_out(MAX_PNG + int(over), n), n, "unreadable" if over else "accepted"
        return f"png-{sub}", render_out(bad, tw, th, n), n, "unreadable" if refuse else None
    if kind == "page":
        wrong = rng.choice((n - 1, n + 1, 0, -n, str(n), float(n), None, [n], True if n == 1 else n * 2))
        return kind, render_out(png, w, h, wrong), n, "unreadable"
    if kind == "base64":
        b = body(png, w, h, n)
        s = b["png"]
        at = rng.randrange(len(s) + 1)
        b["png"] = rng.choice((s[:at] + "\n" + s[at:], s[:at] + " " + s[at:], s[:at] + "*" + s[at:],
                               s[:at] + "é" + s[at:], s + "A", None, 0, [s], {"b64": s}))
        return kind, encode(b).encode(), n, "unreadable"
    if kind == "size":
        tw, th = rng.choice(((float(w), h), (w, float(h)), (str(w), h), (w + 1, h), (w, h - 1), (None, h),
                             (True, h) if w == 1 else (h + w, h), (h, w) if w != h else (w, 2 * h)))
        return kind, render_out(png, tw, th, n), n, "unreadable"
    if kind == "keys":
        b = body(png, w, h, n)
        op = rng.choice(("delete", "add", "repeat"))
        if op == "delete":
            del b[rng.choice(sorted(b))]
        elif op == "add":
            b[rng.choice(("extra", "error", "pages", "page"))] = 1
        return kind, encode(b, id(b) if op == "repeat" else None).encode(), n, "unreadable"
    if kind == "refusal":
        e = rng.choice(ERRORS)
        if rng.random() < 0.5:
            return kind, encode({"error": e}).encode(), n, e
        return kind, encode({**body(png, w, h, n), "error": e}).encode(), n, "unreadable"
    if kind == "bytes":
        return kind, mutate_bytes(render_out(png, w, h, n), rng), n, None
    return kind, rng.choice(DEEP), n, "unreadable"


def check_render(got, out: bytes, n: int) -> str:
    """The contract: a Rendered; a refusal from the list with no picture, or the page asked for and a PNG at most
    MAX_PNG whose own IHDR (CRC right) says 8-bit greyscale, not interlaced, each side at most MAX_PX, and the size the
    child reported as ints. Returns "accepted" or the refusal."""
    assert isinstance(got, Rendered)
    if got.error is not None:
        assert got.png is None and got.width == got.height == 0 and got.error in ERRORS
        return got.error
    b = json.loads(out.decode("utf-8"))                # the strict read already passed, so this reads the same
    assert type(b["n"]) is int and b["n"] == n
    png = got.png
    assert isinstance(png, bytes) and len(png) <= MAX_PNG and len(b["png"]) <= MAX_PNG_B64
    assert png == base64.b64decode(b["png"], validate=True)
    assert png[:8] == SIGNATURE and png[8:16] == b"\x00\x00\x00\x0dIHDR"
    assert zlib.crc32(png[12:29]) == int.from_bytes(png[29:33], "big")
    w, h, *fmt = struct.unpack(">IIBBBBB", png[16:29])
    assert fmt == [8, 0, 0, 0, 0] and 1 <= w <= MAX_PX and 1 <= h <= MAX_PX
    assert (got.width, got.height) == (w, h) and type(got.width) is int and type(got.height) is int
    assert type(b["width_px"]) is int and type(b["height_px"]) is int and (b["width_px"], b["height_px"]) == (w, h)
    return "accepted"


def test_parse_render_never_raises_and_accepts_only_a_png_of_the_asked_page():
    rng = random.Random(SEED)
    seen, kinds = Counter(), Counter()
    for i in range(CASES):
        kind, out, n, want = render_case(rng)
        got = check_render(parse_render(out, n), out, n)
        if want is not None:
            assert got == want, (i, kind, n, out[:200])
        seen["accepted" if got == "accepted" else "refused"] += 1
        kinds[kind] += 1
    assert seen["accepted"] >= 100 and seen["refused"] >= 100, seen
    assert {k for k in kinds if k.startswith("png-")} == {f"png-{k}" for k in ("truncate", "lie", "bomb", "chunk",
                                                                               "format", "foreign", "cap")}, kinds
    assert {"page", "base64", "size", "keys", "refusal", "bytes", "deep"} <= set(kinds), kinds


def test_none_and_empty_outputs_are_refusals():
    assert parse_extract(None) == Outcome(None, "unreadable")
    assert parse_extract(b"") == Outcome(None, "unreadable")
    assert parse_render(None, 1) == Rendered(None, 0, 0, "unreadable")
    assert parse_render(b"", 1) == Rendered(None, 0, 0, "unreadable")
