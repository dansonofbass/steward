"""The gateway image (release spec 2026-11-05, section 7): CPU only, so no NVIDIA wheel is baked in; its bases pinned by
digest and the same as the app image's; its own user and private folders; nothing secret; a compose-mode config."""
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from tests.gateway.license_values import LICENSE_VALUES

ROOT = Path(__file__).resolve().parents[1]
GW = ROOT / "deploy" / "gateway"
DIGEST = r"@sha256:[0-9a-f]{64}"
CPU_INDEX = "https://download.pytorch.org/whl/cpu"
FOLDERS = "/etc/steward-gateway /var/lib/steward-gateway /var/cache/steward-gateway"


IMAGES = {"Dockerfile": None, "Dockerfile.cuda": "nvidia", "Dockerfile.rocm": "amd"}


def dockerfile(name="Dockerfile") -> str:
    return (GW / name).read_text()


def locked() -> list[dict]:
    return tomllib.loads((ROOT / "uv.lock").read_text())["package"]


@pytest.mark.parametrize("name", IMAGES)
def test_the_bases_are_pinned_and_the_same_as_the_app_images(name):
    app = (ROOT / "Dockerfile").read_text()
    python = re.search(r"^FROM (python:3\.12-slim\S+) AS base$", app, re.M)[1]
    uv = re.search(r"^COPY --from=(ghcr\.io/astral-sh/uv\S+) ", app, re.M)[1]
    assert re.search(DIGEST + "$", python) and re.search(DIGEST + "$", uv)
    assert re.findall(r"^FROM (\S+) AS (\w+)$", dockerfile(name), re.M) == [(python, "base")]
    assert re.findall(r"^COPY --from=(\S+) ", dockerfile(name), re.M) == [uv]


def test_torch_is_the_cpu_build_of_the_locked_version_pinned_by_hash():
    version = next(p["version"] for p in locked() if p["name"] == "torch")
    reqs = [l for l in (GW / "torch-cpu.txt").read_text().splitlines() if l.strip() and not l.startswith("#")]
    assert len(reqs) == 1 and re.fullmatch(rf"torch=={re.escape(version)}\+cpu --hash=sha256:[0-9a-f]{{64}}", reqs[0])
    for flag in (f"--index-url {CPU_INDEX}", "--no-deps", "--require-hashes", "-r torch-cpu.txt"):
        assert flag in dockerfile(), flag


def test_no_cuda_wheel_from_the_lock_is_installed():
    cuda = {p["name"] for p in locked() if re.match(r"nvidia-|cuda-", p["name"]) or p["name"] == "triton"}
    assert cuda                                       # PyPI's torch brings them on Linux
    assert set(re.findall(r"--no-install-package (\S+)", dockerfile())) == cuda | {"torch"}
    assert "sys.exit(torch.version.cuda is not None)" in dockerfile()
    assert "grep -Eiq '^(nvidia|cuda|triton)'" in dockerfile()


@pytest.mark.parametrize("name", IMAGES)
def test_it_installs_the_gateway_groups_and_never_runs_uv_at_start(name):
    d = dockerfile(name)
    assert "uv sync --frozen --no-dev --group gateway --group models" in d
    assert "uv run" not in d
    assert re.findall(r"^CMD (.+)$", d, re.M) == ['["steward-gateway", "serve"]']
    assert re.findall(r"^EXPOSE (.+)$", d, re.M) == ["8430"]


@pytest.mark.parametrize("name", IMAGES)
def test_it_runs_as_its_own_user_with_private_folders(name):
    d = dockerfile(name)
    assert "useradd -u 1000 -m steward-gw" in d
    assert f"install -d -m 700 -o steward-gw -g steward-gw {FOLDERS}" in d
    assert "COPY --chown=steward-gw:steward-gw deploy/gateway/gateway.toml /etc/steward-gateway/gateway.toml" in d
    assert re.findall(r"^USER (\S+)$", d, re.M) == ["steward-gw"]
    assert d.index("USER steward-gw") < d.index("CMD [")


@pytest.mark.parametrize("name", IMAGES)
def test_the_image_bakes_in_no_secret(name):
    d = dockerfile(name)
    assert re.findall(r"^ARG (\S+)$", d, re.M) == ([] if IMAGES[name] is None else ["STEWARD_GPU_LICENSE_ACCEPTED"])
    env = {}
    for line in d.splitlines():
        if line.startswith("ENV "):
            env.update(re.findall(r'(\w+)=("[^"]*"|\S+)', line[4:]))
    expected = {"STEWARD_GATEWAY_CONFIG_DIR": "/etc/steward-gateway",
                "STEWARD_GATEWAY_STATE_DIR": "/var/lib/steward-gateway",
                "HF_HOME": "/var/cache/steward-gateway", "XDG_CACHE_HOME": "/var/cache/steward-gateway",
                "HF_HUB_DISABLE_TELEMETRY": "1", "PATH": '"/app/.venv/bin:$PATH"'}
    if IMAGES[name] is not None:
        expected["STEWARD_GATEWAY_GPU"] = IMAGES[name]
    assert env == expected
    sources = re.findall(r"^COPY (?:--\S+ )*(.+) \S+$", d, re.M)
    assert not any(n in s for s in sources for n in ("gateway.env", ".token", "history.key", ".env"))


