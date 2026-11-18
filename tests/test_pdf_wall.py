"""The wall and the check (remote-reading P54, P58, P59): a confined child also walls off every file but its runtime
with Landlock, and reports what holds, tried for real; the parent believes only that report's exact shape. One rule
for every machine (the 0.1.0 gate's SEC-2): no child reads a PDF without the filter and the wall both up."""
import ast
import base64
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
    """The child's main() in this process, its rlimits, preload, filter and wall stubbed (pytest itself is never
    confined). The preload fails the test if stdin has been read.
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

    def preload():
        steps.append("preload")
        if stdin is not None and stdin.buffer.seekable():               # an Untouched stdin fails on any read
            assert stdin.buffer.tell() == 0, "stdin read before the preload"
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(S, "_limit", lambda: None)
    monkeypatch.setattr(S.os, "umask", lambda _m: 0)
    monkeypatch.setattr(confine, "no_new_privs", lambda: steps.append("no_new_privs"))
    monkeypatch.setattr(confine, "install", install)
    monkeypatch.setattr(confine, "mode", lambda: mode)
    monkeypatch.setattr(landlock, "restrict", restrict)
    monkeypatch.setattr(S, "preload", preload)
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
    assert order == ["no_new_privs", "preload", "restrict", "install"]


def test_the_pdf_libraries_load_before_the_wall_and_before_any_input(monkeypatch):
    """#12: behind the wall the child can't read its own sys.path, so it imports the PDF libraries first, on every
    path through main and before stdin is read."""
    for argv in ([], ["--render", "1"], ["--confined"]):
        order = []
        stdin = io.TextIOWrapper(io.BytesIO(S.canary_pdf()))
        _main(monkeypatch, argv, stdin=stdin, order=order)
        assert order[:3] == ["no_new_privs", "preload", "restrict"], argv


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


def _covers(granted: str, path: str) -> bool:
    return path == granted or path.startswith(granted.rstrip("/") + "/")


def test_the_wall_lets_in_only_fonts_character_maps_and_its_folder():
    """#12: with the libraries imported first, the wall grants pdfium's font folders, pdfminer's character map folders
    and the child's own empty folder. No prefix of the interpreter and no sys.path entry is granted."""
    paths = landlock.runtime_paths()
    cmaps = [p for p in paths if p.endswith("/pdfminer/cmap")]
    assert len(cmaps) == 1
    assert set(paths) <= {*landlock.FONTS, *landlock.CMAPS, *cmaps, os.getcwd()}
    granted = [p for p in paths if p != os.getcwd()]                    # the child's is its own empty folder
    for entry in {sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix, *filter(None, sys.path)}:
        assert not any(_covers(p, entry) for p in granted), entry
    assert not set(paths) & {"/", "/etc", "/home", "/root", "/var", "/tmp", "/proc", "/usr/lib", "/usr/local/lib"}
    assert landlock.handled(1) == (1 << 13) - 1 and landlock.handled(7) == (1 << 16) - 1


def _one_file(folder: str) -> str | None:
    try:
        return next((e.path for e in sorted(os.scandir(folder), key=lambda e: e.name) if e.is_file()), None)
    except OSError:
        return None


def test_a_read_under_sys_path_fails_inside_the_wall():
    """#12: a taken-over reader can't read the interpreter's files, the installed packages or Steward's source: one
    file from every sys.path folder, plus the sandbox's own source and pdfplumber's, tried for real behind the wall.
    An editable install or a .pth file pointing at a folder with private files exposes nothing."""
    from importlib.util import find_spec
    files = {S.__file__, find_spec("pdfplumber").origin, find_spec("pypdfium2").origin, os.__file__}
    files |= {f for f in map(_one_file, filter(os.path.isdir, sys.path)) if f}
    for path in sorted(files):
        out, code, _ = S._run(["--selfcheck", "outside", path], b"", S.subprocess.Popen, S.threading.Timer, S.WALL_S,
                              S.OUT_CAP)
        assert code == 0 and json.loads(out)["open"] == "EACCES", path


LATE = r"""
import base64, json, os, sys
from steward_pdf import landlock, sandbox as S
S.preload()
preloaded, imported, opened = sorted(sys.modules), [], []
def hook(event, args):
    if event == "import":
        imported.append(args[0])
    elif event == "open" and isinstance(args[0], (str, bytes)):
        opened.append(os.fsdecode(args[0]))
sys.addaudithook(hook)
for data in map(base64.b64decode, json.loads(sys.stdin.read())):
    for job in (lambda: S.read_pdf(data), lambda: S.render_page(data, 1)):
        try:
            job()
        except S.Refused:
            pass
print(json.dumps({"preloaded": preloaded, "imported": imported, "opened": opened, "paths": landlock.runtime_paths()}))
"""


