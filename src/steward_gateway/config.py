"""The gateway's settings (spec 3.4, 8.1, 9.1): where it keeps its files, where it listens (network = "tailscale", or
"compose" inside the Docker image), the models and their prices. gateway.toml in the config dir (/etc/steward-gateway) is optional; prices default to the list current on 2026-10-20 and a
configured model with no price stops start-up."""
from __future__ import annotations

import ipaddress
import os
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

ANSWER_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")
FALLBACK_MODELS = ("claude-opus-5", "claude-opus-4-8")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16_000
MAX_STEPS = 8
PREWARM_EVERY_S = 300
TAILNET = ipaddress.ip_network("100.64.0.0/10")
NETWORKS = ("tailscale", "compose")
CONTAINER_MARKERS = (Path("/.dockerenv"), Path("/run/.containerenv"))
NETWORK_RULE = 'network in gateway.toml must be "tailscale" or "compose".'
NOT_A_CONTAINER = ('network = "compose" is for the gateway\'s Docker image. On a machine of its own, leave it out and '
                   "use this machine's Tailscale address.")
COMPOSE_MCP = "Claude Code (mcp = true) can't reach a gateway in compose. Run the gateway on the machine Claude Code runs on."
HOST_RULE_COMPOSE = ("host in gateway.toml must be 0.0.0.0 in compose (inside its container), this machine's Tailscale "
                     "address (100.64.0.0/10) or 127.0.0.1.")
OLLAMA_RULE_COMPOSE = "ollama_url in gateway.toml must be on this machine or the ollama service, like http://ollama:11434."


class ConfigError(RuntimeError):
    """gateway.toml can't be used. The message says what to change."""


@dataclass(frozen=True)
class Price:
    """Dollars per million tokens. cache_write is the 5-minute write (1.25 × input)."""
    input: Decimal
    output: Decimal
    cache_write: Decimal
    cache_read: Decimal


DEFAULT_PRICES: dict[str, Price] = {
    "claude-opus-5-5": Price(Decimal("4.00"), Decimal("20.00"), Decimal("5.00"), Decimal("0.20")),
    "claude-sonnet-5-5": Price(Decimal("2.00"), Decimal("10.00"), Decimal("2.50"), Decimal("0.20")),
    "claude-opus-5": Price(Decimal("5.00"), Decimal("25.00"), Decimal("6.25"), Decimal("0.50")),
    "claude-opus-4-8": Price(Decimal("5.00"), Decimal("25.00"), Decimal("6.25"), Decimal("0.50")),
}


@dataclass(frozen=True)
class GatewayConfig:
    config_dir: Path
    state_dir: Path
    host: str = "127.0.0.1"
    port: int = 8430
    timezone: str = "America/Los_Angeles"
    default_model: str = "claude-opus-5-5"
    default_cap_cents: int = 1000
    max_cap_cents: int = 10_000
    prices: dict[str, Price] = field(default_factory=lambda: dict(DEFAULT_PRICES))
    anthropic_base_url: str | None = None   # tests only: the fake Anthropic server
    ollama_url: str = "http://127.0.0.1:11434"
    title_model: str = "qwen3.5:9b-q4_K_M"
    categorizer_model: str = "qwen3.5:9b-q4_K_M"
    categorizer_parallel: int = 4
    statement_layout_model: str = "qwen3.5:9b-q4_K_M"
    statement_layout_timeout_s: float = 120.0
    statement_vision_model: str = "gemma4:12b-it-qat"
    statement_page_timeout_s: float = 90.0
    nas_url: str | None = None              # Steward on the NAS, for Claude Code only (ruling 2)
    mcp_port: int = 8431
    mcp: bool = False                       # Claude Code over MCP (release spec 2026-11-05, section 6): off unless set
    network: str = "tailscale"              # "compose" only in the gateway's Docker image (release spec 2026-11-05, section 7)

    @property
    def env_path(self) -> Path:
        return self.config_dir / "gateway.env"

    @property
    def token_path(self) -> Path:
        return self.config_dir / "advisor.token"

    @property
    def history_key_path(self) -> Path:
        return self.config_dir / "history.key"

    @property
    def pending_pair_path(self) -> Path:
        return self.state_dir / "pairing.json"

    @property
    def ledger_path(self) -> Path:
        return self.state_dir / "ledger.db"

    @property
    def stop_flag_path(self) -> Path:
        return self.state_dir / "chat-stopped"

    @property
    def mcp_token_path(self) -> Path:
        return self.config_dir / "mcp.token"

    @property
    def grants_path(self) -> Path:
        return self.config_dir / "mcp-grants.json"


