"""docs/screenshots: the deliberate list in the public-docs plan (D9), at most 20 (the export's cap). Each is a shot from
the e2e servers' made-up vaults, a plain PNG of its size with no text chunks, small, and shown by a public doc."""
import struct

import pytest

from tests.public_docs import ROOT, public_docs

SHOT_DIR = ROOT / "docs" / "screenshots"
PHONE, DESKTOP = (780, 1688), (1280, 800)
SHOTS = {"signin": PHONE, "first-run": PHONE, "home": PHONE, "review": PHONE, "ask": PHONE, "sent": PHONE,
         "ready": DESKTOP, "plan": DESKTOP, "access": DESKTOP, "email": DESKTOP, "backups": DESKTOP,
         "bank-link": DESKTOP, "gateway-pair": DESKTOP}
LATER: set[str] = set()         # a shot whose page is written later; none now
DISPLAY = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"pHYs"}
MAX_BYTES = 500_000
SIGNATURE = b"\x89PNG\r\n\x1a\n"


def chunks(data: bytes) -> list[bytes]:
    """The chunk types of a PNG, in order; ValueError if it isn't one."""
    if not data.startswith(SIGNATURE):
        raise ValueError("not a PNG")
    found, at = [], len(SIGNATURE)
    while at < len(data):
        if at + 8 > len(data):
            raise ValueError("a cut chunk header")
        (length,) = struct.unpack(">I", data[at:at + 4])
        found.append(data[at + 4:at + 8])
        at += 12 + length
    if at != len(data) or not found or found[0] != b"IHDR" or found[-1] != b"IEND":
        raise ValueError("chunks do not run from IHDR to IEND")
    return found


def test_chunks_reads_types_in_order_and_refuses_what_is_not_a_png():
    def chunk(kind: bytes, body: bytes = b"") -> bytes:
        return struct.pack(">I", len(body)) + kind + body + b"\0\0\0\0"
    png = SIGNATURE + chunk(b"IHDR", b"x" * 13) + chunk(b"tEXt", b"k\0v") + chunk(b"IEND")
    assert chunks(png) == [b"IHDR", b"tEXt", b"IEND"]
    for bad in (b"GIF89a", SIGNATURE + b"\0\0", png[:-3]):
        with pytest.raises(ValueError):
            chunks(bad)


def test_the_screenshots_are_the_list():
    assert len(SHOTS) <= 20
    assert sorted(p.stem for p in SHOT_DIR.glob("*")) == sorted(set(SHOTS) - LATER)


@pytest.mark.parametrize("name", sorted(set(SHOTS) - LATER))
def test_each_is_a_plain_small_png_of_its_size(name):
    data = (SHOT_DIR / f"{name}.png").read_bytes()
    assert set(chunks(data)) <= DISPLAY and len(data) <= MAX_BYTES
    assert struct.unpack(">II", data[16:24]) == SHOTS[name]


def test_each_is_shown_by_a_public_doc():
    shown = "".join(p.read_text() for p in public_docs())
    assert [n for n in set(SHOTS) - LATER if f"screenshots/{n}.png" not in shown] == []
