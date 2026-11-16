"""The e2e demo vault's keeper (web/e2e/server.sh; flaky-test audit E2). Every spec on the demo vault starts from the
household server.sh seeded. `seed` seeds the vault and copies it aside before the server first starts. `serve` runs
`steward serve` with a small control port beside it, where POST /restore stops the server, puts the snapshot back and
starts it again. The seeds date their rows from the household's day, and the specs ask the server for "this month" at
test time, so a restore on a later day than the seed's seeds the vault afresh first (the Oct 31 to Nov 1 flake). The
keeper touches only a vault server.sh made: a folder holding its .e2e-vault marker, with STEWARD_ENV=test. Test-only:
nothing in the app imports it."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from steward import clock

MARKER = ".e2e-vault"
# What a spec can change: the directory (people, sessions, the list of books) and every book. The key, the advisor
# token and the fake gateway's state stay as they are.
VAULT_FILES = ("directory.db", "directory.db-wal", "directory.db-shm", "steward.db", "steward.db-wal", "steward.db-shm")
VAULT_DIRS = ("books",)
HEALTH_CEILING_S = 60
ROOT = Path(__file__).resolve().parents[2]
SEEDED_DAY = "seeded-day"       # in the snapshot folder: the household day the seed began on
# The demo household, in order. Each runs from the repository root with STEWARD_DATA_DIR at the vault.
SEEDS = (
    ("uv", "run", "steward", "migrate"),
    ("uv", "run", "steward", "seed-demo"),
    ("uv", "run", "python", "web/e2e/seed_extra.py"),
    ("uv", "run", "python", "web/e2e/seed_spending.py"),
    ("uv", "run", "python", "web/e2e/seed_setasides.py"),
    ("uv", "run", "python", "web/e2e/seed_reimburse.py"),
    ("uv", "run", "python", "web/e2e/seed_chat.py"),
    ("uv", "run", "python", "web/e2e/seed_same_account.py"),
    ("uv", "run", "python", "web/e2e/seed_notes.py"),
    ("uv", "run", "python", "web/e2e/seed_home.py"),
    ("uv", "run", "python", "web/e2e/seed_single.py"),
    ("uv", "run", "python", "web/e2e/seed_welcomed.py"),
)


def check_vault(data: Path) -> None:
    if os.environ.get("STEWARD_ENV") != "test":
        raise SystemExit("vault_keeper: STEWARD_ENV is not test; refusing to touch a vault")
    if not (data / MARKER).is_file():
        raise SystemExit(f"vault_keeper: {data} has no {MARKER} marker, so server.sh didn't make it; refusing")


def _copy_vault(src: Path, dest: Path) -> None:
    for name in VAULT_FILES:
        if (src / name).exists():
            shutil.copy2(src / name, dest / name)
    for name in VAULT_DIRS:
        if (src / name).exists():
            shutil.copytree(src / name, dest / name)


def _clear_vault(folder: Path) -> None:
    for name in VAULT_FILES:
        (folder / name).unlink(missing_ok=True)
    for name in VAULT_DIRS:
        shutil.rmtree(folder / name, ignore_errors=True)


def snapshot(data: Path, snap: Path, day: str | None = None) -> None:
    """Copies the seeded vault aside, with the household day it was seeded on. Nothing may hold its databases open."""
    check_vault(data)
    _clear_vault(snap)
    _copy_vault(data, snap)
    (snap / SEEDED_DAY).write_text(day or clock.today().isoformat())


def run_seeds(data: Path) -> None:
    env = {**os.environ, "STEWARD_DATA_DIR": str(data), "PYTHONPATH": str(ROOT)}
    for cmd in SEEDS:
        subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def seed(data: Path, snap: Path) -> None:
    """Seeds an empty vault (the key made) and snapshots it. The day is read before the first seed, so a seed that runs
    past midnight counts as the day it began, and the next restore seeds again."""
    check_vault(data)
    day = clock.today().isoformat()
    _clear_vault(data)
    run_seeds(data)
    snapshot(data, snap, day)


def restore(data: Path, snap: Path) -> None:
    """Puts the snapshot back, or seeds afresh when the household's day is no longer the seed's. The server must be
    stopped: nothing may hold the databases open."""
    check_vault(data)
    seeded = snap / SEEDED_DAY
    if seeded.is_file() and seeded.read_text() != clock.today().isoformat():
        seed(data, snap)
        return
    _clear_vault(data)
    _copy_vault(snap, data)


class Keeper:
    def __init__(self, data: Path, snap: Path, app_port: int):
        self.data, self.snap, self.app_port = data, snap, app_port
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.proc = subprocess.Popen(["uv", "run", "steward", "serve"])
        if not self._healthy():
            self.stop()
            raise RuntimeError("steward serve didn't answer /api/health")

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=HEALTH_CEILING_S)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc = None

    def restore(self) -> None:
        self.stop()
        restore(self.data, self.snap)
        self.start()

    def _healthy(self) -> bool:
        """Until /api/health answers, failing after HEALTH_CEILING_S or when the server exits: a condition wait."""
        deadline = time.monotonic() + HEALTH_CEILING_S
        while time.monotonic() < deadline:
            if self.proc is None or self.proc.poll() is not None:
                return False
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.app_port}/api/health", timeout=2) as r:
                    if r.status == 200:
                        return True
            except OSError:
                pass
            time.sleep(0.1)
        return False


def serve(data: Path, snap: Path, app_port: int, control_port: int) -> None:
    check_vault(data)
    keeper = Keeper(data, snap, app_port)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/restore":
                self.send_error(404)
                return
            try:
                keeper.restore()
            except Exception as e:  # noqa: BLE001 - the spec's beforeAll reports it
                self.send_error(500, type(e).__name__)
                return
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    # Bind the control port and install the handlers before the server starts: Playwright is ready when uvicorn
    # says it listens, which is before this keeper has polled /api/health, and an early /restore waits in the backlog.
    httpd = HTTPServer(("127.0.0.1", control_port), Handler)

    def bye(*_):
        keeper.stop()
        sys.exit(0)
    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    keeper.start()
    httpd.serve_forever()


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "seed":
        seed(Path(args[0]), Path(args[1]))
    elif cmd == "serve":
        serve(Path(args[0]), Path(args[1]), int(args[2]), int(args[3]))
    else:
        raise SystemExit(f"vault_keeper: unknown command {cmd}")