SYSTEM_CONFIG_DIR = Path("/etc/steward-gateway")
SYSTEM_STATE_DIR = Path("/var/lib/steward-gateway")


def _owns(path: Path) -> bool:
    try:
        return path.stat().st_uid == os.getuid()
    except OSError:
        return False


def default_dirs() -> tuple[Path, Path]:
    """Where the gateway keeps its files. STEWARD_GATEWAY_CONFIG_DIR and STEWARD_GATEWAY_STATE_DIR come first (the
    systemd unit sets them). Then the system dirs, when /etc/steward-gateway belongs to the user running this: that is
    the steward-gw account, which `sudo -u steward-gw` starts with a clean environment. Otherwise the XDG dirs, for
    development, unless /etc/steward-gateway exists and belongs to someone else: then this is the wrong user, and a
    command would quietly write a second copy of the grants and token into this user's home, so it refuses."""
    home = Path.home()
    system = _owns(SYSTEM_CONFIG_DIR)
    config = os.environ.get("STEWARD_GATEWAY_CONFIG_DIR")
    state = os.environ.get("STEWARD_GATEWAY_STATE_DIR")
    if not (config and state) and not system and SYSTEM_CONFIG_DIR.exists():
        raise ConfigError("The gateway's files belong to steward-gw. Run: steward-gateway <command> (or sudo -u "
                          "steward-gw /opt/steward-gateway/bin/steward-gateway <command>). For development set "
                          "STEWARD_GATEWAY_CONFIG_DIR.")
    return (
        Path(config) if config else SYSTEM_CONFIG_DIR if system
        else Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "steward-gateway",
        Path(state) if state else SYSTEM_STATE_DIR if system
        else Path(os.environ.get("XDG_STATE_HOME") or home / ".local" / "state") / "steward-gateway",
    )


def load_config(config_dir: Path | None = None, state_dir: Path | None = None) -> GatewayConfig:
    if config_dir is None or state_dir is None:      # explicit dirs never consult (or trip) the wrong-user guard
        default_config, default_state = default_dirs()
        config_dir, state_dir = config_dir or default_config, state_dir or default_state
    path = config_dir / "gateway.toml"
    data = tomllib.loads(path.read_text()) if path.exists() else {}
    prices = dict(DEFAULT_PRICES)
    for model, p in (data.get("prices") or {}).items():
        try:
            prices[model] = Price(*(Decimal(str(p[k])) for k in ("input", "output", "cache_write", "cache_read")))
        except (KeyError, ArithmeticError, TypeError):
            raise ConfigError(f"The price for {model} in gateway.toml needs input, output, cache_write and cache_read.") from None
    mcp = data.get("mcp", False)
    if not isinstance(mcp, bool):
        raise ConfigError("mcp in gateway.toml must be true or false.")
    network = data.get("network", "tailscale")
    if not isinstance(network, str) or network not in NETWORKS:
        raise ConfigError(NETWORK_RULE)
    cfg = GatewayConfig(config_dir, state_dir, host=str(data.get("host", "127.0.0.1")), port=int(data.get("port", 8430)),
                        timezone=str(data.get("timezone", "America/Los_Angeles")),
                        default_model=str(data.get("model", "claude-opus-5-5")),
                        max_cap_cents=int(Decimal(str(data.get("max_cap_dollars", 100))) * 100), prices=prices,
                        ollama_url=str(data.get("ollama_url", "http://127.0.0.1:11434")),
                        title_model=str(data.get("title_model", "qwen3.5:9b-q4_K_M")),
                        categorizer_model=str(data.get("categorizer_model", "qwen3.5:9b-q4_K_M")),
                        categorizer_parallel=int(data.get("categorizer_parallel", 4)),
                        statement_layout_model=str(data.get("statement_layout_model",
                                                            data.get("categorizer_model", "qwen3.5:9b-q4_K_M"))),
                        statement_layout_timeout_s=float(data.get("statement_layout_timeout_s", 120)),
                        statement_vision_model=str(data.get("statement_vision_model", "gemma4:12b-it-qat")),
                        statement_page_timeout_s=float(data.get("statement_page_timeout_s", 90)),
                        nas_url=data.get("nas_url"), mcp_port=int(data.get("mcp_port", 8431)), mcp=mcp,
                        network=network)
    check(cfg)
    return cfg


