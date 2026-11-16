from decimal import Decimal

import pytest

from steward_gateway.config import ConfigError, GatewayConfig, check, check_host, load_config


def test_defaults_price_every_model_and_listen_on_localhost(tmp_path):
    cfg = load_config(tmp_path / "c", tmp_path / "s")
    assert (cfg.host, cfg.port, cfg.default_model, cfg.default_cap_cents, cfg.max_cap_cents) == (
        "127.0.0.1", 8430, "claude-opus-5-5", 1000, 10_000)
    assert cfg.prices["claude-opus-5-5"].input == Decimal("4.00")
    assert cfg.prices["claude-opus-5-5"].cache_read == Decimal("0.20")
    assert cfg.prices["claude-sonnet-5-5"].output == Decimal("10.00")


def test_the_toml_file_sets_host_cap_and_prices(tmp_path):
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "gateway.toml").write_text(
        'host = "100.101.102.103"\nmax_cap_dollars = 50\n[prices."claude-opus-5-5"]\n'
        'input = "4.50"\noutput = "21"\ncache_write = "5.625"\ncache_read = "0.25"\n')
    cfg = load_config(tmp_path / "c", tmp_path / "s")
    assert cfg.host == "100.101.102.103" and cfg.max_cap_cents == 5000
    assert cfg.prices["claude-opus-5-5"].output == Decimal("21")


def test_a_configured_model_without_a_price_is_refused(tmp_path):
    cfg = GatewayConfig(tmp_path, tmp_path, prices={"claude-opus-5-5": GatewayConfig(tmp_path, tmp_path).prices["claude-opus-5-5"]})
    with pytest.raises(ConfigError, match="No price for claude-sonnet-5-5"):
        check(cfg)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "gateway-box", "::"])
def test_only_localhost_or_a_tailscale_address(host):
    with pytest.raises(ConfigError):
        check_host(host)


def test_tailscale_and_localhost_are_fine():
    check_host("127.0.0.1")
    check_host("100.64.0.1")
    check_host("100.127.255.254")


def test_paths(tmp_path):
    cfg = GatewayConfig(tmp_path / "c", tmp_path / "s")
    assert cfg.env_path.name == "gateway.env" and cfg.env_path.parent == tmp_path / "c"
    assert cfg.token_path.name == "advisor.token" and cfg.history_key_path.name == "history.key"
    assert cfg.ledger_path.parent == tmp_path / "s" and cfg.stop_flag_path.name == "chat-stopped"


def test_categorizer_settings_load_and_are_checked(tmp_path):
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "gateway.toml").write_text('categorizer_model = "llama3.1:8b"\ncategorizer_parallel = 2\n')
    cfg = load_config(tmp_path / "c", tmp_path / "s")
    assert (cfg.categorizer_model, cfg.categorizer_parallel) == ("llama3.1:8b", 2)
    assert GatewayConfig(tmp_path, tmp_path).categorizer_model == "qwen3.5:9b-q4_K_M"
    with pytest.raises(ConfigError, match="categorizer_parallel"):
        check(GatewayConfig(tmp_path, tmp_path, categorizer_parallel=0))


def test_nas_url_and_mcp_port(tmp_path):
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "gateway.toml").write_text('nas_url = "https://steward.tail1234.ts.net"\nmcp_port = 8432\n')
    cfg = load_config(tmp_path / "c", tmp_path / "s")
    assert (cfg.nas_url, cfg.mcp_port) == ("https://steward.tail1234.ts.net", 8432)
    assert cfg.grants_path.name == "mcp-grants.json" and cfg.mcp_token_path.name == "mcp.token"
    for bad in ("https://example.com", "http://steward.tail1234.ts.net", "ftp://100.64.0.9"):
        with pytest.raises(ConfigError, match="nas_url"):
            check(GatewayConfig(tmp_path, tmp_path, nas_url=bad))
    check(GatewayConfig(tmp_path, tmp_path, nas_url="http://127.0.0.1:8420"))      # tests and the eval rig
    check(GatewayConfig(tmp_path, tmp_path, nas_url="https://100.88.1.2"))
    with pytest.raises(ConfigError, match="mcp_port"):
        check(GatewayConfig(tmp_path, tmp_path, mcp_port=8430))


