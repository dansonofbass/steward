"""The sandbox (spec P8, P9, P11; plan Engineering choices 3, 4, 17). Every PDF is opened only here, in a child
process: `python -I -B -m steward_pdf.sandbox`, the PDF on stdin and one JSON object on stdout. Steward runs it when
its kernel can confine it; otherwise the gateway runs this same module and Steward reads its answer with
parse_extract and parse_render, the checks it runs on its own child (remote-reading P56, P62). Before
reading, the child sets RLIMIT_AS 1 GiB, RLIMIT_CPU 60 s, RLIMIT_FSIZE 0 (SIGXFSZ ignored, so a write fails instead
of killing it), RLIMIT_NOFILE 32 and RLIMIT_CORE 0, asks to die with its parent (and dies at once if the parent is
already gone), sets its own SIGKILL deadline 100 s out, imports the PDF libraries (preload), then puts up landlock's
wall (no file but the fonts, pdfminer's character maps and its own folder can be opened or listed, though a stat still
shows whether a path exists and its metadata, never what it holds) and last installs confine's seccomp filter (no
network, exec, new process, ptrace, signal to another process, link read, or change to a file, its metadata or the
child's own confinement; confine's docstring has the exact rules). It reads a
PDF only with both up, on every machine: seccomp alone leaves every file Steward's user can read,
the book key included, open to a child a crafted PDF took over. It runs with an empty environment, in an
empty 0700 folder that the parent removes after, under a 90-second wall timeout, with stdout capped at 16 MB; one
child at a time (the reader runs one job at a time). pypdfium2 counts pages and spots a password; pdfplumber reads the words. Neither runs
JavaScript or fetches anything; forms, links, attachments and embedded files are never touched. The parent never
imports either library. A crafted PDF could own the child, so the parent trusts nothing it prints: strict JSON of
exactly the shape the child writes, and a PNG judged by its own header. Any non-zero exit, overrun or answer off in
any way fails only that file's line, as a copy key."""
from __future__ import annotations

import errno
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass

from steward_pdf import confine, landlock
from steward_pdf.lines import CELL_CHARS, CELLS_PER_LINE, LINES_PER_PAGE
from steward_boundary.statements_wire import png_header

MAX_BYTES = 15 * 1024 * 1024
MAX_PAGES = 60
MAX_OBJECTS = 200_000
MAX_CHARS_PAGE = 20_000
MAX_SIDE = 5000.0
OUT_CAP = 16 * 1024 * 1024
LINES_CAP = 4 * 1024 * 1024
WALL_S = 90
DEADLINE_S = WALL_S + 10                                # the child's own clock: past the parent's, which acts first
LIMITS = {"RLIMIT_AS": 1 << 30, "RLIMIT_CPU": 60, "RLIMIT_FSIZE": 0, "RLIMIT_NOFILE": 32, "RLIMIT_CORE": 0}
NICE = 10                                               # P59: a 60-second parse never starves the machine it's on
ERRORS = ("password", "too_many_pages", "not_pdf", "too_big", "too_slow", "unreadable")
MODULE = "steward_pdf.sandbox"


class Refused(Exception):
    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


# ---------------------------------------------------------------- the child

def _limit() -> None:
    import resource
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    for name, value in LIMITS.items():
        resource.setrlimit(getattr(resource, name), (value, value))
    confine.die_with_parent(signal.SIGKILL)             # before the filter, which then refuses undoing it (ARG-1)
    confine.deadline(DEADLINE_S)                        # and its own SIGKILL clock, which the filter keeps in place
    try:
        os.nice(NICE)
    except OSError:
        pass


CODECS = ("utf-8", "utf-16", "utf-16-be", "utf-16-le", "latin-1", "ascii")    # each one the PDF libraries name


def preload() -> None:
    """#12: import, before the wall and before any input is read, everything the child would otherwise load after it,
    since behind the wall it can't read its own sys.path. The PDF libraries, and what they import only on first use:
    PIL and its PNG writer for a render, cryptography's backend and pdfminer's password rule for an AES file, and the
    codecs they decode with (a ToUnicode map is UTF-16BE). Then what the selfcheck's probes import. Nothing here reads
    a PDF."""
    import base64  # noqa: F401
    import codecs
    import fcntl  # noqa: F401
    import socket  # noqa: F401

    import pdfminer._saslprep  # noqa: F401
    import pdfplumber  # noqa: F401
    import pypdfium2  # noqa: F401
    from cryptography.hazmat.backends import default_backend
    from PIL import Image, PngImagePlugin  # noqa: F401
    default_backend()                                   # imports the OpenSSL backend pdfminer asks for on each AES call
    Image.preinit()                                     # the plugins Image.save looks up by name
    for name in CODECS:
        codecs.lookup(name)


