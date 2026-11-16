"""Spec 2026-11-05, section 7: the gateway's own CLI and errors run on its own machine, so they say "this machine";
what it sends the NAS keeps {gateway}, and the NAS fills in its name."""
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from steward_gateway import categorize, cli, pdf, statements
from steward_gateway.mcp import nas, server
from steward_gateway.pairing import PairRefused, claim

runner = CliRunner()


def test_the_cli_says_this_machine(gw_cfg, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    stop = runner.invoke(cli.app, ["stop-chat"])
    assert stop.output.strip() == "Chat is turned off on this machine. Run steward-gateway start-chat to turn it back on."
    assert runner.invoke(cli.app, ["start-chat"]).output.strip() == "Chat is allowed again on this machine."
    assert runner.invoke(cli.app, ["mcp-grant", "list"]).output.strip() == "No grants on this machine yet."
    assert "Steward to finish pairing" in runner.invoke(cli.app, ["pair", "ABCD-EFGH-JKMN-PQRS"]).output


def test_its_own_errors_say_this_machine():
    assert categorize.CATEGORIZER_AWAY == "The categorizer on this machine isn't answering."
    assert statements.STATEMENTS_AWAY == "The statement reader on this machine isn't answering."
    assert pdf.PDF_OFF == "This machine can't open PDFs safely right now."
    assert server.NO_NAS == "nas_url isn't set in gateway.toml on this machine."
    assert server.NAS_AWAY == "Steward isn't answering."
    assert nas.NOT_PAIRED == "This machine isn't paired with Steward yet. Run steward advisor pair where Steward runs."


def test_no_pairing_waiting_says_this_machine(gw_cfg):
    with pytest.raises(PairRefused, match=r"Run steward-gateway pair on this machine\."):
        claim(gw_cfg, "ABCD", datetime(2026, 11, 5, tzinfo=timezone.utc))
