import pytest

from steward_gateway.config import GatewayConfig


@pytest.fixture
def gw_cfg(tmp_path) -> GatewayConfig:
    """A gateway config under tmp_path: its own config and state folders, never ~/.config."""
    cfg = GatewayConfig(config_dir=tmp_path / "config", state_dir=tmp_path / "state")
    cfg.config_dir.mkdir(mode=0o700)
    cfg.state_dir.mkdir(mode=0o700)
    return cfg