def _area(im: dict, w: float, h: float) -> float:
    x0, x1 = max(0.0, float(im["x0"])), min(w, float(im["x1"]))
    t, b = max(0.0, float(im["top"])), min(h, float(im["bottom"]))
    return max(0.0, x1 - x0) * max(0.0, b - t)


def read_pdf(data: bytes) -> dict:
    """The child's whole job: {"pages": [{"n", "width", "height", "scan", "lines"}]}, or Refused with a copy key."""
    from steward_pdf.lines import is_scan, page_lines
    if len(data) > MAX_BYTES:
        raise Refused("too_big")
    if b"%PDF-" not in data[:1024]:
        raise Refused("not_pdf")
    import pypdfium2 as pdfium
    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        raise Refused("password" if "password" in str(e).lower() else "unreadable") from None
    try:
        if len(doc) > MAX_PAGES:
            raise Refused("too_many_pages")
    finally:
        doc.close()
    import pdfplumber
    try:
        pdf = pdfplumber.open(io.BytesIO(data), password="")
    except Exception:                                   # noqa: BLE001 - any parser failure is this file's only
        raise Refused("unreadable") from None
    with pdf:
        if len(pdf.pages) > MAX_PAGES:                  # pdfplumber walks its own page tree: count it too (P8 step 5)
            raise Refused("too_many_pages")
        if sum(len(x.get_objids()) for x in pdf.doc.xrefs) > MAX_OBJECTS:
            raise Refused("unreadable")
        pages = []
        for n, page in enumerate(pdf.pages, 1):
            if n > MAX_PAGES:
                raise Refused("too_many_pages")
            w, h = float(page.width), float(page.height)
            if not (0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE) or len(page.chars) > MAX_CHARS_PAGE:
                raise Refused("unreadable")
            lines = page_lines(page.extract_words(keep_blank_chars=False, use_text_flow=False))
            image = sum(_area(im, w, h) for im in page.images)
            pages.append({"n": n, "width": round(w, 1), "height": round(h, 1), "scan": is_scan(lines, w, h, image),
                          "lines": lines})
            page.close()
    out = {"pages": pages}
    if len(json.dumps(out, ensure_ascii=False).encode()) > LINES_CAP:
        raise Refused("unreadable")
    return out


def _errno(fn) -> str:
    try:
        fn()
    except OSError as e:
        return errno.errorcode.get(e.errno or 0, "?")
    return "ok"


def _probes() -> dict:
    """What the filter refuses, tried for real (each would succeed unconfined)."""
    import resource
    import socket

    def fork() -> None:
        if os.fork() == 0:
            os._exit(0)
        os.wait()

    def thread() -> None:
        t = threading.Thread(target=lambda: None)
        t.start()
        t.join()
    return {"socket": _errno(lambda: socket.socket().close()),
            "exec": _errno(lambda: os.execv("/bin/true", ["true"])),
            "fork": _errno(fork),
            "write": _errno(lambda: os.close(os.open("probe", os.O_WRONLY | os.O_CREAT, 0o600))),
            "signal_parent": _errno(lambda: os.kill(os.getppid(), 0)),
            "limit_parent": _errno(lambda: resource.prlimit(os.getppid(), resource.RLIMIT_CORE)),
            "thread": _errno(thread)}


def _selfcheck_child(confined: bool, seccomp: int) -> dict:
    import resource
    empty = os.listdir(".") == []
    probes, denied, escapes, memfd = {}, {}, {}, {}
    pdeathsig = confine.parent_death_signal()           # before probe_escapes tries to clear it
    deadline = confine.deadline_left()                  # and to move or delete it
    if confined and seccomp == 2:
        probes, denied = {**_probes(), **confine.probe_edges()}, confine.probe_raw()
        escapes = confine.probe_escapes(os.getppid())
        memfd = confine.probe_memfd()
    try:
        bytearray(2 * 1024 ** 3)
        big = "allowed"
    except MemoryError:
        big = "refused"
    try:
        with open("probe", "wb") as f:
            f.write(b"x")
            f.flush()
        write = "allowed"
    except OSError:
        write = "refused"
    finally:
        if os.path.exists("probe"):
            os.remove("probe")
    return {"limits": {n: list(resource.getrlimit(getattr(resource, n))) for n in LIMITS}, "big": big, "write": write,
            "env": sorted(os.environ), "cwd_empty": empty, "nice": os.nice(0), "seccomp": seccomp, "probes": probes,
            "denied": denied, "escapes": escapes, "pdeathsig": pdeathsig, "deadline": deadline, "memfd": memfd,
            "deadline_after": confine.deadline_left()}