def _no_gateway_env(monkeypatch, tmp_path):
    from steward_gateway import config
    for name in ("STEWARD_GATEWAY_CONFIG_DIR", "STEWARD_GATEWAY_STATE_DIR", "XDG_CONFIG_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "SYSTEM_CONFIG_DIR", tmp_path / "missing-etc")
    monkeypatch.setattr(config, "SYSTEM_STATE_DIR", tmp_path / "missing-var")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def test_the_units_dirs_come_first(monkeypatch, tmp_path):
    from steward_gateway.config import default_dirs
    _no_gateway_env(monkeypatch, tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("STEWARD_GATEWAY_CONFIG_DIR", str(tmp_path / "etc"))
    monkeypatch.setenv("STEWARD_GATEWAY_STATE_DIR", str(tmp_path / "var"))
    assert default_dirs() == (tmp_path / "etc", tmp_path / "var")


def test_each_dir_falls_back_to_xdg_on_its_own(monkeypatch, tmp_path):
    from steward_gateway.config import default_dirs
    _no_gateway_env(monkeypatch, tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    assert default_dirs() == (tmp_path / "xdg-config" / "steward-gateway", tmp_path / "xdg-state" / "steward-gateway")
    monkeypatch.setenv("STEWARD_GATEWAY_STATE_DIR", str(tmp_path / "var"))
    assert default_dirs() == (tmp_path / "xdg-config" / "steward-gateway", tmp_path / "var")


def test_without_xdg_it_uses_the_home_dirs(monkeypatch, tmp_path):
    from steward_gateway.config import default_dirs
    _no_gateway_env(monkeypatch, tmp_path)
    home = tmp_path / "home"
    assert default_dirs() == (home / ".config" / "steward-gateway", home / ".local" / "state" / "steward-gateway")


def test_the_account_that_owns_the_system_dirs_finds_them_without_env(monkeypatch, tmp_path):
    """`sudo -u steward-gw /opt/steward-gateway/bin/steward-gateway …` starts with a clean environment."""
    from steward_gateway import config
    _no_gateway_env(monkeypatch, tmp_path)
    (tmp_path / "etc").mkdir()
    monkeypatch.setattr(config, "SYSTEM_CONFIG_DIR", tmp_path / "etc")
    monkeypatch.setattr(config, "SYSTEM_STATE_DIR", tmp_path / "var")
    assert config.default_dirs() == (tmp_path / "etc", tmp_path / "var")
    monkeypatch.setattr(config.os, "getuid", lambda: (tmp_path / "etc").stat().st_uid + 1)   # someone else's
    with pytest.raises(config.ConfigError, match="belong to steward-gw"):
        config.default_dirs()


def test_env_dirs_still_win_for_another_user(monkeypatch, tmp_path):
    from steward_gateway import config
    _no_gateway_env(monkeypatch, tmp_path)
    (tmp_path / "etc").mkdir()
    monkeypatch.setattr(config, "SYSTEM_CONFIG_DIR", tmp_path / "etc")
    monkeypatch.setattr(config.os, "getuid", lambda: (tmp_path / "etc").stat().st_uid + 1)   # someone else's
    monkeypatch.setenv("STEWARD_GATEWAY_CONFIG_DIR", str(tmp_path / "dev-etc"))
    monkeypatch.setenv("STEWARD_GATEWAY_STATE_DIR", str(tmp_path / "dev-var"))
    assert config.default_dirs() == (tmp_path / "dev-etc", tmp_path / "dev-var")
    monkeypatch.delenv("STEWARD_GATEWAY_STATE_DIR")      # one set, the other falls back: same rule for the fallback
    with pytest.raises(config.ConfigError):
        config.default_dirs()


def test_explicit_dirs_work_while_the_system_dir_belongs_to_another_user(monkeypatch, tmp_path):
    """deploy.sh runs the tests as the deploying user after creating /etc/steward-gateway for steward-gw."""
    from steward_gateway import config
    _no_gateway_env(monkeypatch, tmp_path)
    (tmp_path / "etc").mkdir()
    monkeypatch.setattr(config, "SYSTEM_CONFIG_DIR", tmp_path / "etc")
    monkeypatch.setattr(config.os, "getuid", lambda: (tmp_path / "etc").stat().st_uid + 1)   # someone else's
    cfg = config.load_config(tmp_path / "c", tmp_path / "s")
    assert (cfg.config_dir, cfg.state_dir) == (tmp_path / "c", tmp_path / "s")
    with pytest.raises(config.ConfigError, match="belong to steward-gw"):
        config.load_config(tmp_path / "c")


COMPOSE = 'network = "compose"\nhost = "0.0.0.0"\nollama_url = "http://ollama:11434"\n'


@pytest.fixture
def in_container(monkeypatch, tmp_path):
    from steward_gateway import config
    marker = tmp_path / ".dockerenv"
    marker.touch()
    monkeypatch.setattr(config, "CONTAINER_MARKERS", (marker,))


@pytest.fixture
def on_a_host(monkeypatch, tmp_path):
    from steward_gateway import config
    monkeypatch.setattr(config, "CONTAINER_MARKERS", (tmp_path / "no-dockerenv", tmp_path / "no-containerenv"))


def _toml(tmp_path, text):
    (tmp_path / "c").mkdir(exist_ok=True)
    (tmp_path / "c" / "gateway.toml").write_text(text)
    return tmp_path / "c", tmp_path / "s"


def test_the_default_network_is_tailscale(tmp_path, on_a_host):
    assert load_config(tmp_path / "c", tmp_path / "s").network == "tailscale"


def test_compose_mode_is_opt_in_and_only_inside_a_container(tmp_path, monkeypatch):
    from steward_gateway import config
    dirs = _toml(tmp_path, COMPOSE)
    monkeypatch.setattr(config, "CONTAINER_MARKERS", (tmp_path / "no-dockerenv",))
    with pytest.raises(ConfigError) as e:
        load_config(*dirs)
    assert str(e.value) == ('network = "compose" is for the gateway\'s Docker image. On a machine of its own, leave '
                            "it out and use this machine's Tailscale address.")
    (tmp_path / ".containerenv").touch()                                      # Podman's marker counts too
    monkeypatch.setattr(config, "CONTAINER_MARKERS", (tmp_path / "no-dockerenv", tmp_path / ".containerenv"))
    cfg = load_config(*dirs)
    assert (cfg.network, cfg.host, cfg.ollama_url) == ("compose", "0.0.0.0", "http://ollama:11434")


@pytest.mark.parametrize("value", ['"Compose"', '"lan"', '""', "true", "1"])
def test_network_must_be_tailscale_or_compose(tmp_path, in_container, value):
    with pytest.raises(ConfigError) as e:
        load_config(*_toml(tmp_path, f"network = {value}\n"))
    assert str(e.value) == 'network in gateway.toml must be "tailscale" or "compose".'


@pytest.mark.parametrize("host", ["192.168.1.10", "10.0.0.5", "172.17.0.2", "gateway-box", "::", "0.0.0.1"])
def test_compose_mode_adds_only_the_containers_own_address(host):
    with pytest.raises(ConfigError) as e:
        check_host(host, "compose")
    if host != "gateway-box":
        assert str(e.value) == ("host in gateway.toml must be 0.0.0.0 in compose (inside its container), this "
                                "machine's Tailscale address (100.64.0.0/10) or 127.0.0.1.")
    for ok in ("0.0.0.0", "127.0.0.1", "100.64.0.1"):
        check_host(ok, "compose")


@pytest.mark.parametrize("url", ["http://ollama.example.com:11434", "http://ollama-box:11434",
                                 "http://192.0.2.20:11434", "http://gateway:11434"])
def test_compose_mode_adds_only_the_ollama_service(tmp_path, in_container, url):
    with pytest.raises(ConfigError) as e:
        check(GatewayConfig(tmp_path, tmp_path, network="compose", host="0.0.0.0", ollama_url=url))
    assert str(e.value) == "ollama_url in gateway.toml must be on this machine or the ollama service, like http://ollama:11434."
    for ok in ("http://ollama:11434", "http://127.0.0.1:11434", "http://localhost:11434"):
        check(GatewayConfig(tmp_path, tmp_path, network="compose", host="0.0.0.0", ollama_url=ok))


def test_compose_mode_refuses_claude_code(tmp_path, in_container):
    with pytest.raises(ConfigError) as e:
        check(GatewayConfig(tmp_path, tmp_path, network="compose", host="0.0.0.0", mcp=True))
    assert str(e.value) == ("Claude Code (mcp = true) can't reach a gateway in compose. Run the gateway on the machine "
                            "Claude Code runs on.")
