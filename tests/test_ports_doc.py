"""docs/reference/ports-and-volumes.md against the compose files and the gateway's defaults."""
import re
from dataclasses import fields

import yaml

from steward_gateway.config import GatewayConfig
from tests.public_docs import ROOT, section

DOC = ROOT / "docs" / "reference" / "ports-and-volumes.md"
COMPOSE_FILES = ("deploy/compose.yml", "deploy/compose.demo.yml")


def mentioned() -> set[str]:
    return set(re.findall(r"`([^`]+)`", DOC.read_text(encoding="utf-8")))


def test_every_port_and_volume_the_compose_files_use_is_listed():
    """For compose.yml and compose.demo.yml: each published container port (the part after the last ':'), each named
    volume and each ./ bind mount appears in backticks in ports-and-volumes.md; so do GatewayConfig's port and mcp_port
    defaults."""
    shown, expected = mentioned(), set()
    for name in COMPOSE_FILES:
        compose = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
        expected |= set(compose.get("volumes") or {})
        for service in compose["services"].values():
            expected |= {str(p).rsplit(":", 1)[-1] for p in service.get("ports", [])}
            expected |= {v.split(":", 1)[0] for v in service.get("volumes", []) if str(v).startswith("./")}
    defaults = {f.name: f.default for f in fields(GatewayConfig)}
    expected |= {str(defaults["port"]), str(defaults["mcp_port"])}
    assert expected >= {"8420", "443", "80", "demo-data", "gateway-state", "./data", "8430", "8431"}
    assert not expected - shown, f"not in ports-and-volumes.md: {sorted(expected - shown)}"


def test_the_page_has_its_three_sections():
    for heading in ("## Ports", "## Volumes and folders", "## Removing Steward"):
        assert section(DOC, heading).strip(), heading