def _sigio_child(confined: bool) -> dict:
    """ARG-2, tried for real: make the parent stdin's owner, ask for SIGUSR1 on input, turn on O_ASYNC, then say ready
    and read stdin to its end. The parent's test writes to it and counts the signals it gets."""
    import fcntl
    out = {}
    if confined:
        out["F_SETOWN"] = _errno(lambda: fcntl.fcntl(0, fcntl.F_SETOWN, os.getppid()))
        out["F_SETSIG"] = _errno(lambda: fcntl.fcntl(0, confine.FCNTL_REFUSED["F_SETSIG"], signal.SIGUSR1))
        out["O_ASYNC"] = _errno(lambda: fcntl.fcntl(0, fcntl.F_SETFL, fcntl.fcntl(0, fcntl.F_GETFL) | os.O_ASYNC))
    sys.stdout.write("ready\n")
    sys.stdout.flush()
    sys.stdin.buffer.read()
    return out


def canary_pdf() -> bytes:
    """A one-page PDF built here, so the check reads and renders a real file inside the filter and the wall (P58)."""
    text = b"BT /F1 12 Tf 20 100 Td (Steward canary) Tj ET"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(text), text),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, at = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        at.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % a for a in at)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def _confined_child(confined: bool, seccomp: int, walled: bool) -> dict:
    """P54, P58: what holds here, tried for real: a read of a file outside the wall, then the canary read and rendered
    inside both the filter and the wall."""
    try:
        with open("/etc/passwd", "rb"):
            probe = "allowed"
    except PermissionError:
        probe = "refused"
    except OSError:
        probe = "missing"
    canary = "skipped"
    if confined and seccomp == 2:
        try:
            data = canary_pdf()
            canary = "ok" if len(read_pdf(data)["pages"]) == 1 and render_page(data, 1)["n"] == 1 else "failed"
        except Exception:                               # noqa: BLE001 - a library the wall kept out, a parser bug
            canary = "failed"
    return {"confined": confined, "seccomp": seccomp, "walled": walled, "probe": probe, "canary": canary}


