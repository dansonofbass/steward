"""What this machine has for the gateway to run on (PR 13b). Read-only: it looks at device nodes and sysfs under a root
and asks three programs short questions (nvidia-smi -L, docker info, rocminfo); it installs and changes nothing.
deploy/gateway/detect-gpu.sh does the same in plain sh, and both are tested on tests/gateway/hardware_scenarios.py."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Runner = Callable[[Sequence[str]], "str | None"]

NVIDIA_NEXT = 'Next: docs/guides/gpu.md, "NVIDIA".'
TOOLKIT_NEXT = "Next: install NVIDIA's Container Toolkit, then follow docs/guides/gpu.md, \"NVIDIA\"."
AMD_NEXT = 'Next: docs/guides/gpu.md, "AMD" (not yet tested on real hardware).'
NOT_YET_NEXT = ("Next: nothing yet. Steward finds it but doesn't use it yet, because Ollama's and torch's support for "
                "Intel GPUs and for NPUs is still experimental. The gateway runs on the CPU.")
NOTHING_NEXT = "Next: nothing to do. The gateway runs on the CPU."
UNKNOWN_GROUP = "Unknown: render group (STEWARD_RENDER_GID). ls -ln /dev/kfd shows its number, in the fourth column."

_NPU_LABELS = {"0x8086": "Intel NPU", "0x1022": "AMD NPU"}


def run_command(args: Sequence[str]) -> str | None:
    """stdout when the program exits 0; None when it fails, is missing, hangs or can't be run."""
    try:
        done = subprocess.run(list(args), capture_output=True, text=True, errors="replace", timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


@dataclass(frozen=True)
class Hardware:
    nvidia: str | None                                                   # "" when found with no name
    docker_runtime: Literal["found", "missing", "unknown"] | None
    amd: str | None
    render_gid: int | None
    intel_gpu: str | None
    npu: tuple[str, str] | None                                          # (label, node), like ("Intel NPU", "accel0")


def _read(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return None


def _vendor(root: Path, kind: str, node: str) -> str:
    return (_read(root / "sys" / "class" / kind / node / "device" / "vendor") or "").strip().lower()


def _names(directory: Path, prefix: str) -> list[str]:
    try:
        return sorted(n for n in os.listdir(directory) if n.startswith(prefix))
    except OSError:
        return []


def _render_nodes(root: Path, vendor: str) -> list[str]:
    """Render nodes of one vendor that really exist in /dev/dri, in byte order (as an sh glob sorts them)."""
    return [n for n in _names(root / "sys" / "class" / "drm", "renderD")
            if _vendor(root, "drm", n) == vendor and (root / "dev" / "dri" / n).exists()]


def _nvidia(root: Path, run: Runner, have: Callable[[str], bool]) -> str | None:
    if have("nvidia-smi"):
        m = re.search(r"^GPU \d+: (.+?) \(UUID", run(["nvidia-smi", "-L"]) or "", re.M)
        if m:
            return m.group(1)
    # /dev/dxg alone never counts: WSL exposes every vendor through it.
    return "" if any(re.fullmatch(r"nvidia\d+", n) for n in _names(root / "dev", "nvidia")) else None


def _docker_runtime(run: Runner, have: Callable[[str], bool]) -> Literal["found", "missing", "unknown"] | None:
    if not have("docker"):
        return None
    out = run(["docker", "info", "--format", "{{json .Runtimes}}"])
    if out is None:
        return "unknown"
    return "found" if '"nvidia"' in out else "missing"


def _amd(root: Path, run: Runner, have: Callable[[str], bool]) -> tuple[str | None, int | None]:
    nodes = _render_nodes(root, "0x1002")
    if not (root / "dev" / "kfd").exists() or not nodes:
        return None, None
    gfx = re.search(r"gfx\w+", run(["rocminfo"]) or "") if have("rocminfo") else None
    return (gfx.group(0) if gfx else nodes[0]), _group(root / "dev" / "kfd")


def _group(path: Path) -> int | None:
    """The node's group number, or None when it can't be read (the report then says how to find it)."""
    try:
        return os.stat(path).st_gid
    except OSError:
        return None


def _npu(root: Path) -> tuple[str, str] | None:
    nodes = _names(root / "dev" / "accel", "accel")
    if not nodes:
        return None
    return _NPU_LABELS.get(_vendor(root, "accel", nodes[0]), "NPU"), nodes[0]


def probe(root: Path = Path("/"), run: Runner = run_command,
          have: Callable[[str], bool] = lambda c: shutil.which(c) is not None) -> Hardware:
    nvidia = _nvidia(root, run, have)
    amd, gid = _amd(root, run, have)
    intel = _render_nodes(root, "0x8086")
    return Hardware(nvidia, _docker_runtime(run, have) if nvidia is not None else None, amd, gid,
                    intel[0] if intel else None, _npu(root))


def report(hw: Hardware) -> list[str]:
    lines: list[str] = []
    if hw.nvidia is not None:
        lines.append(f"Found: NVIDIA GPU ({hw.nvidia})" if hw.nvidia else "Found: NVIDIA GPU")
    if hw.docker_runtime == "found":
        lines.append("Found: Docker's NVIDIA runtime")
    elif hw.docker_runtime == "missing":
        lines.append("Missing: Docker's NVIDIA runtime (the NVIDIA Container Toolkit)")
    elif hw.docker_runtime == "unknown":
        lines.append("Unknown: Docker's NVIDIA runtime (docker info didn't answer)")
    if hw.amd is not None:
        lines.append(f"Found: AMD GPU ({hw.amd})")
        lines.append(UNKNOWN_GROUP if hw.render_gid is None
                     else f"Found: render group {hw.render_gid} (STEWARD_RENDER_GID)")
    if hw.intel_gpu is not None:
        lines.append(f"Found: Intel GPU ({hw.intel_gpu})")
    if hw.npu is not None:
        lines.append(f"Found: {hw.npu[0]} ({hw.npu[1]})")
    if not lines:
        lines.append("Found: no GPU or NPU")
    if hw.docker_runtime == "missing":
        lines.append(TOOLKIT_NEXT)
    elif hw.nvidia is not None:
        lines.append(NVIDIA_NEXT)
    elif hw.amd is not None:
        lines.append(AMD_NEXT)
    elif hw.intel_gpu is not None or hw.npu is not None:
        lines.append(NOT_YET_NEXT)
    else:
        lines.append(NOTHING_NEXT)
    return lines
