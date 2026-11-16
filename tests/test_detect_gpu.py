"""deploy/gateway/detect-gpu.sh: for a host with no gateway yet. Plain sh, read-only, and the same lines as
steward-gateway hardware for every machine in the shared table."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.gateway.hardware_scenarios import SCENARIOS, build

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "gateway" / "detect-gpu.sh"
TOOLS = ("sh", "cat", "grep", "head", "sed", "stat", "tr")


def hermetic(tmp_path, s) -> str:
    """A PATH holding only the tools the script may use and the scenario's stub commands, never the real ones. A stub
    that fails complains on stderr, as real ones do, so the script must keep every failure quiet."""
    tools, stubs = tmp_path / "tools", tmp_path / "stubs"
    tools.mkdir()
    stubs.mkdir()
    for t in TOOLS:
        (tools / t).symlink_to(shutil.which(t))
    for name, (code, out) in s.commands.items():
        (stubs / f"{name}.out").write_text(out)
        complain = f'echo "{name}: failed" >&2\n' if code else ""
        (stubs / name).write_text(f'#!/bin/sh\ncat "{stubs / (name + ".out")}"\n{complain}exit {code}\n')
        (stubs / name).chmod(0o755)
    return f"{stubs}:{tools}"


@pytest.mark.parametrize("s", SCENARIOS, ids=lambda s: s.id)
def test_the_script_prints_the_same_lines(tmp_path, s):
    root = build(tmp_path, s)
    gid = os.stat(root / "dev" / "kfd").st_gid if (root / "dev" / "kfd").exists() else None
    p = subprocess.run([shutil.which("sh"), str(SCRIPT)], capture_output=True, text=True, timeout=20,
                       env={"PATH": hermetic(tmp_path, s), "STEWARD_DETECT_ROOT": str(root)})
    assert p.returncode == 0 and p.stderr == ""
    assert p.stdout.splitlines() == [line.format(gid=gid) for line in s.lines]


def test_the_script_is_plain_sh_and_writes_nothing():
    text = SCRIPT.read_text()
    assert text.startswith("#!/bin/sh\n") and os.access(SCRIPT, os.X_OK)
    for bash_only in ("[[", "function ", "local ", "$'", "<<<"):
        assert bash_only not in text, bash_only
    for writes in (" > ", ">>", "tee ", "rm ", "mkdir", "apt", "dnf", "pip", "curl", "wget", "sudo"):
        assert writes not in text, writes
