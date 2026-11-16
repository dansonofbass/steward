"""Spec 2026-11-05, section 7: the gateway's name becomes a setting. STEWARD_GATEWAY_NAME is what Steward's screens, CLI
and log call the gateway machine, "the gateway" when unset. Copy names it through the {gateway} slot."""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from typer.testing import CliRunner

from steward import gateway_name
from steward.app import create_app
from steward.cli import app as cli_app
from steward.settings import Settings
from steward_boundary.naming import DEFAULT_GATEWAY_NAME, THIS_MACHINE, name_in
from tests.factories import login, make_user

runner = CliRunner()


@pytest.mark.parametrize("text, name, out", [
    ("{gateway} is answering.", "the gateway", "The gateway is answering."),
    ("{gateway} is answering.", "Otter-PC", "Otter-PC is answering."),
    ("Chat needs {gateway}, which isn't answering.", "the gateway", "Chat needs the gateway, which isn't answering."),
    ("Checked. To stop, run it on {gateway}. {gateway} keeps going.", "this machine",
     "Checked. To stop, run it on this machine. This machine keeps going."),
    ("{gateway}'s check took out 1 part", "the gateway", "The gateway's check took out 1 part"),
    ("No slot here.", "Zebra-Box", "No slot here."),
    ("Waiting for {gateway}", "a$1\\g<0>", "Waiting for a$1\\g<0>"),     # a name is never read as a pattern
])
def test_the_slot_is_filled_and_capitalized_at_a_sentence_start(text, name, out):
    assert name_in(text, name) == out


@pytest.mark.parametrize("raw, name", [(None, "the gateway"), ("", "the gateway"), ("   ", "the gateway"),
                                       ("Otter-PC", "Otter-PC"), ("  Zebra   Box ", "Zebra Box"), ("x" * 40, "x" * 40)])
def test_a_name_is_tidied_and_empty_means_the_default(raw, name):
    assert gateway_name.clean(raw) == name


@pytest.mark.parametrize("raw", ["x" * 41, "{x}", "Box}", "Zebra\x00Box", "Zebra​Box"])
def test_a_name_copy_cant_hold_is_refused_in_plain_words(raw):
    with pytest.raises(ValueError, match="STEWARD_GATEWAY_NAME must be up to 40 characters"):
        gateway_name.clean(raw)


def test_settings_take_the_name_and_refuse_a_bad_one(settings, monkeypatch):
    assert settings.gateway_name == DEFAULT_GATEWAY_NAME
    monkeypatch.setenv("STEWARD_GATEWAY_NAME", "Zebra-Box")
    assert Settings(_env_file=None).gateway_name == "Zebra-Box"
    monkeypatch.setenv("STEWARD_GATEWAY_NAME", "{x}")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_the_cli_stops_on_a_bad_name_with_one_line(settings, monkeypatch):
    monkeypatch.setenv("STEWARD_GATEWAY_NAME", "{x}")
    r = runner.invoke(cli_app, ["book", "list"])
    assert r.exit_code == 1 and r.output.strip() == gateway_name.NAME_RULE


def test_serve_says_the_name_before_it_starts(settings, monkeypatch):
    import uvicorn
    assert runner.invoke(cli_app, ["init-key"]).exit_code == 0
    assert runner.invoke(cli_app, ["migrate"]).exit_code == 0
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setenv("STEWARD_GATEWAY_NAME", "Zebra-Box")
    r = runner.invoke(cli_app, ["serve"])
    assert r.exit_code == 0 and "Gateway name: Zebra-Box" in r.output.splitlines()


@pytest.fixture
def zebra(settings, books):
    """The app with STEWARD_GATEWAY_NAME=Zebra-Box and no gateway paired."""
    s = settings.model_copy(update={"gateway_name": "Zebra-Box"})
    with TestClient(create_app(s, books), base_url="https://nas.tail1234.ts.net") as c:
        yield c


def test_me_carries_the_name_and_the_nas_lines_use_it(zebra, db):
    make_user(db)
    login(zebra, "jr")
    assert zebra.get("/api/auth/me").json()["gateway_name"] == "Zebra-Box"
    s = zebra.get("/api/b/ours/chat").json()
    assert (s["gateway"]["state"], s["gateway"]["line"]) == ("not_set_up", "Chat isn't set up on Zebra-Box yet.")


def test_every_line_about_the_gateway_names_it_through_the_slot():
    from steward.advisor import gateway as gw_client, outgoing, state
    from steward.deps import GATEWAY_ONLY
    from steward.services import catchup
    from steward.services.simplefin.sync import MODEL_DOWN_MSG
    from steward.services.statements import client, copy
    from steward_boundary.protocol import LINES
    lines = [GATEWAY_ONLY, MODEL_DOWN_MSG, catchup.CAUGHT_UP, gw_client.REFUSED, state.GATEWAY_LINES["ok"],
             outgoing.CHECKS[2], outgoing.STORE_CHECKS[2], copy.HELD, copy.NOT_PAIRED, copy.ERRORS["layout_failed"],
             copy.ERRORS["page_failed"], copy.ERRORS["read_failed"], client.TOO_SLOW, client.UNREACHABLE,
             client.ERROR_STATUS, client.UNREADABLE,
             *(LINES[k] for k in ("not_set_up", "privacy_not_ready", "stopped_by_gateway", "dropped", "away"))]
    assert [t for t in lines if "{gateway}" not in t] == []


def test_this_machine_is_the_gateway_s_own_fill():
    assert name_in("Chat is turned off on {gateway}.", THIS_MACHINE) == "Chat is turned off on this machine."