def check(cfg: GatewayConfig) -> None:
    for model in ANSWER_MODELS + FALLBACK_MODELS:
        if model not in cfg.prices:
            raise ConfigError(f"No price for {model} in gateway.toml.")
    if cfg.default_model not in ANSWER_MODELS:
        raise ConfigError(f"model in gateway.toml must be one of {', '.join(ANSWER_MODELS)}.")
    if not 100 <= cfg.default_cap_cents <= cfg.max_cap_cents:
        raise ConfigError("max_cap_dollars in gateway.toml must be at least the $10 budget.")
    if cfg.network not in NETWORKS:
        raise ConfigError(NETWORK_RULE)
    if cfg.network == "compose":
        if not in_container():
            raise ConfigError(NOT_A_CONTAINER)
        if cfg.mcp:
            raise ConfigError(COMPOSE_MCP)
    check_host(cfg.host, cfg.network)
    check_ollama_url(cfg.ollama_url, cfg.network)
    if not 1 <= cfg.categorizer_parallel <= 8:
        raise ConfigError("categorizer_parallel in gateway.toml must be from 1 to 8, the same as OLLAMA_NUM_PARALLEL.")
    if not 10 <= cfg.statement_layout_timeout_s <= 600:
        raise ConfigError("statement_layout_timeout_s in gateway.toml must be from 10 to 600 seconds.")
    if not 10 <= cfg.statement_page_timeout_s <= 600:
        raise ConfigError("statement_page_timeout_s in gateway.toml must be from 10 to 600 seconds.")
    if cfg.nas_url is not None:
        check_nas_url(cfg.nas_url)
    if cfg.mcp_port == cfg.port or not 1024 <= cfg.mcp_port <= 65535:
        raise ConfigError("mcp_port in gateway.toml must be a free port above 1023 other than the gateway's port.")


def check_nas_url(url: str) -> None:
    u = urlparse(url)
    host = u.hostname or ""
    if u.scheme == "https" and host.endswith(".ts.net"):
        return
    if u.scheme in ("http", "https") and host in ("127.0.0.1", "localhost"):
        return
    try:
        if u.scheme in ("http", "https") and ipaddress.ip_address(host) in TAILNET:
            return
    except ValueError:
        pass
    raise ConfigError("nas_url in gateway.toml must be Steward's address on the tailnet, like "
                      "https://steward.tail1234.ts.net.")


def in_container() -> bool:
    return any(p.exists() for p in CONTAINER_MARKERS)


def check_ollama_url(url: str, network: str = "tailscale") -> None:
    allowed = {"127.0.0.1", "localhost"} | ({"ollama"} if network == "compose" else set())
    if urlparse(url).hostname not in allowed:
        raise ConfigError(OLLAMA_RULE_COMPOSE if network == "compose"
                          else "ollama_url in gateway.toml must be on this machine (127.0.0.1).")


def check_host(host: str, network: str = "tailscale") -> None:
    compose = network == "compose"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise ConfigError(HOST_RULE_COMPOSE if compose else
                          "host in gateway.toml must be this machine's Tailscale address, like 100.101.102.103.") from None
    if not (str(ip) == "127.0.0.1" or (ip.version == 4 and ip in TAILNET) or (compose and str(ip) == "0.0.0.0")):
        raise ConfigError(HOST_RULE_COMPOSE if compose else
                          "host in gateway.toml must be this machine's Tailscale address (100.64.0.0/10) or 127.0.0.1.")