def _first_use(kind: str) -> bytes:
    """A file that takes the libraries down a path the synthetic statements never do."""
    from tests.statement_files import aes_pdf, font_pdf
    return aes_pdf() if kind == "aes" else font_pdf(kind)


FIRST_USE = ("cid", "embedded", "aes")


def _corpus() -> list[bytes]:
    from steward_gateway.evals.statement_set import BANK_CARD, HSPECS
    return [S.canary_pdf(), *map(_first_use, FIRST_USE), pdf("receipt")[0], *(pdf(s)[0] for s in BANK_CARD),
            *(pdf("chase_checking", v)[0] for v in ("password", "permissions", "scan", "mixed")),
            *(pdf(s)[0] for s in HSPECS)]


@pytest.fixture(scope="module")
def late(tmp_path_factory) -> dict:
    """A throwaway child, never walled: the preload, then an audit hook, then a real read and render of every kind of
    file the tests know. What it imports or opens after the preload is what a walled child would need."""
    import subprocess
    body = json.dumps([base64.b64encode(d).decode() for d in _corpus()])
    done = subprocess.run([sys.executable, "-I", "-B", "-c", LATE], input=body.encode(), capture_output=True,
                          env={}, cwd=tmp_path_factory.mktemp("late"), timeout=S.WALL_S, check=True)
    return json.loads(done.stdout)


def test_after_the_preload_a_real_read_imports_nothing_and_opens_only_what_the_wall_grants(late):
    """#12, found by test: whatever the libraries load late shows up here as an import (which the wall would refuse)
    or as an open outside the granted folders."""
    assert late["imported"] == []
    assert [p for p in late["opened"] if not any(_covers(g, p) for g in late["paths"])] == []
    assert any("/pdfminer/cmap/" in p for p in late["opened"]), "the CID file no longer loads a character map"


UNREACHABLE = {
    "pygame": "pdfminer.ccitt's debugging viewer",
    "unittest": "pdfminer.ccitt's own test entry point",
    "numpy": "pypdfium2's to_numpy, which the child never calls",
    "tabulate": "pypdfium2's command line",
    "pdfplumber.display": "Page.to_image, which the child never calls",
    "PIL.ImageChops": "pdfminer.image's ImageWriter, which pdfplumber never makes",
    "PIL.ImageOps": "pdfminer.image's ImageWriter, which pdfplumber never makes",
}


def _submodule(name: str) -> bool:
    from importlib.util import find_spec
    try:
        return find_spec(name) is not None
    except (ImportError, ValueError):                                   # its package isn't installed
        return False


def _lazy_imports(package: str) -> set[tuple[str, str]]:
    """Every import inside a function in package: (file, module), relative imports resolved. `from pkg import name`
    counts as pkg, and as pkg.name too when name is a submodule (`from PIL import ImageChops` loads PIL.ImageChops)."""
    from importlib.util import find_spec
    root = Path(find_spec(package).origin).parent
    found = set()
    for path in root.rglob("*.py"):
        here = path.relative_to(root.parent).parts[:-1]                # the package the file's in
        for fn in ast.walk(ast.parse(path.read_text())):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Import):
                    found |= {(path.name, a.name) for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    base = here[:len(here) - node.level + 1] if node.level else ()
                    module = ".".join([*base, *([node.module] if node.module else [])])
                    found.add((path.name, module))
                    found |= {(path.name, f"{module}.{a.name}") for a in node.names
                              if a.name != "*" and _submodule(f"{module}.{a.name}")}
    return found


def test_every_import_the_pdf_libraries_make_on_first_use_is_preloaded_or_never_reached(late):
    """#12's class: a library that imports a module only when first needed (PIL for a render, pdfminer's AES-256
    password rule) would fail behind the wall. Each such import in pdfminer, pdfplumber and pypdfium2 is preloaded or
    named here with why the child never reaches it; a library update that adds one fails this test."""
    missing = sorted({(f, m) for pkg in ("pdfminer", "pdfplumber", "pypdfium2") for f, m in _lazy_imports(pkg)
                      if m not in late["preloaded"] and m.split(".")[0] not in UNREACHABLE and m not in UNREACHABLE})
    assert missing == []


@pytest.mark.parametrize("kind", FIRST_USE)
def test_files_that_load_code_on_first_use_read_and_render_the_same_behind_the_wall(kind):
    """A CID font's character maps, a ToUnicode map's UTF-16 codec, and AES, whose cryptography backend loads on first
    use: each would come back unreadable if the wall kept out what it loads."""
    data = _first_use(kind)
    out = S.run_extract(data)
    assert out.error is None and out.pages == S.read_pdf(data)["pages"]
    got = S.run_render(data, 1)
    assert got.error is None and got.png == base64.b64decode(S.render_page(data, 1)["png"])


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
