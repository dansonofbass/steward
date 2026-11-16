"""The sandbox (spec P8, P11): a child process with rlimits, an empty environment and folder, a wall timeout and an
output cap; every outcome is a copy key, one bad file fails only its own line; nothing is left on disk."""
import io
import json
import signal
import subprocess
import tempfile
from pathlib import Path

import pytest

from steward_pdf import confine
from steward_pdf import sandbox as S
from steward_gateway.evals.statement_set import BANK_CARD
from tests.statement_files import pdf


class FakeProc:
    """A stand-in for Popen: what the child would print and how it would exit."""
    def __init__(self, out: bytes = b"", code: int = 0):
        self.stdin, self.stdout, self.code, self.killed = io.BytesIO(), io.BytesIO(out), code, False

    def wait(self, timeout=None):
        return -signal.SIGKILL if self.killed else self.code

    def kill(self):
        self.killed = True
        self.stdout = io.BytesIO(b"")


class NowTimer:
    """A stand-in for threading.Timer whose time is already up when it starts."""
    def __init__(self, _s, fn):
        self.fn = fn
        self.daemon = False

    def start(self):
        self.fn()

    def cancel(self):
        pass


def _popen(proc):
    return lambda *a, **k: proc


def test_the_child_reads_a_statement_as_the_parent_would():
    data = pdf("chase_checking")[0]
    out = S.run_extract(data)
    assert out.error is None and out.pages == S.read_pdf(data)["pages"]


def test_the_child_sets_its_limits_and_they_hold():
    """P8: read back with resource.getrlimit; a 2 GiB allocation and a file write both fail at once (no load)."""
    got = S.selfcheck()
    assert got["limits"] == {k: [v, v] for k, v in S.LIMITS.items()}
    assert (got["big"], got["write"], got["cwd_empty"]) == ("refused", "refused", True)
    assert set(got["env"]) <= {"LC_CTYPE"}                     # PEP 538's locale coercion may add this one


def test_a_password_pdf_through_the_child():
    assert S.run_extract(pdf("chase_checking", "password")[0]).error == "password"


def test_the_wall_timeout_and_a_cpu_overrun_are_too_slow():
    assert S.run_extract(b"%PDF-", popen=_popen(FakeProc(b'{"pages": []}')), timer=NowTimer).error == "too_slow"
    assert S.run_extract(b"%PDF-", popen=_popen(FakeProc(b"", -signal.SIGXCPU))).error == "too_slow"


def test_bad_json_a_crash_and_too_much_output_are_unreadable():
    assert S.run_extract(b"%PDF-", popen=_popen(FakeProc(b"{not json"))).error == "unreadable"
    assert S.run_extract(b"%PDF-", popen=_popen(FakeProc(b"", -signal.SIGSEGV))).error == "unreadable"
    assert S.run_extract(b"%PDF-", popen=_popen(FakeProc(b'{"pages": []}', 1))).error == "unreadable"
    assert S.run_extract(b"%PDF-", popen=_popen(FakeProc(b"x" * 101)), out_cap=100).error == "unreadable"
    assert S.run_extract(b"%PDF-", popen=_popen(FakeProc(b'{"error": "not a key"}'))).error == "unreadable"
    assert S.run_extract(b"%PDF-", popen=_popen(FakeProc(b'{"error": "password"}'))).error == "password"


def test_one_bad_file_leaves_the_next_untouched():
    assert S.run_extract(b"not a pdf at all").error == "not_pdf"
    assert S.run_extract(pdf("boa_checking")[0]).pages


