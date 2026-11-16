"""The wall and the check (remote-reading P54, P58, P59): a confined child also walls off every file but its runtime
with Landlock, and reports what holds, tried for real; the parent believes only that report's exact shape. One rule
for every machine (the 0.1.0 gate's SEC-2): no child reads a PDF without the filter and the wall both up."""
import ast
import ctypes
import io
import json
import logging
import os
import sys
from pathlib import Path

import pytest

from steward_pdf import confine, landlock
from steward_pdf import sandbox as S
from tests.statement_files import pdf
from tests.test_statement_sandbox import FakeProc, _popen

GOOD = {"confined": True, "seccomp": 2, "walled": True, "probe": "refused", "canary": "ok"}


def test_the_child_walls_its_reads_and_still_reads_a_pdf():
    got = S.confinement()
    assert got == GOOD
    assert S.can_wall(got)


def test_the_selfcheck_still_holds_behind_the_wall_and_runs_at_nice_10():
    got = S.selfcheck()
    assert got["seccomp"] == 2 and got["cwd_empty"] is True and got["write"] == "refused"
    assert got["probes"]["socket"] == "EPERM" and got["nice"] >= S.NICE


def test_the_canary_is_a_real_one_page_pdf():
    data = S.canary_pdf()
    page = S.read_pdf(data)["pages"]
    assert len(page) == 1 and "Steward canary" in " ".join(c["text"] for ln in page[0]["lines"] for c in ln["cells"])
    assert S.render_page(data, 1)["n"] == 1


def _main(monkeypatch, argv, *, confined=True, mode=2, walled=True, stdin=None, order=None):
    """The child's main() in this process, its rlimits, filter and wall stubbed (pytest itself is never confined).
    walled: True puts the wall up, False makes restrict raise, 0 makes it report no rule added. order, a list, gets
    the setup steps in the order main takes them."""
    out = io.StringIO()
    steps = [] if order is None else order

    def install():
        steps.append("install")
        if not confined:
            raise confine.Unconfined("seccomp")

    def restrict(_paths):
        steps.append("restrict")
        if walled is False:
            raise landlock.Unrestricted("landlock")
        return 7 if walled is True else 0
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(S, "_limit", lambda: None)
    monkeypatch.setattr(S.os, "umask", lambda _m: 0)
    monkeypatch.setattr(confine, "no_new_privs", lambda: steps.append("no_new_privs"))
    monkeypatch.setattr(confine, "install", install)
    monkeypatch.setattr(confine, "mode", lambda: mode)
    monkeypatch.setattr(landlock, "restrict", restrict)
    monkeypatch.setattr(sys, "stdout", out)
    before = _own_state()
    assert S.main(argv) == 0
    assert _own_state() == before, "main confined pytest itself: a setup step went unstubbed"
    return json.loads(out.getvalue())


def _own_state() -> tuple:
    """This process's no_new_privs, seccomp mode and whether it can still list /: what a real confinement step run
    in pytest would change for good (Landlock would wall the worker off from its own tmp folders)."""
    libc = ctypes.CDLL(None)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    try:
        listed = bool(os.listdir("/"))
    except OSError:
        listed = False
    return libc.prctl(confine.PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0), libc.prctl(confine.PR_GET_SECCOMP, 0, 0, 0, 0), listed


