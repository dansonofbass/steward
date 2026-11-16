from steward import clock
import json

from sqlalchemy.orm import Session
from typer.testing import CliRunner

from steward.advisor.state import set_chat_on
from steward.cli import app
from tests.advisor.test_chat_api import answered
from tests.advisor.stubs import StubGateway
from tests.factories import make_person

runner = CliRunner()


def test_ask_prints_the_answer_with_real_names_and_what_was_sent(settings, books, ours, ddb, monkeypatch):
    make_person(ddb, "jr", [(ours.id, "manager")])
    gw = StubGateway(answered("Person 1 has $14,500.00 in Account 1."))
    monkeypatch.setattr("steward.advisor.gateway.client_from_settings", lambda s: gw)
    r = runner.invoke(app, ["ask", "How much is in savings?", "--book", "ours", "--as", "jr"])
    assert r.exit_code == 1 and "Chat is off for this book." in r.output
    with Session(books.engine_for(ours)) as db:
        set_chat_on(db, True, None, clock.now())
        db.commit()
    r = runner.invoke(app, ["ask", "How much is in savings?", "--book", "ours", "--as", "jr"])
    assert r.exit_code == 0, r.output
    assert "Jr has $14,500.00 in Account 1." in r.output
    assert "Sent: 2 parts" in r.output and "cost $0.09" in r.output
    log = runner.invoke(app, ["advisor", "log", "--book", "ours"])
    assert log.exit_code == 0 and "Question" in log.output and "Jr" in log.output
    rows = json.loads(runner.invoke(app, ["advisor", "log", "--book", "ours", "--json"]).output)
    assert [row["part"] for row in rows] == ["question", "system"]


def test_ask_needs_a_member_and_a_paired_gateway(settings, books, ours, ddb, monkeypatch):
    make_person(ddb, "jr", [(ours.id, "manager")])
    make_person(ddb, "stranger")
    monkeypatch.setattr("steward.advisor.gateway.client_from_settings", lambda s: None)
    r = runner.invoke(app, ["ask", "Hi", "--book", "ours", "--as", "jr"])
    assert r.exit_code == 1 and "Chat isn't set up on the gateway yet. Run steward advisor pair first." in r.output
    monkeypatch.setattr("steward.advisor.gateway.client_from_settings", lambda s: StubGateway())
    r = runner.invoke(app, ["ask", "Hi", "--book", "ours", "--as", "stranger"])
    assert r.exit_code == 1 and "stranger isn't a member of ours." in r.output
    assert runner.invoke(app, ["ask", "Hi", "--book", "nope", "--as", "jr"]).output.strip() == "No book nope."


def test_advisor_check_reports_gateway(settings, books, monkeypatch):
    monkeypatch.setattr("steward.advisor.gateway.client_from_settings", lambda s: StubGateway())
    r = runner.invoke(app, ["advisor", "check"])
    assert r.exit_code == 0 and "The gateway is answering." in r.output and "This month: $3.12 of $10" in r.output
    monkeypatch.setattr("steward.advisor.gateway.client_from_settings", lambda s: StubGateway(away=True))
    r = runner.invoke(app, ["advisor", "check"])
    assert r.exit_code == 1 and "isn't answering" in r.output


def test_pair_needs_an_address(settings, books, monkeypatch):
    r = runner.invoke(app, ["advisor", "pair"])
    assert r.exit_code == 1 and "STEWARD_GATEWAY_URL" in r.output
