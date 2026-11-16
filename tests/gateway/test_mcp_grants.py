"""Grants on the gateway (spec 7, rulings 2, 4): kept in a private file one per book, checked with the NAS before they
are saved, and printed as the exact `claude mcp add` command with Claude Code's local token."""
import asyncio
import json
import stat
from dataclasses import replace

import httpx2
import pytest
from typer.testing import CliRunner

from steward_gateway import cli
from steward_gateway.mcp import grants as G
from steward_gateway.mcp.nas import NasAway, NasClient, NasRefused

GRANT = "stg1.ours." + "A" * 43
MOM = "stg1.margaret-ellis." + "D" * 43
runner = CliRunner()


def test_grants_are_kept_privately_one_per_book_under_a_name_the_gateway_chooses(gw_cfg):
    assert G.load(gw_cfg) == {}
    assert G.add(gw_cfg, GRANT) == "steward-1"
    assert G.load(gw_cfg) == {"steward-1": GRANT}
    assert stat.S_IMODE(gw_cfg.grants_path.stat().st_mode) == 0o600
    newer = "stg1.ours." + "B" * 43
    assert G.add(gw_cfg, newer) == "steward-1"                          # the same book keeps its name
    assert G.load(gw_cfg) == {"steward-1": newer}
    assert G.add(gw_cfg, MOM) == "steward-2"
    assert G.remove(gw_cfg, "steward-1") is True and G.remove(gw_cfg, "steward-1") is False
    assert G.add(gw_cfg, "stg1.another-book." + "C" * 43) == "steward-1"   # the lowest free number
    assert G.load(gw_cfg) == {"steward-1": "stg1.another-book." + "C" * 43, "steward-2": MOM}
    assert "margaret" not in "".join(G.load(gw_cfg))


def test_a_file_keyed_by_book_address_is_not_read():
    """Only names the gateway chose are served, so an old file keyed by the book's address can't put it in a path."""
    assert G.ALIAS_RE.match("steward-12") and not G.ALIAS_RE.match("margaret-ellis")
    assert not G.ALIAS_RE.match("steward-0") and not G.ALIAS_RE.match("steward-margaret-ellis")


def test_nothing_made_from_the_book_reaches_claude_code(gw_cfg):
    """Ruling C1: Claude Code sends its server names and tool names to Anthropic on every request, so the name and the
    MCP path are the gateway's own, never the book's address (which is made from the book's name)."""
    alias = G.add(gw_cfg, MOM)
    command = G.claude_command(gw_cfg, alias, "t" * 43)
    assert command == ('claude mcp add --transport http --scope user steward-1 http://127.0.0.1:8431/mcp/steward-1 '
                       f'--header "Authorization: Bearer {"t" * 43}"')
    assert alias == "steward-1" and "margaret" not in command.casefold() and "ellis" not in command.casefold()


def test_only_steward_grants_are_accepted():
    for bad in ("", "stg1.ours.short", "stg2.ours." + "A" * 43, "stg1.Ours." + "A" * 43, "stg1.ours." + "A" * 43 + " x"):
        with pytest.raises(G.GrantError):
            G.slug_of(bad)


def test_the_local_token_is_made_once(gw_cfg):
    assert G.mcp_token(gw_cfg) is None
    token = G.mcp_token(gw_cfg, create=True)
    assert G.mcp_token(gw_cfg, create=True) == token and len(token) >= 40


PAIRED = "c" * 64


def nas(handler, paired=PAIRED):
    return NasClient("https://steward.tail1234.ts.net", lambda: paired,
                     http=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))


def test_the_nas_client_sends_the_grant_with_the_pairing_token_and_reads_answers():
    seen = []

    def handler(request):
        assert request.headers["x-steward-gateway"] == PAIRED
        seen.append((request.method, request.url.path, request.headers["authorization"],
                     json.loads(request.content) if request.content else None))
        return httpx2.Response(200, json={"ok": True})
    n = nas(handler)
    asyncio.run(n.tools("ours", GRANT))
    asyncio.run(n.call("ours", GRANT, "debts", {}))
    asyncio.run(n.finish("ours", GRANT, "mcp_0123456789abcdef", "stopped", "model", "parts[0].content"))
    assert seen == [("GET", "/api/b/ours/advisor/tools", f"Bearer {GRANT}", None),
                    ("POST", "/api/b/ours/advisor/tools/debts", f"Bearer {GRANT}", {"input": {}}),
                    ("POST", "/api/b/ours/advisor/calls/mcp_0123456789abcdef", f"Bearer {GRANT}",
                     {"outcome": "stopped", "check": "model", "path": "parts[0].content"})]


