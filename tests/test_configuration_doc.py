"""docs/reference/configuration.md against the code (release spec 2026-11-05, section 8; guided setup spec 1.3)."""
import ast
import re
from dataclasses import fields

from pydantic_core import PydanticUndefined

from steward import app_settings
from steward.settings import Settings
from steward_gateway.config import GatewayConfig
from tests.public_docs import ROOT, public_docs, section

DOC = ROOT / "docs" / "reference" / "configuration.md"
STEWARD, OTHER = "## Steward's settings", "## Set outside Steward's settings"
GATEWAY, GATEWAY_ENV = "## gateway.toml", "## The gateway's environment"
ROW = re.compile(r"^\| `([^`]+)` \|(.*)\|\s*$")
CODE = re.compile(r"`([^`]+)`")
VAR = re.compile(r"\bSTEWARD_[A-Z0-9_]*[A-Z0-9]\b")
GENERIC = ("deploy/.env.example", "deploy/compose.yml", "deploy/compose.demo.yml", "deploy/proxy/proxy.env.example",
           "deploy/tailscale/tailscale.env.example")
# Files outside src/ and GENERIC that read a gateway setting (the gateway image's own config and Dockerfile).
GATEWAY_FILES = ("deploy/gateway/gateway.toml", "deploy/gateway/Dockerfile")
READABLE = (".py", ".sh", ".yml", ".json", ".example", ".toml")
DEV = {"STEWARD_E2E_BASE_PORT", "STEWARD_PERF_FACTOR", "STEWARD_PERF_BASE_URL"}   # CONTRIBUTING's; README too, until Task 11
TOML = {"host": "host", "port": "port", "timezone": "timezone", "default_model": "model",
        "max_cap_cents": "max_cap_dollars", "prices": "prices", "ollama_url": "ollama_url", "title_model": "title_model",
        "categorizer_model": "categorizer_model", "categorizer_parallel": "categorizer_parallel",
        "statement_layout_model": "statement_layout_model", "statement_layout_timeout_s": "statement_layout_timeout_s",
        "statement_vision_model": "statement_vision_model", "statement_page_timeout_s": "statement_page_timeout_s",
        "nas_url": "nas_url", "mcp_port": "mcp_port", "mcp": "mcp", "network": "network"}
ENV = {"config_dir": "STEWARD_GATEWAY_CONFIG_DIR", "state_dir": "STEWARD_GATEWAY_STATE_DIR"}
NOT_SET = {"default_cap_cents": "the $10 starting budget", "anthropic_base_url": "tests only: the fake Anthropic server"}


def table(heading: str) -> dict[str, list[str]]:
    """The rows under heading until the next ## heading: {first cell's name: the other cells}. A name twice fails."""
    rows: dict[str, list[str]] = {}
    for line in section(DOC, heading).splitlines():
        m = ROW.match(line)
        if m:
            assert m[1] not in rows, f"{heading}: {m[1]} has two rows"
            rows[m[1]] = [c.strip() for c in m[2].split("|")]
    return rows


def toml_keys() -> set[str]:
    """Every data.get("<key>") in steward_gateway/config.py's load_config, prices included."""
    source = (ROOT / "src" / "steward_gateway" / "config.py").read_text(encoding="utf-8")
    load = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == "load_config")
    return {n.args[0].value for n in ast.walk(load)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get"
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "data"
            and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)}


def test_every_setting_has_one_row_and_every_row_is_a_setting():
    assert set(table(STEWARD)) == {f"STEWARD_{f.upper()}" for f in Settings.model_fields}


def test_each_default_is_the_codes():
    """A required field says "required". A bool (`true`/`false`, checked before int), number (by float) or non-empty
    string default is the first `…` in its Default cell. None, "" and Path defaults are prose."""
    rows = table(STEWARD)
    for name, info in Settings.model_fields.items():
        cells = rows[f"STEWARD_{name.upper()}"]
        shown, default = cells[0], info.default
        if default is PydanticUndefined:
            assert shown == "required", f"STEWARD_{name.upper()}: the default cell says {shown!r}, not 'required'"
            continue
        if default is None or default == "" or not isinstance(default, (bool, int, float, str)):
            continue    # None, "" and Path defaults are prose
        code = CODE.search(shown)
        assert code, f"STEWARD_{name.upper()}: the default cell has no `value` for {default!r}"
        if isinstance(default, bool):
            assert code[1] == ("true" if default else "false"), f"STEWARD_{name.upper()}: {code[1]!r} is not {default}"
        elif isinstance(default, (int, float)):
            assert float(code[1]) == float(default), f"STEWARD_{name.upper()}: {code[1]!r} is not {default}"
        else:
            assert code[1] == default, f"STEWARD_{name.upper()}: {code[1]!r} is not {default!r}"


def test_the_app_stored_settings_say_so():
    rows = table(STEWARD)
    assert {n for n, c in rows.items() if c[1] == "Get Steward ready"} == {s.env for s in app_settings.KEYS.values()}
    assert all(c[1] in ("", "Get Steward ready") for c in rows.values())


def test_every_gateway_toml_key_has_one_row():
    assert set(table(GATEWAY)) == toml_keys()


def test_every_gateway_config_field_is_documented_or_named_here():
    assert {f.name for f in fields(GatewayConfig)} == set(TOML) | set(ENV) | set(NOT_SET)
    assert set(TOML.values()) <= set(table(GATEWAY)) and set(ENV.values()) <= set(table(GATEWAY_ENV))


def test_every_variable_a_public_doc_or_deploy_file_names_has_a_row():
    """VAR over every public doc but CONTRIBUTING.md, and over GENERIC. Each name not in DEV is a row of STEWARD, OTHER
    or GATEWAY_ENV. The failure lists "<file>: <name>"."""
    known = set(table(STEWARD)) | set(table(OTHER)) | set(table(GATEWAY_ENV))
    files = [p for p in public_docs() if p.name != "CONTRIBUTING.md"] + [ROOT / g for g in GENERIC]
    missing = sorted(f"{p.relative_to(ROOT)}: {name}" for p in files if p.is_file()
                     for name in set(VAR.findall(p.read_text(encoding="utf-8"))) - DEV - known)
    assert not missing, missing


def test_every_row_outside_steward_settings_is_read_somewhere():
    """Each name in OTHER and GATEWAY_ENV appears as a whole word in src/ or GENERIC (.py, .sh, .yml, .json, .example
    and Caddyfile* files only), or in the gateway image's own files."""
    paths = [p for p in (ROOT / "src").rglob("*") if p.is_file() and p.suffix in READABLE]
    paths += [ROOT / g for g in GENERIC + GATEWAY_FILES]
    paths += [p for p in (ROOT / "deploy" / "proxy").glob("Caddyfile*") if p.is_file()]
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in paths if p.is_file())
    unread = [name for name in list(table(OTHER)) + list(table(GATEWAY_ENV))
              if not re.search(rf"\b{re.escape(name)}\b", text)]
    assert not unread, f"no code or deploy file reads: {unread}"
