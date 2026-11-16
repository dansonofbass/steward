"""web/e2e/vault_keeper.py (flaky-test audit E2): it puts the seeded demo vault back between e2e specs, and it works
only on a vault web/e2e/server.sh made."""
import importlib.util
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("vault_keeper", ROOT / "web" / "e2e" / "vault_keeper.py")
vk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vk)


def made_by_server_sh(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "books").mkdir(parents=True)
    (data / vk.MARKER).write_text("")
    (data / "directory.db").write_bytes(b"people")
    (data / "books" / "ours.db").write_bytes(b"seeded")
    return data


def test_restore_puts_the_seeded_vault_back_and_nothing_else(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_ENV", "test")
    data, snap = made_by_server_sh(tmp_path), tmp_path / "snap"
    snap.mkdir()
    vk.snapshot(data, snap)
    (data / "books" / "ours.db").write_bytes(b"a spec sorted the review queue")
    (data / "books" / "mom-test-phone.db").write_bytes(b"a book a spec made")
    (data / "directory.db-wal").write_bytes(b"a session")
    (data / "steward.key").write_bytes(b"key")                 # outside the vault: left alone
    (data / "gateway-state").mkdir()
    (data / "gateway-state" / "ledger.db").write_bytes(b"the fake gateway's")
    vk.restore(data, snap)
    assert (data / "books" / "ours.db").read_bytes() == b"seeded"
    assert sorted(p.name for p in (data / "books").iterdir()) == ["ours.db"]
    assert (data / "directory.db").read_bytes() == b"people" and not (data / "directory.db-wal").exists()
    assert (data / "steward.key").read_bytes() == b"key"
    assert (data / "gateway-state" / "ledger.db").read_bytes() == b"the fake gateway's"


@pytest.mark.parametrize("env, marker", [("test", False), ("prod", True), (None, True)])
def test_it_refuses_a_vault_server_sh_did_not_make(tmp_path, monkeypatch, env, marker):
    data, snap = made_by_server_sh(tmp_path), tmp_path / "snap"
    snap.mkdir()
    if not marker:
        (data / vk.MARKER).unlink()
    if env is None:
        monkeypatch.delenv("STEWARD_ENV", raising=False)
    else:
        monkeypatch.setenv("STEWARD_ENV", env)
    with pytest.raises(SystemExit):
        vk.restore(data, snap)
    with pytest.raises(SystemExit):
        vk.snapshot(data, snap)
    assert (data / "books" / "ours.db").read_bytes() == b"seeded"


PACIFIC = ZoneInfo("America/Los_Angeles")


def fake_seeds(monkeypatch, seeded: list) -> None:
    """Stands in for server.sh's seed scripts: each dates the vault with the household's day, as deps.today() does."""
    def seed_vault(data: Path) -> None:
        assert not (data / "books").exists(), "the old vault is cleared before seeding"
        (data / "books").mkdir()
        day = vk.clock.today()
        (data / "books" / "ours.db").write_text(f"seeded {day}")
        (data / "directory.db").write_text("people")
        seeded.append(day.isoformat())
    monkeypatch.setattr(vk, "run_seeds", seed_vault)


def fresh_vault(tmp_path: Path) -> tuple[Path, Path]:
    data, snap = tmp_path / "data", tmp_path / "snap"
    data.mkdir()
    snap.mkdir()
    (data / vk.MARKER).write_text("")
    return data, snap


def test_a_restore_on_a_later_day_seeds_the_vault_afresh(tmp_path, monkeypatch, fake_clock):
    """The month-boundary flake: seeded on Oct 31, Spending's specs ran on Nov 1 against Oct 31's rows. A restore
    on another household day than the seed's seeds again, so every date-relative seed matches the server's day."""
    monkeypatch.setenv("STEWARD_ENV", "test")
    seeded: list[str] = []
    fake_seeds(monkeypatch, seeded)
    data, snap = fresh_vault(tmp_path)
    fake_clock.set(datetime(2026, 10, 31, 23, 58, tzinfo=PACIFIC))
    vk.seed(data, snap)
    (data / "books" / "ours.db").write_text("a spec sorted the review queue")
    fake_clock.set(datetime(2026, 10, 31, 23, 59, 59, tzinfo=PACIFIC))
    vk.restore(data, snap)
    assert (data / "books" / "ours.db").read_text() == "seeded 2026-10-31"
    fake_clock.set(datetime(2026, 11, 1, 0, 0, 1, tzinfo=PACIFIC))
    vk.restore(data, snap)
    assert (data / "books" / "ours.db").read_text() == "seeded 2026-11-01"
    (data / "books" / "ours.db").write_text("Spending's spec saved a target")
    vk.restore(data, snap)                            # the next spec, the same day: the new snapshot, no new seed
    assert (data / "books" / "ours.db").read_text() == "seeded 2026-11-01"
    assert seeded == ["2026-10-31", "2026-11-01"]


def test_a_seed_that_runs_past_midnight_counts_as_the_day_it_began(tmp_path, monkeypatch, fake_clock):
    """Some seed scripts dated their rows Oct 31 and some Nov 1: the first restore seeds again."""
    monkeypatch.setenv("STEWARD_ENV", "test")
    seeded: list[str] = []
    fake_seeds(monkeypatch, seeded)
    real = vk.run_seeds

    def slow(data: Path) -> None:
        real(data)
        fake_clock.set(datetime(2026, 11, 1, 0, 0, 5, tzinfo=PACIFIC))
    monkeypatch.setattr(vk, "run_seeds", slow)
    data, snap = fresh_vault(tmp_path)
    fake_clock.set(datetime(2026, 10, 31, 23, 59, 59, tzinfo=PACIFIC))
    vk.seed(data, snap)
    vk.restore(data, snap)
    assert seeded == ["2026-10-31", "2026-11-01"]


def test_the_seed_list_is_server_sh_s():
    """One list: server.sh seeds through the keeper, so a reseed runs exactly what the first seed ran."""
    script = (ROOT / "web" / "e2e" / "server.sh").read_text()
    assert "vault_keeper.py seed " in script and "seed_spending.py" not in script
    names = [c[-1] for c in vk.SEEDS]
    for s in ("seed-demo", "web/e2e/seed_extra.py", "web/e2e/seed_spending.py", "web/e2e/seed_setasides.py",
              "web/e2e/seed_reimburse.py", "web/e2e/seed_chat.py", "web/e2e/seed_same_account.py",
              "web/e2e/seed_notes.py", "web/e2e/seed_home.py", "web/e2e/seed_single.py"):
        assert s in names
    assert vk.SEEDS[0][-1] == "migrate"