def test_only_the_stubbed_runner_calls_the_childs_main_in_process():
    """The class behind two tests that walled their own pytest worker once the wall went up before the filter: a test
    that runs the child's main() in this process with only some setup steps stubbed runs the rest for real. _main
    stubs every step and checks the process after; no other test calls main() directly."""
    callers = []
    for path in sorted(Path(__file__).parent.rglob("test_*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "main" \
                    and isinstance(node.func.value, ast.Name) and node.func.value.id in {"S", "sandbox"}:
                callers.append(path.name)
    assert callers == ["test_pdf_wall.py"]


def test_a_kernel_without_seccomp_reports_it_cant_confine(monkeypatch):
    """The NAS (Synology's 4.4): confine.install raises Unconfined, PR_GET_SECCOMP can't answer, and Landlock (5.13+)
    isn't there either."""
    got = _main(monkeypatch, ["--confined"], confined=False, mode=-1, walled=False)
    assert got == {"confined": False, "seccomp": -1, "walled": False, "probe": "allowed", "canary": "skipped"}
    assert not S.can_wall(got)


def test_the_wall_goes_up_before_the_filter(monkeypatch):
    """Argon's second round: with the filter first, landlock_* (and seccomp) had to stay allowed under it. Now the
    wall goes up first and the filter last, so the filter refuses them both (tests/test_pdf_syscalls.py)."""
    order = []
    assert _main(monkeypatch, ["--confined"], order=order)["confined"] is True
    assert order == ["no_new_privs", "restrict", "install"]


def test_confinement_believes_only_its_own_shape():
    for out in (b"", b"[]", b"not json", b'{"confined": true}', json.dumps({**GOOD, "more": 1}).encode()):
        assert S.confinement(popen=_popen(FakeProc(out))) == {}
    assert S.confinement(popen=_popen(FakeProc(json.dumps(GOOD).encode(), code=1))) == {}

    def broken(*a, **k):
        raise OSError("no process")
    assert S.confinement(popen=broken) == {}


def test_can_wall_needs_every_part():
    assert S.can_wall(GOOD)
    for k, v in (("confined", False), ("seccomp", 0), ("walled", False), ("probe", "allowed"), ("canary", "failed")):
        assert not S.can_wall({**GOOD, k: v}), k
    assert not S.can_wall({**GOOD, "walled": False, "probe": "allowed", "canary": "skipped"}) and not S.can_wall({})


SRC = Path(S.__file__).parents[1]
FILTER_ONLY = {**GOOD, "walled": False, "probe": "allowed"}             # seccomp without Landlock (SEC-2's kernel)


def test_nothing_decides_a_read_on_the_filter_alone(caplog):
    """SEC-2's class: a place to read PDFs chosen on a narrower check than the gateway's. Every module that asks for
    the confinement report decides with can_wall, no narrower rule exists to call, and Steward's own choice sends a
    filter-only machine's PDFs to the gateway (a forced local warns and its child refuses them)."""
    from steward.services.statements import where
    assert not hasattr(S, "can_confine")
    askers = []
    for path in SRC.rglob("*.py"):
        text = path.read_text()
        tree = ast.parse(text)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
            {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert "can_confine" not in names, path
        if "confinement" in names and path.name != "sandbox.py":
            askers.append(path.relative_to(SRC).as_posix())
            assert "can_wall" in names, f"{path} asks for the report but doesn't decide with can_wall"
    assert sorted(askers) == ["steward/services/statements/where.py", "steward_gateway/cli.py",
                              "steward_gateway/pdf.py"]
    assert where.resolve("auto", probe=True, check=lambda: FILTER_ONLY) == "gateway"
    assert where.resolve("auto", probe=True, check=lambda: GOOD) == "local"
    caplog.set_level(logging.WARNING)
    assert where.resolve("local", probe=True, check=lambda: FILTER_ONLY) == "local"
    assert "can't confine" in caplog.text


def test_without_landlock_restrict_refuses(monkeypatch):
    monkeypatch.setattr(landlock, "abi", lambda: 0)
    with pytest.raises(landlock.Unrestricted):
        landlock.restrict(["/usr/lib"])


def test_the_wall_lets_in_only_the_runtime():
    paths = landlock.runtime_paths()
    assert any(sys.base_prefix == p or sys.base_prefix.startswith(p + "/") for p in paths)
    assert not set(paths) & {"/", "/etc", "/home", "/root", "/var", "/tmp", "/proc"}
    assert landlock.handled(1) == (1 << 13) - 1 and landlock.handled(7) == (1 << 16) - 1


class Untouched(io.RawIOBase):
    """A stdin that fails the test if the child reads it."""
    def readable(self):
        return True

    def readinto(self, _b):
        raise AssertionError("stdin read without the wall")


def test_no_child_reads_with_the_filter_alone(monkeypatch):
    """SEC-2, on any machine: a kernel with seccomp but no Landlock (or a wall that adds no rule) leaves the child able to
    open the book key and the books, so it refuses before it touches stdin, for a read and for a render."""
    def never(*_a):
        raise AssertionError("read without the wall")
    monkeypatch.setattr(S, "read_pdf", never)
    monkeypatch.setattr(S, "render_page", never)
    for walled in (False, 0):
        for argv in ([], ["--render", "1"]):
            stdin = io.TextIOWrapper(io.BufferedReader(Untouched()))
            assert _main(monkeypatch, argv, walled=walled, stdin=stdin) == {"error": "unreadable"}, (walled, argv)
    stdin = io.TextIOWrapper(io.BufferedReader(Untouched()))
    assert _main(monkeypatch, [], mode=0, stdin=stdin) == {"error": "unreadable"}


def test_with_the_filter_and_the_wall_up_the_child_reads(monkeypatch):
    data = pdf("chase_checking")[0]
    got = _main(monkeypatch, [], stdin=io.TextIOWrapper(io.BytesIO(data)))
    assert got == S.read_pdf(data)


def test_run_extract_and_run_render_have_no_flag_that_changes_the_rule():
    seen = []

    def popen(args, **_k):
        seen.append(args[args.index(S.MODULE) + 1:])
        return FakeProc(b"{}")
    S.run_extract(b"x", popen=popen)
    S.run_render(b"x", 2, popen=popen)
    assert seen == [[], ["--render", "2"]]
    with pytest.raises(TypeError):
        S.run_extract(b"x", popen=popen, wall=False)                    # the old opt-out is gone
