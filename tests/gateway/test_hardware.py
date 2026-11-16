"""Detection (PR 13b): read-only, on a fake root with fake command answers; the script runs the same table."""
import os

import pytest
from typer.testing import CliRunner

from steward_gateway import accelerator, cli, hardware as H
from tests.gateway.hardware_scenarios import SCENARIOS, build


def fake(s):
    return (lambda args: (s.commands[args[0]][1] if s.commands[args[0]][0] == 0 else None)), (lambda c: c in s.commands)


@pytest.mark.parametrize("s", SCENARIOS, ids=lambda s: s.id)
def test_each_machine_gets_its_found_lines_and_one_next_step(tmp_path, monkeypatch, s):
    root = build(tmp_path, s)
    run, have = fake(s)
    if s.commands.get("stat", (0, ""))[0]:                       # the scenario's group lookup fails
        monkeypatch.setattr(H, "_group", lambda path: None)
    gid = os.stat(root / "dev" / "kfd").st_gid if (root / "dev" / "kfd").exists() else None
    assert H.report(H.probe(root, run, have)) == [line.format(gid=gid) for line in s.lines]


def test_a_group_that_cant_be_read_is_none_not_a_traceback(tmp_path):
    assert H._group(tmp_path / "dev" / "kfd") is None
    (tmp_path / "kfd").write_text("")
    assert H._group(tmp_path / "kfd") == os.stat(tmp_path / "kfd").st_gid


def test_probing_only_asks_the_three_read_only_commands(tmp_path):
    s = next(s for s in SCENARIOS if s.id == "nvidia-with-toolkit")
    asked = []
    run, have = fake(s)
    H.probe(build(tmp_path, s), lambda args: asked.append(list(args)) or run(args), have)
    assert asked == [["nvidia-smi", "-L"], ["docker", "info", "--format", "{{json .Runtimes}}"]]


def test_a_command_that_hangs_or_is_missing_counts_as_not_found(monkeypatch):
    import subprocess

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("nvidia-smi", 5)
    monkeypatch.setattr(H.subprocess, "run", boom)
    assert H.run_command(["nvidia-smi", "-L"]) is None
    monkeypatch.setattr(H.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    assert H.run_command(["rocminfo"]) is None


def test_undecodable_output_is_replaced_not_a_traceback():
    import sys
    out = H.run_command([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'GPU 0: a\\xff (UUID: x)')"])
    assert out is not None and out.startswith("GPU 0: a")


def test_nvidia_smi_that_answers_without_a_gpu_line_falls_back_to_the_device_nodes(tmp_path):
    (tmp_path / "dev").mkdir()
    (tmp_path / "dev" / "nvidia0").write_text("")
    hw = H.probe(tmp_path, lambda args: "NVIDIA-SMI has failed\n", lambda c: c == "nvidia-smi")
    assert hw.nvidia == ""


def test_the_command_says_what_this_gateway_runs_on_first(monkeypatch):
    monkeypatch.setattr(accelerator, "available", lambda: "cuda")
    monkeypatch.setattr(H, "probe", lambda *a, **k: H.Hardware("", None, None, None, None, None))
    r = CliRunner().invoke(cli.app, ["hardware"])
    assert r.exit_code == 0 and r.output.splitlines() == [
        "This gateway runs on: cuda", "Found: NVIDIA GPU", 'Next: docs/guides/gpu.md, "NVIDIA".']
