import os

import pytest

from steward_gateway.secrets import SecretFileError, api_key, read_env_file, read_private, write_private


def test_a_private_env_file_is_read(gw_cfg):
    write_private(gw_cfg.env_path, "# Steward gateway\nANTHROPIC_API_KEY=test-key-not-real\n")
    assert oct(gw_cfg.env_path.stat().st_mode & 0o777) == "0o600"
    assert read_env_file(gw_cfg.env_path) == {"ANTHROPIC_API_KEY": "test-key-not-real"}
    assert api_key(gw_cfg) == "test-key-not-real"


def test_no_env_file_means_no_key(gw_cfg):
    assert api_key(gw_cfg) is None


def test_an_env_file_others_can_read_is_refused(gw_cfg):
    gw_cfg.env_path.write_text("ANTHROPIC_API_KEY=test-key-not-real\n")
    os.chmod(gw_cfg.env_path, 0o644)
    with pytest.raises(SecretFileError, match="chmod 600"):
        api_key(gw_cfg)


def test_private_text_round_trips(gw_cfg):
    write_private(gw_cfg.token_path, "ab" * 32)
    assert read_private(gw_cfg.token_path) == "ab" * 32
    assert read_private(gw_cfg.config_dir / "missing") is None