def test_the_baked_config_is_compose_mode(tmp_path, monkeypatch):
    from steward_gateway import config
    marker = tmp_path / ".dockerenv"
    marker.touch()
    monkeypatch.setattr(config, "CONTAINER_MARKERS", (marker,))
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "gateway.toml").write_text((GW / "gateway.toml").read_text())
    cfg = config.load_config(tmp_path / "c", tmp_path / "s")
    assert (cfg.network, cfg.host, cfg.port, cfg.ollama_url, cfg.timezone, cfg.mcp) == (
        "compose", "0.0.0.0", 8430, "http://ollama:11434", "UTC", False)


ROCM_INDEX = "https://download.pytorch.org/whl/rocm7.2"
NAMES = {"nvidia": "NVIDIA's CUDA", "amd": "AMD's ROCm"}


@pytest.mark.parametrize("name, vendor", [("Dockerfile.cuda", "nvidia"), ("Dockerfile.rocm", "amd")])
def test_a_gpu_image_refuses_to_build_before_its_license_is_accepted(name, vendor):
    d = dockerfile(name)
    gate = d.index("ARG STEWARD_GPU_LICENSE_ACCEPTED")
    check = d.index(f'= {vendor} ] || {{ echo "Building this image downloads {NAMES[vendor]} libraries')
    assert gate < check < d.index("uv sync")                         # nothing of the vendor's is fetched before it
    assert f'then set STEWARD_GPU_LICENSE_ACCEPTED={vendor} in .env and build again."; exit 1; }}' in d


def build_gate(name: str) -> str:
    """The Dockerfile's license check, as the shell command its RUN line runs."""
    gates = [l[len("RUN "):] for l in dockerfile(name).splitlines()
             if l.startswith("RUN ") and "$STEWARD_GPU_LICENSE_ACCEPTED" in l]
    assert len(gates) == 1
    return gates[0]


@pytest.mark.parametrize("value, vendor, accepted", LICENSE_VALUES)
def test_the_build_gate_follows_the_same_rule_as_the_start_up_gate(value, vendor, accepted):
    """The RUN line itself, run in sh as the image's shell runs it (LANG=C.UTF-8 as in python:3.12-slim), on the table
    tests/gateway/test_gpu_mode.py checks gpu.license_problem on."""
    name = {"nvidia": "Dockerfile.cuda", "amd": "Dockerfile.rocm"}[vendor]
    p = subprocess.run([shutil.which("sh"), "-c", build_gate(name)], capture_output=True, text=True, timeout=20,
                       env={"PATH": os.environ["PATH"], "LANG": "C.UTF-8", "STEWARD_GPU_LICENSE_ACCEPTED": value})
    assert p.stderr == ""
    if accepted:
        assert p.returncode == 0 and p.stdout == ""
    else:
        assert p.returncode == 1 and p.stdout.startswith(f"Building this image downloads {NAMES[vendor]} libraries")


def test_the_cuda_image_is_the_lock_as_the_systemd_gateway_installs_it():
    d = dockerfile("Dockerfile.cuda")
    assert "--no-install-package" not in d and "uv pip install" not in d
    assert "sys.exit(torch.version.cuda is None)" in d


def test_the_rocm_image_swaps_torch_for_the_locked_versions_rocm_build():
    d, cpu = dockerfile("Dockerfile.rocm"), dockerfile()
    assert set(re.findall(r"--no-install-package (\S+)", d)) == set(re.findall(r"--no-install-package (\S+)", cpu))
    for flag in (f"--index-url {ROCM_INDEX}", "--no-deps", "--require-hashes", "-r torch-rocm.txt", "uv pip check",
                 "sys.exit(torch.version.hip is None)"):
        assert flag in d, flag
    version = next(p["version"] for p in locked() if p["name"] == "torch")
    reqs = [l for l in (GW / "torch-rocm.txt").read_text().splitlines() if l.strip() and not l.startswith("#")]
    assert all(re.search(r" --hash=sha256:[0-9a-f]{64}", l) for l in reqs)
    names = {re.match(r"([A-Za-z0-9_.-]+)==", l)[1].lower().replace("_", "-") for l in reqs}
    assert re.match(rf"torch=={re.escape(version)}\+rocm7\.2 ", next(l for l in reqs if l.startswith("torch==")))
    assert not (names - {"torch"}) & {p["name"] for p in locked()}     # never a second copy of a locked package