RENDER_DPI, FALLBACK_DPI = 200, 150
MAX_PX = 2200
MAX_PNG = 3 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_PNG_B64 = 4 * ((MAX_PNG + 2) // 3)
RENDER_KEYS = frozenset({"png", "width_px", "height_px", "n"})
RENDER_PNG = (8, 0, 0, 0, 0)        # IHDR's bit depth, colour type (greyscale), compression, filter, interlace: PIL's "L"


def render_page(data: bytes, n: int) -> dict:
    """P26: one page, just before it's sent: 200 DPI, greyscale, the long side at most 2,200 px whatever size the page
    claims, a PNG at most 3 MB (150 DPI when bigger; still bigger is an error). The child's job in render mode."""
    import base64

    if len(data) > MAX_BYTES:
        raise Refused("too_big")
    if b"%PDF-" not in data[:1024]:
        raise Refused("not_pdf")
    import pypdfium2 as pdfium
    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        raise Refused("password" if "password" in str(e).lower() else "unreadable") from None
    try:
        if len(doc) > MAX_PAGES:
            raise Refused("too_many_pages")
        if not 1 <= n <= len(doc):
            raise Refused("unreadable")
        page = doc[n - 1]
        try:
            w, h = page.get_size()
            if not (0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE):
                raise Refused("unreadable")
            for dpi in (RENDER_DPI, FALLBACK_DPI):
                scale = min(dpi / 72, MAX_PX / max(w, h))
                img = page.render(scale=scale, grayscale=True, may_draw_forms=False).to_pil().convert("L")
                buf = io.BytesIO()
                img.save(buf, "PNG", optimize=True)
                png = buf.getvalue()
                if len(png) <= MAX_PNG:
                    return {"png": base64.b64encode(png).decode("ascii"), "width_px": img.width, "height_px": img.height,
                            "n": n}
            raise Refused("unreadable")
        finally:
            page.close()
    finally:
        doc.close()


def main(argv: list[str]) -> int:
    """One rule for every machine (P59, and the 0.1.0 gate's SEC-2): the child reads a PDF only with the filter and the
    wall both up, checked here in the child itself, so a check cached at startup that has gone stale can't let a read
    through. Without Landlock, seccomp still blocks the network, exec and writes, but not reading Steward's files."""
    _limit()
    os.umask(0o077)
    walled = confined = False
    try:
        confine.no_new_privs()                          # the wall and the filter both need it
        ready = True
    except Exception:                                   # noqa: BLE001 - not Linux x86_64: it stays unconfined
        ready = False
    if ready:                                           # the wall first, so the filter can refuse landlock_* after
        preload()                                       # before the wall, which keeps sys.path out; a failure here
        #                                                 ends the child, so nothing reads
        try:
            walled = landlock.restrict(landlock.runtime_paths()) > 0
        except Exception:                               # noqa: BLE001 - no Landlock here: the caller decides (P59)
            walled = False
        try:
            confine.install()                           # last, before stdin is read
            confined = True
        except Exception:                               # noqa: BLE001 - any failure leaves it unconfined
            confined = False
    seccomp = confine.mode()
    if argv == ["--selfcheck"]:
        out = _selfcheck_child(confined, seccomp)
    elif argv == ["--confined"]:
        out = _confined_child(confined, seccomp, walled)
    elif argv == ["--selfcheck", "x32"]:                # only ever kills itself: the test reads the signal
        if confined:
            confine.x32_call()
        out = {"x32": "survived" if confined else "unconfined"}
    elif argv == ["--selfcheck", "sigio"]:
        out = _sigio_child(confined and seccomp == 2)
    elif len(argv) == 3 and argv[:2] == ["--selfcheck", "outside"]:
        out = confine.probe_outside(argv[2]) if confined and seccomp == 2 else {}
    elif not (confined and seccomp == 2 and walled):
        out = {"error": "unreadable"}                   # fail closed: a child without the filter and the wall never
        #                                                 reads a PDF
    else:
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        try:
            if len(argv) == 2 and argv[0] == "--render" and argv[1].isdigit():
                out = render_page(data, int(argv[1]))
            else:
                out = read_pdf(data)
        except Refused as e:
            out = {"error": e.key}
        except Exception:                               # noqa: BLE001 - MemoryError, RecursionError, a parser bug
            out = {"error": "unreadable"}
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    sys.stdout.flush()
    return 0


# ---------------------------------------------------------------- the parent

@dataclass(frozen=True)
class Outcome:
    pages: list[dict] | None
    error: str | None


def _feed(stream, data: bytes) -> None:
    try:
        for i in range(0, len(data), 1 << 16):
            stream.write(data[i:i + (1 << 16)])
    except (BrokenPipeError, OSError, ValueError):
        pass                                            # the child stopped reading: its exit says why
    finally:
        try:
            stream.close()                              # closed on a broken pipe too (ARG-6)
        except (OSError, ValueError):
            pass


def _read(stream, cap: int) -> bytes | None:
    buf = bytearray()
    while True:
        chunk = stream.read(1 << 16)
        if not chunk:
            return bytes(buf)
        buf += chunk
        if len(buf) > cap:
            return None


def _run(args: list[str], data: bytes, popen, timer, wall_s: float, out_cap: int) -> tuple[bytes | None, int, bool]:
    folder = tempfile.mkdtemp(prefix="steward-pdf-")
    killed = threading.Event()
    proc = None
    try:
        os.chmod(folder, 0o700)
        proc = popen([sys.executable, "-I", "-B", "-m", MODULE, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.DEVNULL, env={}, cwd=folder, close_fds=True)

        def stop() -> None:
            killed.set()
            proc.kill()
        clock = timer(wall_s, stop)
        clock.daemon = True
        clock.start()
        feeder = threading.Thread(target=_feed, args=(proc.stdin, data), daemon=True)
        feeder.start()
        out = _read(proc.stdout, out_cap)
        if out is None:
            proc.kill()
        code = proc.wait()
        clock.cancel()
        feeder.join(timeout=5)
    finally:
        if proc is not None and proc.stdout is not None:
            proc.stdout.close()
        shutil.rmtree(folder, ignore_errors=True)
    return out, code, killed.is_set()


# What the child prints is the attacker's if a crafted PDF took it over, so the parent believes none of it: strict JSON
# under the output cap (counted as it's read), exactly the keys and types read_pdf and render_page write, the caps
# page_lines keeps, and a PNG judged by its own header rather than by the sizes the child reports.
PAGE_KEYS = frozenset({"n", "width", "height", "scan", "lines"})
MAX_AT = 2 * MAX_SIDE                                   # a word may sit off the page's edge (_onto clamps it back);
#                                                         no real one sits this far
MAX_TEXT_PAGE = 4 * MAX_CHARS_PAGE                      # a page's cell text: with a joining space, a ligature ("ffi")
#                                                         or a masked digit ("••"), one character is at most 4


def _json(out: bytes):
    """The child's stdout as strict JSON (UTF-8, no NaN or Infinity, no repeated key), or None."""
    def unique(pairs: list) -> dict:
        d = dict(pairs)
        if len(d) != len(pairs):
            raise ValueError("a repeated key")
        return d

    def constant(name: str):
        raise ValueError(name)
    try:
        return json.loads(out.decode("utf-8"), object_pairs_hook=unique, parse_constant=constant)
    except (ValueError, RecursionError):                # UnicodeDecodeError is a ValueError
        return None


def _refusal(body: dict) -> str | None:
    return body["error"] if set(body) == {"error"} and isinstance(body["error"], str) and body["error"] in ERRORS \
        else None


def _int(v) -> bool:
    return type(v) is int


def _at(v, lo: float = -MAX_AT, hi: float = MAX_AT) -> bool:
    return type(v) in (int, float) and lo <= v <= hi      # NaN and infinity fail the bounds (and strict JSON has none)


def _cells(cells) -> int | None:
    """A line's cells as page_lines writes them; the characters they hold, or None."""
    if not isinstance(cells, list) or not 1 <= len(cells) <= CELLS_PER_LINE:
        return None
    chars = 0
    for c in cells:
        if not isinstance(c, dict) or c.keys() != {"x0", "x1", "text"} or not _at(c["x0"]) or not _at(c["x1"]):
            return None
        t = c["text"]
        if not isinstance(t, str) or not 0 < len(t) <= CELL_CHARS or not t.isprintable():
            return None
        chars += len(t)
    return chars


def _pages(pages) -> list[dict] | None:
    """read_pdf's pages, numbered 1 to at most MAX_PAGES, each held to page_lines' caps; None when anything is off."""
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
        return None
    for n, p in enumerate(pages, 1):
        if not isinstance(p, dict) or p.keys() != PAGE_KEYS or not _int(p["n"]) or p["n"] != n:
            return None
        if not (_at(p["width"], 0, MAX_SIDE) and p["width"] > 0 and _at(p["height"], 0, MAX_SIDE) and p["height"] > 0):
            return None
        if type(p["scan"]) is not bool or not isinstance(p["lines"], list) or len(p["lines"]) > LINES_PER_PAGE:
            return None
        chars = 0
        for ln in p["lines"]:
            if not isinstance(ln, dict) or ln.keys() != {"y", "cells"} or not _at(ln["y"]):
                return None
            got = _cells(ln["cells"])
            if got is None:
                return None
            chars += got
        if chars > MAX_TEXT_PAGE:
            return None
    return [_onto(p) for p in pages]


def _clamp(v: float, hi: float) -> float:
    return min(max(v, 0.0), hi)                          # a value already on the page comes back as it was


def _onto(p: dict) -> dict:
    """A checked page with its text moved onto the page's own box (at most MAX_SIDE a side): a word just past the edge
    is real text, and the bands, the fingerprint and the gateway (0-5000) all need on-page positions."""
    w, h = p["width"], p["height"]
    return {**p, "lines": [{"y": _clamp(ln["y"], h),
                            "cells": [{"x0": _clamp(c["x0"], w), "x1": _clamp(c["x1"], w), "text": c["text"]}
                                      for c in ln["cells"]]} for ln in p["lines"]]}


def parse_extract(out: bytes | None) -> Outcome:
    """The child's stdout, or the gateway's answer to /v1/statements/extract (remote-reading P62): believed only as
    read_pdf's exact shape, under read_pdf's caps, with every position moved onto its page; else "unreadable"."""
    if out is None:
        return Outcome(None, "unreadable")
    body = _json(out)
    if not isinstance(body, dict):
        return Outcome(None, "unreadable")
    if (key := _refusal(body)) is not None:
        return Outcome(None, key)
    pages = _pages(body["pages"]) if body.keys() == {"pages"} else None
    return Outcome(pages, None) if pages is not None else Outcome(None, "unreadable")


def run_extract(data: bytes, *, popen=subprocess.Popen, timer=threading.Timer, wall_s: float = WALL_S,
                out_cap: int = OUT_CAP) -> Outcome:
    """The child's pages, checked by parse_extract. The child itself refuses unless the filter and the wall are up."""
    try:
        out, code, killed = _run([], data, popen, timer, wall_s, out_cap)
    except OSError:                                     # no process, no temp folder: this file's refusal, no traceback
        return Outcome(None, "unreadable")
    if killed or code == -signal.SIGXCPU:
        return Outcome(None, "too_slow")
    if out is None or code != 0:
        return Outcome(None, "unreadable")
    return parse_extract(out)


@dataclass(frozen=True)
class Rendered:
    png: bytes | None
    width: int
    height: int
    error: str | None


def parse_render(out: bytes | None, n: int) -> Rendered:
    """The child's stdout, or the gateway's answer to /v1/statements/render (remote-reading P62), checked again: the page
    asked for, and a PNG at most 3 MB whose own header says 8-bit greyscale (what render_page saves) at the size
    reported, at most 2,200 px a side."""
    import base64

    if out is None:
        return Rendered(None, 0, 0, "unreadable")
    body = _json(out)
    if not isinstance(body, dict):
        return Rendered(None, 0, 0, "unreadable")
    if (key := _refusal(body)) is not None:
        return Rendered(None, 0, 0, key)
    if body.keys() != RENDER_KEYS or not _int(body["n"]) or body["n"] != n or not isinstance(body["png"], str) \
            or len(body["png"]) > MAX_PNG_B64:
        return Rendered(None, 0, 0, "unreadable")
    try:
        png = base64.b64decode(body["png"], validate=True)
    except ValueError:                                  # binascii.Error
        return Rendered(None, 0, 0, "unreadable")
    head = png_header(png)
    if head is None or len(png) > MAX_PNG or (head.depth, head.colour, head.compression, head.filter,
                                              head.interlace) != RENDER_PNG:
        return Rendered(None, 0, 0, "unreadable")
    w, h = head.width, head.height
    if not (w <= MAX_PX and h <= MAX_PX) or (body["width_px"], body["height_px"]) != (w, h) \
            or not (_int(body["width_px"]) and _int(body["height_px"])):
        return Rendered(None, 0, 0, "unreadable")
    return Rendered(png, w, h, None)


def run_render(data: bytes, n: int, *, popen=subprocess.Popen, timer=threading.Timer, wall_s: float = WALL_S,
               out_cap: int = OUT_CAP) -> Rendered:
    """One page's picture from the child, checked by parse_render; the child refuses as in run_extract."""
    try:
        out, code, killed = _run(["--render", str(n)], data, popen, timer, wall_s, out_cap)
    except OSError:                                     # no process, no temp folder: this page's refusal, no traceback
        return Rendered(None, 0, 0, "unreadable")
    if killed or code == -signal.SIGXCPU:
        return Rendered(None, 0, 0, "too_slow")
    if out is None or code != 0:
        return Rendered(None, 0, 0, "unreadable")
    return parse_render(out, n)


def selfcheck(*, popen=subprocess.Popen) -> dict:
    out, _, _ = _run(["--selfcheck"], b"", popen, threading.Timer, WALL_S, OUT_CAP)
    return json.loads(out or b"{}")


CONFINED_KEYS = frozenset({"confined", "seccomp", "walled", "probe", "canary"})


def confinement(*, popen=subprocess.Popen) -> dict:
    """The child's own report of what holds on this machine (P54, P58), or {} when it can't say. Run once at startup
    by Steward (auto) and by the gateway (before it offers to open PDFs)."""
    try:
        out, code, killed = _run(["--confined"], b"", popen, threading.Timer, WALL_S, 4096)
    except OSError:
        return {}
    body = _json(out) if out is not None and code == 0 and not killed else None
    return body if isinstance(body, dict) and body.keys() == CONFINED_KEYS else {}


def can_wall(c: dict) -> bool:
    """P54, P58: the one rule for opening PDFs on a machine, Steward's own or the gateway: the filter (seccomp mode 2),
    the wall (a read outside it refused), and the canary read inside both. Nothing decides on the filter alone."""
    return c.get("confined") is True and c.get("seccomp") == 2 and c.get("walled") is True \
        and c.get("probe") == "refused" and c.get("canary") == "ok"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