def test_the_nas_client_asks_nothing_before_pairing():
    def handler(request):
        raise AssertionError("asked the NAS")
    with pytest.raises(NasRefused) as e:
        asyncio.run(nas(handler, paired=None).tools("ours", GRANT))
    assert e.value.status == 503 and "paired" in e.value.message


def test_the_nas_client_says_refused_or_away():
    n = nas(lambda r: httpx2.Response(401, json={"error": "That grant isn't valid."}))
    with pytest.raises(NasRefused) as e:
        asyncio.run(n.tools("ours", GRANT))
    assert (e.value.status, e.value.message) == (401, "That grant isn't valid.")

    def refused(request):
        raise httpx2.ConnectError("refused")
    with pytest.raises(NasAway):
        asyncio.run(nas(refused).tools("ours", GRANT))


def test_mcp_grant_add_checks_with_the_nas_then_prints_the_command(gw_cfg, monkeypatch):
    from dataclasses import replace
    cfg = replace(gw_cfg, nas_url="https://steward.tail1234.ts.net", mcp=True)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    seen = []

    async def tools(self, slug, grant):
        seen.append((slug, self._gateway_token()))
        return {"book_id": 2, "book_kind": "parent", "until": "Nov 20", "chat": True, "tools": ["accounts"]}
    monkeypatch.setattr(NasClient, "tools", tools)
    from steward_gateway.secrets import write_private
    write_private(cfg.token_path, PAIRED)
    r = runner.invoke(cli.app, ["mcp-grant", "add"], input=MOM + "\n")
    assert r.exit_code == 0, r.output
    assert seen == [("margaret-ellis", PAIRED)]
    assert "This grant lets Claude Code look up that book until Nov 20 as steward-1." in r.output
    assert "claude mcp add --transport http --scope user steward-1 http://127.0.0.1:8431/mcp/steward-1" in r.output
    assert "margaret" not in r.output.casefold() and "ellis" not in r.output.casefold()
    assert G.load(cfg) == {"steward-1": MOM}
    listed = runner.invoke(cli.app, ["mcp-grant", "list"]).output
    assert "steward-1" in listed and "margaret" not in listed
    out = runner.invoke(cli.app, ["mcp-grant", "remove", "steward-1"]).output
    assert "claude mcp remove steward-1" in out and G.load(cfg) == {}


def test_mcp_grant_add_saves_nothing_when_the_nas_refuses_or_is_away(gw_cfg, monkeypatch):
    from dataclasses import replace
    cfg = replace(gw_cfg, nas_url="https://steward.tail1234.ts.net", mcp=True)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)

    async def refused(self, slug, grant):
        raise NasRefused(401, "That grant isn't valid.")
    monkeypatch.setattr(NasClient, "tools", refused)
    r = runner.invoke(cli.app, ["mcp-grant", "add"], input=GRANT + "\n")
    assert r.exit_code == 1 and "That grant isn't valid." in r.output and G.load(cfg) == {}

    async def away(self, slug, grant):
        raise NasAway()
    monkeypatch.setattr(NasClient, "tools", away)
    r = runner.invoke(cli.app, ["mcp-grant", "add"], input=GRANT + "\n")
    assert r.exit_code == 1 and "didn't answer" in r.output and G.load(cfg) == {}


def test_mcp_grant_add_needs_nas_url(gw_cfg, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: replace(gw_cfg, mcp=True))
    r = runner.invoke(cli.app, ["mcp-grant", "add"], input=GRANT + "\n")
    assert r.exit_code == 1 and "nas_url" in r.output


def test_a_grant_on_the_command_line_is_refused_and_not_saved(gw_cfg, monkeypatch):
    from dataclasses import replace
    cfg = replace(gw_cfg, nas_url="https://steward.tail1234.ts.net", mcp=True)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    r = runner.invoke(cli.app, ["mcp-grant", "add", MOM])
    assert r.exit_code == 2
    assert "Paste the grant when asked, not on the command line" in r.output
    assert G.load(cfg) == {} and "claude mcp add" not in r.output