def test_the_child_leaves_no_files(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    before = sorted(tmp_path.rglob("*"))
    S.run_extract(pdf("citi_card")[0])
    S.run_extract(b"%PDF-1.7 broken")
    assert sorted(tmp_path.rglob("*")) == before


def test_the_child_is_isolated_and_bounded():
    seen = {}

    def spy(args, **kw):
        seen.update(kw, args=args)
        return FakeProc(b'{"pages": []}')
    S.run_extract(b"%PDF-", popen=spy)
    assert seen["args"][1:5] == ["-I", "-B", "-m", "steward_pdf.sandbox"]
    assert seen["env"] == {} and seen["stderr"] is subprocess.DEVNULL and seen["close_fds"] is True


def test_only_the_child_imports_the_pdf_libraries():
    src = Path(S.__file__).parents[1]
    files = [*(src / "steward").rglob("*.py"), *(src / "steward_pdf").rglob("*.py"),
             *(p for p in (src / "steward_gateway").rglob("*.py") if "evals" not in p.parts)]
    hits = [str(p) for p in files if p.name != "sandbox.py"
            and ("import pdfplumber" in p.read_text() or "import pypdfium2" in p.read_text())]
    assert hits == []
    for line in Path(S.__file__).read_text().splitlines():
        if "import pdfplumber" in line or "import pypdfium2" in line:
            assert line.startswith("    "), "imported at module level: the parent would load it"


def test_a_failure_to_start_the_child_is_this_files_refusal():
    def broken(*a, **k):
        raise OSError("EAGAIN")
    assert S.run_extract(pdf("chase_checking")[0], popen=broken) == S.Outcome(None, "unreadable")


def test_the_childs_output_pipe_is_closed():
    proc = FakeProc(b"{}")
    S.run_extract(b"x", popen=_popen(proc))
    assert proc.stdout.closed


def test_the_child_confines_itself_before_it_reads():
    """The seccomp filter is on (mode 2) and holds: no socket, exec, fork, write-mode open, signal to or limit of
    another process; threads still start, and a clone with any flag past glibc's thread set is refused; every
    outright-denied syscall answers EPERM."""
    got = S.selfcheck()
    assert got["seccomp"] == 2
    assert got["probes"] == {"socket": "EPERM", "exec": "EPERM", "fork": "EPERM", "write": "EPERM",
                             "signal_parent": "EPERM", "limit_parent": "EPERM", "thread": "ok",
                             "clone3": "ENOSYS", "clone_newuser": "EPERM", "clone_parent": "EPERM",
                             "clone_exit_signal": "EPERM", "clone_high_half": "EPERM"}
    assert got["denied"] == {name: "EPERM" for name in confine.PROBED}
    assert {"io_uring_setup", "pidfd_send_signal", "bpf", "unshare", "mount", "personality"} <= set(got["denied"])


def test_an_x32_syscall_kills_the_child():
    """A number with the x32 bit set would slip past a number denylist: the filter kills the process instead."""
    out, code, _ = S._run(["--selfcheck", "x32"], b"", subprocess.Popen, S.threading.Timer, S.WALL_S, S.OUT_CAP)
    assert (out, code) == (b"", -signal.SIGSYS)


@pytest.mark.parametrize("sid", [*BANK_CARD, "receipt"])
def test_every_synthetic_statement_reads_exactly_in_the_confined_child(sid):
    data = pdf(sid)[0]
    out = S.run_extract(data)
    assert out.error is None and out.pages == S.read_pdf(data)["pages"]


def test_a_filter_that_wont_install_means_the_pdf_is_never_read(monkeypatch):
    from tests.test_pdf_wall import _main                       # the one in-process runner: every step stubbed

    def never(_data):
        raise AssertionError("read without the filter")
    monkeypatch.setattr(S, "read_pdf", never)
    stdin = io.TextIOWrapper(io.BytesIO(pdf("chase_checking")[0]))
    assert _main(monkeypatch, [], confined=False, stdin=stdin) == {"error": "unreadable"}


@pytest.mark.parametrize("platform, machine", [("darwin", "x86_64"), ("linux", "aarch64"), ("win32", "AMD64")])
def test_off_linux_x86_64_the_filter_refuses_before_touching_the_kernel(monkeypatch, platform, machine):
    monkeypatch.setattr(confine.sys, "platform", platform)
    monkeypatch.setattr(confine, "_machine", lambda: machine)
    monkeypatch.setattr(confine, "_libc", lambda: pytest.fail("reached prctl"))
    with pytest.raises(confine.Unconfined):
        confine.install()


# ---- the parent trusts nothing the child prints (P8): a crafted PDF may own the child, so its stdout is the attacker's

def _cell(text="Opening balance", x0=40.0):
    return {"x0": x0, "x1": x0 + 80.0, "text": text}


def _line(cells=None, y=100.0):
    return {"y": y, "cells": [_cell()] if cells is None else cells}


def _page(n=1, lines=None, **kw):
    return {"n": n, "width": 612.0, "height": 792.0, "scan": False, "lines": [_line()] if lines is None else lines, **kw}


def _extract(body) -> S.Outcome:
    out = body if isinstance(body, bytes) else json.dumps(body).encode()
    return S.run_extract(b"%PDF-", popen=_popen(FakeProc(out)))


def test_a_well_formed_child_answer_passes():
    pages = [_page(1), _page(2, lines=[]), _page(3, scan=True)]
    assert _extract({"pages": pages}) == S.Outcome(pages, None)


class Endless:
    """A child that never stops printing: the cap must stop the read, not the end of the stream."""
    def __init__(self):
        self.reads = 0

    def read(self, n):
        self.reads += 1
        assert self.reads <= 3, "read on past the cap"
        return b"x" * n

    def close(self):
        pass


def test_the_output_cap_is_enforced_while_reading():
    proc = FakeProc()
    proc.stdout = stream = Endless()
    assert S.run_extract(b"%PDF-", popen=_popen(proc), out_cap=100).error == "unreadable"
    assert stream.reads == 1 and proc.killed


@pytest.mark.parametrize("out", [
    b'{"pages": [{"n": 1, "width": NaN, "height": 792, "scan": false, "lines": []}]}',      # not strict JSON
    b'{"pages": [], "pages": [' + json.dumps(_page()).encode() + b"]}",                      # a repeated key
    b'{"pages": "\xff\xfe"}',                                                                # not UTF-8
    b"[" * 100_000 + b"]" * 100_000,                                                        # nested past the stack
    b"null",
    b"\xef\xbb\xbf" + json.dumps({"pages": [_page()]}).encode(),                             # a BOM
], ids=["nan", "repeated-key", "not-utf8", "deep", "null", "bom"])
def test_output_that_isnt_strict_json_is_unreadable(out):
    assert _extract(out) == S.Outcome(None, "unreadable")


@pytest.mark.parametrize("body", [
    {"pages": [_page()], "extra": 1},
    {"error": "password", "pages": []},
    {"error": "password", "detail": "x"},
    {"pages": [_page(extra=True)]},
    {"pages": [_page(lines=[{**_line(), "z": 0}])]},
    {"pages": [_page(lines=[_line(cells=[{**_cell(), "font": "x"}])])]},
    {"pages": [{k: v for k, v in _page().items() if k != "scan"}]},
], ids=["top", "error-and-pages", "error-extra", "page", "line", "cell", "missing"])
def test_extra_or_missing_keys_are_unreadable(body):
    assert _extract(body) == S.Outcome(None, "unreadable")


def test_a_page_count_over_the_cap_or_off_from_the_pages_is_unreadable():
    assert _extract({"pages": [_page(n) for n in range(1, S.MAX_PAGES + 1)]}).error is None
    assert _extract({"pages": [_page(n) for n in range(1, S.MAX_PAGES + 2)]}) == S.Outcome(None, "unreadable")
    assert _extract({"pages": []}) == S.Outcome(None, "unreadable")
    assert _extract({"pages": [_page(1), _page(3)]}) == S.Outcome(None, "unreadable")
    assert _extract({"pages": [_page(2)]}) == S.Outcome(None, "unreadable")
    assert _extract({"pages": [_page(True)]}) == S.Outcome(None, "unreadable")


def test_line_cell_and_character_caps_hold_on_the_parent():
    from steward.services.statements.extract import CELL_CHARS, CELLS_PER_LINE, LINES_PER_PAGE
    ok = [_line(y=float(i)) for i in range(LINES_PER_PAGE)]
    assert _extract({"pages": [_page(lines=ok)]}).error is None
    assert _extract({"pages": [_page(lines=[*ok, _line()])]}).error == "unreadable"
    assert _extract({"pages": [_page(lines=[_line(cells=[_cell()] * CELLS_PER_LINE)])]}).error is None
    assert _extract({"pages": [_page(lines=[_line(cells=[_cell()] * (CELLS_PER_LINE + 1))])]}).error == "unreadable"
    assert _extract({"pages": [_page(lines=[_line(cells=[])])]}).error == "unreadable"
    assert _extract({"pages": [_page(lines=[_line(cells=[_cell("x" * CELL_CHARS)])])]}).error is None
    assert _extract({"pages": [_page(lines=[_line(cells=[_cell("x" * (CELL_CHARS + 1))])])]}).error == "unreadable"
    full = [_line(cells=[_cell("x" * CELL_CHARS)] * 2, y=float(i)) for i in range(LINES_PER_PAGE)]
    assert _extract({"pages": [_page(lines=full)]}).error == "unreadable"          # each within its cap; the page isn't


@pytest.mark.parametrize("cell", [_cell(""), _cell("\x1b[31mred"), _cell("a b"), _cell(7), _cell(None),
                                  {**_cell(), "x0": float("inf")}, {**_cell(), "x1": "40"}, {**_cell(), "x0": True},
                                  {**_cell(), "x0": 1e9}],
                         ids=["empty", "escape", "separator", "int", "none", "inf", "str-x", "bool-x", "far"])
def test_every_cell_is_printable_text_at_a_real_position(cell):
    assert _extract({"pages": [_page(lines=[_line(cells=[cell])])]}) == S.Outcome(None, "unreadable")


@pytest.mark.parametrize("page", [_page(width=0), _page(width=S.MAX_SIDE + 1), _page(height=True), _page(height="792"),
                                  _page(scan=1), _page(scan=None), _page(lines={}), _page(lines=[_line(y=-1e9)])],
                         ids=["zero", "wide", "bool", "str", "scan-int", "scan-none", "lines-dict", "far-y"])
def test_a_pages_size_flag_and_lines_must_be_what_the_child_writes(page):
    assert _extract({"pages": [page]}) == S.Outcome(None, "unreadable")


def test_text_just_off_the_page_is_clamped_onto_it_and_the_gateway_takes_it():
    """A word a little past the page's edge is real text: it's moved onto the page's own box, so the bands, the
    fingerprint and the layout request all see on-page positions (the gateway refuses anything outside 0-5000)."""
    from steward.services.statements.extract import for_model
    from steward_boundary.statements_wire import pages_errors
    lines = [_line(cells=[{"x0": -3.0, "x1": 60.0, "text": "Opening balance"}], y=-2.0),
             _line(cells=[{"x0": 500.0, "x1": 612.0 + 4, "text": "1,234.56"}], y=792.0 + 5)]
    out = _extract({"pages": [_page(lines=lines)]})
    assert out.error is None
    got = out.pages[0]["lines"]
    assert [(ln["y"], c["x0"], c["x1"]) for ln in got for c in ln["cells"]] == [(0.0, 0.0, 60.0), (792.0, 500.0, 612.0)]
    assert pages_errors(for_model(out.pages)) == []
