"""Claude Code's grants on the gateway (spec 7, ruling 4): the text Settings → Chat showed once, kept in
mcp-grants.json in the config dir (mode 600), one per book; and Claude Code's own local token (mcp.token,
mode 600), which every MCP request must carry. The file is read on every request, so adding or removing a grant needs
no restart.

Each grant is kept under a name the gateway chooses, steward-1, steward-2, … (the lowest free number; final review
ruling C1). That name is Claude Code's server name and the /mcp/<name> path. Claude Code sends its server and tool
names to Anthropic with every request, and a book's address is made from the book's name (often a parent's full
name), so the address is used only on the gateway's own call to the NAS."""
from __future__ import annotations

import json
import re
import secrets

from steward_gateway.config import GatewayConfig
from steward_gateway.secrets import read_private, write_private

# Must match GRANT_RE in src/steward/advisor/grants.py: the gateway may not import `steward` outside the evals.
GRANT_RE = re.compile(r"^stg1\.([a-z0-9][a-z0-9-]{0,39})\.([A-Za-z0-9_-]{43})$")
ALIAS_RE = re.compile(r"^steward-([1-9][0-9]{0,3})$")


class GrantError(ValueError):
    """Not a grant from Settings → Chat → Claude Code."""


def slug_of(text: str) -> str:
    m = GRANT_RE.match(text or "")
    if m is None:
        raise GrantError("That isn't a grant from Settings → Chat → Claude Code. Copy it again from Steward.")
    return m.group(1)


def load(cfg: GatewayConfig) -> dict[str, str]:
    """name → grant. Only names the gateway chose are read."""
    raw = read_private(cfg.grants_path)
    data = json.loads(raw) if raw else {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if ALIAS_RE.match(k) and isinstance(v, str) and GRANT_RE.match(v)}


def _save(cfg: GatewayConfig, grants: dict[str, str]) -> None:
    write_private(cfg.grants_path, json.dumps(grants, sort_keys=True))


def add(cfg: GatewayConfig, text: str) -> str:
    """Keep the grant and give back its name: the book's existing name if it has one here, else the lowest free one."""
    slug = slug_of(text)
    grants = load(cfg)
    alias = next((k for k, v in grants.items() if slug_of(v) == slug), None)
    if alias is None:
        taken = {int(ALIAS_RE.match(k).group(1)) for k in grants}
        alias = f"steward-{next(n for n in range(1, len(taken) + 2) if n not in taken)}"
    grants[alias] = text
    _save(cfg, grants)
    return alias


def remove(cfg: GatewayConfig, alias: str) -> bool:
    grants = load(cfg)
    if alias not in grants:
        return False
    del grants[alias]
    _save(cfg, grants)
    return True


def mcp_token(cfg: GatewayConfig, *, create: bool = False) -> str | None:
    token = read_private(cfg.mcp_token_path)
    if token is None and create:
        token = secrets.token_urlsafe(32)
        write_private(cfg.mcp_token_path, token)
    return token


def claude_command(cfg: GatewayConfig, alias: str, token: str) -> str:
    return (f"claude mcp add --transport http --scope user {alias} http://127.0.0.1:{cfg.mcp_port}/mcp/{alias} "
            f'--header "Authorization: Bearer {token}"')
