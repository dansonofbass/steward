"""Machines for the hardware detection tests (PR 13b). Paths are relative to a fake root and command keys are program
names. tests/gateway/test_hardware.py runs `steward-gateway hardware`'s logic on them, and the shell script
deploy/gateway/detect-gpu.sh is tested on the same table, so the two must print the same lines. `lines` may hold
{gid}, the group of the fake /dev/kfd."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

NVIDIA_NEXT = 'Next: docs/guides/gpu.md, "NVIDIA".'
TOOLKIT_NEXT = "Next: install NVIDIA's Container Toolkit, then follow docs/guides/gpu.md, \"NVIDIA\"."
AMD_NEXT = 'Next: docs/guides/gpu.md, "AMD" (not yet tested on real hardware).'
NOT_YET_NEXT = ("Next: nothing yet. Steward finds it but doesn't use it yet, because Ollama's and torch's support for "
                "Intel GPUs and for NPUs is still experimental. The gateway runs on the CPU.")
NOTHING_NEXT = "Next: nothing to do. The gateway runs on the CPU."
SMI = (0, "GPU 0: NVIDIA GeForce RTX 3080 Ti (UUID: GPU-00000000-0000-0000-0000-000000000000)\n")
RUNTIMES_NVIDIA = (0, '{"io.containerd.runc.v2":{},"nvidia":{"path":"nvidia-container-runtime"},"runc":{}}\n')
RUNTIMES_PLAIN = (0, '{"io.containerd.runc.v2":{},"runc":{}}\n')

GPU_LINE = "Found: NVIDIA GPU (NVIDIA GeForce RTX 3080 Ti)"
GROUP_LINE = "Found: render group {gid} (STEWARD_RENDER_GID)"
UNKNOWN_GROUP_LINE = ("Unknown: render group (STEWARD_RENDER_GID). ls -ln /dev/kfd shows its number, in the fourth "
                      "column.")
AMD_FILES = {"dev/kfd": "", "dev/dri/renderD128": "", "sys/class/drm/renderD128/device/vendor": "0x1002\n"}


@dataclass(frozen=True)
class Scenario:
    id: str
    files: dict[str, str]
    commands: dict[str, tuple[int, str]]
    lines: list[str]


SCENARIOS: list[Scenario] = [
    Scenario("nvidia-with-toolkit", {"dev/nvidia0": "", "dev/nvidiactl": ""},
             {"nvidia-smi": SMI, "docker": RUNTIMES_NVIDIA},
             [GPU_LINE, "Found: Docker's NVIDIA runtime", NVIDIA_NEXT]),
    Scenario("nvidia-wsl-no-toolkit", {"dev/dxg": ""},
             {"nvidia-smi": SMI, "docker": RUNTIMES_PLAIN},
             [GPU_LINE, "Missing: Docker's NVIDIA runtime (the NVIDIA Container Toolkit)", TOOLKIT_NEXT]),
    Scenario("nvidia-driver-broken", {"dev/nvidia0": ""}, {"nvidia-smi": (9, "")},
             ["Found: NVIDIA GPU", NVIDIA_NEXT]),
    # WSL2: a render node whose sysfs directory has no device/vendor file. Detection must stay quiet about it.
    Scenario("nvidia-wsl-render-node-without-vendor",
             {"dev/dxg": "", "dev/dri/renderD128": "", "sys/class/drm/renderD128/version": ""},
             {"nvidia-smi": SMI, "docker": RUNTIMES_NVIDIA},
             [GPU_LINE, "Found: Docker's NVIDIA runtime", NVIDIA_NEXT]),
    Scenario("npu-without-vendor", {"dev/accel/accel0": ""}, {},
             ["Found: NPU (accel0)", NOT_YET_NEXT]),
    Scenario("nvidia-docker-down", {},{"nvidia-smi": SMI, "docker": (1, "")},
             [GPU_LINE, "Unknown: Docker's NVIDIA runtime (docker info didn't answer)", NVIDIA_NEXT]),
    Scenario("amd", dict(AMD_FILES), {"rocminfo": (0, "  Name:                    gfx1100\n")},
             ["Found: AMD GPU (gfx1100)", GROUP_LINE, AMD_NEXT]),
    Scenario("amd-no-rocminfo", dict(AMD_FILES), {},
             ["Found: AMD GPU (renderD128)", GROUP_LINE, AMD_NEXT]),
    # /dev/kfd's group can't be read: a failing "stat" here stands in for the script's stat (it complains on stderr)
    # and makes test_hardware.py's group lookup fail too. Both print how to find the number, and nothing on stderr.
    Scenario("amd-group-unreadable", dict(AMD_FILES), {"stat": (1, "")},
             ["Found: AMD GPU (renderD128)", UNKNOWN_GROUP_LINE, AMD_NEXT]),
    Scenario("intel-gpu-and-npu",
             {"dev/dri/renderD128": "", "sys/class/drm/renderD128/device/vendor": "0x8086\n",
              "dev/accel/accel0": "", "sys/class/accel/accel0/device/vendor": "0x8086\n"}, {},
             ["Found: Intel GPU (renderD128)", "Found: Intel NPU (accel0)", NOT_YET_NEXT]),
    Scenario("amd-npu-only", {"dev/accel/accel0": "", "sys/class/accel/accel0/device/vendor": "0x1022\n"}, {},
             ["Found: AMD NPU (accel0)", NOT_YET_NEXT]),
    Scenario("nvidia-and-intel",
             {"dev/nvidia0": "", "dev/dri/renderD129": "", "sys/class/drm/renderD129/device/vendor": "0x8086\n"},
             {"nvidia-smi": SMI},
             [GPU_LINE, "Found: Intel GPU (renderD129)", NVIDIA_NEXT]),
    Scenario("nothing", {}, {}, ["Found: no GPU or NPU", NOTHING_NEXT]),
]


def build(tmp_path: Path, s: Scenario) -> Path:
    """Write the scenario's files under tmp_path/root (device nodes are empty regular files); return the root."""
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in s.files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root
