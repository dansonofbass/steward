"""Release spec 2026-11-05, section 6: STEWARD_KEY_FILE puts the key on its own mount (a Docker secret, say). Unset,
nothing changes. The file must be private to Steward (mode 600 or 400), a file Steward can't write is explained, the key
is never printed but by `steward keygen`, and no backup holds it (claim S2)."""
import logging
import re
import stat

import pytest
from typer.testing import CliRunner

from steward.cli import app
from steward.settings import Settings

runner = CliRunner()


@pytest.fixture
def key_file(settings, tmp_path_factory, monkeypatch):
    """A key path outside the data folder (settings' data folder is tmp_path)."""
    path = tmp_path_factory.mktemp("secrets") / "steward_key"
    monkeypatch.setenv("STEWARD_KEY_FILE", str(path))
    return path


def test_unset_the_key_stays_in_the_data_folder(settings):
    assert settings.key_file is None and settings.key_path == settings.data_dir / "steward.key"


def test_an_empty_setting_is_unset(settings, monkeypatch):
    monkeypatch.setenv("STEWARD_KEY_FILE", "  ")
    assert Settings(_env_file=None).key_file is None


def test_the_key_can_live_on_its_own_mount_and_no_backup_holds_it(settings, key_file, tmp_path_factory, caplog):
    caplog.set_level(logging.DEBUG)
    assert runner.invoke(app, ["init-key"]).exit_code == 0
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert not (settings.data_dir / "steward.key").exists()
    assert runner.invoke(app, ["migrate"]).exit_code == 0
    out = tmp_path_factory.mktemp("backups")
    r = runner.invoke(app, ["backup", "--dir", str(out)])
    assert r.exit_code == 0, r.output
    key = key_file.read_text().strip()
    files = [p for p in out.rglob("*") if p.is_file()]
    assert files                                         # the directory and ours were copied
    for p in files:
        data = p.read_bytes()
        assert key.encode() not in data and bytes.fromhex(key) not in data, p
    assert not any(p.name in (key_file.name, "steward.key") for p in out.rglob("*"))
    assert key not in r.output and key not in caplog.text


def test_the_default_key_stays_out_of_the_backups(settings):
    assert runner.invoke(app, ["init-key"]).exit_code == 0
    assert runner.invoke(app, ["migrate"]).exit_code == 0
    assert runner.invoke(app, ["backup"]).exit_code == 0
    key = settings.key_path.read_text().strip()
    copies = [p for p in settings.backups_dir.rglob("*") if p.is_file()]
    assert copies and all(key.encode() not in p.read_bytes() for p in copies)
    assert not any(p.name == "steward.key" for p in settings.backups_dir.rglob("*"))


@pytest.mark.parametrize("mode", [0o644, 0o444, 0o640])
def test_a_key_file_others_can_read_is_refused(settings, key_file, mode, monkeypatch):
    import uvicorn

    def boom(*a, **k):
        raise AssertionError("uvicorn.run must not be reached")

    monkeypatch.setattr(uvicorn, "run", boom)
    key_file.write_text("ab" * 32 + "\n")
    key_file.chmod(mode)
    for args in (["migrate"], ["init-key"], ["serve"]):
        r = runner.invoke(app, args)
        assert r.exit_code == 1, args
        said = r.output.replace("\n", " ")
        assert f"The key file {key_file} can be read by others (mode {mode:o}). Run: chmod 600 {key_file}" in said, args
        assert "ab" * 32 not in r.output


def test_mode_400_and_a_link_to_a_private_file_are_fine(settings, key_file, tmp_path_factory):
    real = tmp_path_factory.mktemp("real") / "k"
    real.write_text("cd" * 32 + "\n")
    real.chmod(0o400)
    key_file.symlink_to(real)                          # a Kubernetes secret is a link; the file's own mode counts
    r = runner.invoke(app, ["migrate"])
    assert r.exit_code == 0, r.output


def test_a_key_file_steward_cannot_write_is_explained(settings, monkeypatch, tmp_path_factory):
    blocker = tmp_path_factory.mktemp("ro") / "not-a-folder"
    blocker.write_text("")
    path = blocker / "steward_key"                     # its folder is a file, so nothing can be made there, even as root
    monkeypatch.setenv("STEWARD_KEY_FILE", str(path))
    r = runner.invoke(app, ["init-key"])
    assert r.exit_code == 1
    said = r.output.replace("\n", " ")
    assert f"STEWARD_KEY_FILE is {path}, and Steward can't write there. Run `steward keygen`" in said


def test_a_missing_key_file_says_how_to_make_one(settings, key_file):
    r = runner.invoke(app, ["migrate"])
    assert r.exit_code == 1 and "Run `steward keygen` and save its line there (mode 600)." in r.output.replace("\n", " ")


def test_keygen_prints_a_new_key_and_writes_nothing(settings):
    a, b = runner.invoke(app, ["keygen"]), runner.invoke(app, ["keygen"])
    assert a.exit_code == b.exit_code == 0
    ka, kb = a.output.strip(), b.output.strip()
    assert re.fullmatch(r"[0-9a-f]{64}", ka) and re.fullmatch(r"[0-9a-f]{64}", kb) and ka != kb
    assert not settings.key_path.exists()
