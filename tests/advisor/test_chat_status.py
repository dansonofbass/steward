"""What GET /chat, the preview and /api/books tell the page (plan B rulings 13, 21, 26, 29)."""
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from steward import deps
from steward.app import create_app
from tests.advisor.stubs import StubGateway
from tests.advisor.test_chat_api import CHAT, Q, answered
from tests.factories import login, make_person


@pytest.fixture
def members(books, ddb, ours):
    return make_person(ddb, "jr", [(ours.id, "manager")]), make_person(ddb, "vee", [(ours.id, "viewer")])


def make(settings, books, gw):
    return TestClient(create_app(settings, books, gateway=gw), base_url="https://nas.tail1234.ts.net")


def test_status_names_the_members_and_gateways_checks(settings, books, members):
    with make(settings, books, StubGateway()) as c:
        login(c, "vee")
        s = c.get(CHAT).json()
        assert s["members"] == ["Jr", "Vee"] and s["managers"] == ["Jr"]
        g = s["gateway"]
        assert g["checks"] == {"redaction": True, "key": True, "categorizer": False}
        assert g["checked"].startswith("today at ") and g["last_answered"].startswith("today at ")
        assert g["away_long"] is False and s["sent_month"] == {"requests": 0, "last": None}
        assert (g["paired"], g["url_set"]) == (True, False)


def test_away_long_waits_ten_minutes(settings, books, members):
    with make(settings, books, StubGateway(away=True)) as c:
        login(c, "jr")
        assert c.get(CHAT).json()["gateway"]["away_long"] is False
        c.app.state.advisor.monitor.started_at = deps.now() - timedelta(minutes=11)
        c.app.state.advisor.monitor.checked_at = None
        g = c.get(CHAT).json()["gateway"]
        assert (g["state"], g["away_long"], g["last_answered"], g["checks"]) == ("away", True, None, None)


def test_sent_month_counts_requests(settings, books, members):
    with make(settings, books, StubGateway(answered())) as c:
        login(c, "jr")
        c.post(f"{CHAT}/on", json={"on": True})
        c.post(f"{CHAT}/ask", json={"question": Q})
        sm = c.get(CHAT).json()["sent_month"]
        assert sm["requests"] == 1 and sm["last"].startswith("today at ")


def test_the_preview_names_the_labels_behind_its_aliases(settings, books, members):
    with make(settings, books, StubGateway()) as c:
        login(c, "jr")
        c.post(f"{CHAT}/on", json={"on": True})
        p = c.post(f"{CHAT}/preview", json={"text": "Did Vee pay the bill?"}).json()
        alias = next(ch["label"] for ch in p["chips"] if ch["layer"] == "steward")
        assert p["labels"] == {alias: "Vee"}


def test_each_book_says_whether_chat_is_on(settings, books, members):
    with make(settings, books, StubGateway()) as c:
        login(c, "jr")
        assert c.get("/api/books").json()["books"][0]["chat"] is False
        c.post(f"{CHAT}/on", json={"on": True})
        assert c.get("/api/books").json()["books"][0]["chat"] is True
        login(c, "vee")
        assert c.get("/api/books").json()["books"][0]["chat"] is True


def test_status_says_whether_the_gateway_has_claude_code_on(settings, books, members):
    base = StubGateway()._health
    for health, want in (({**base, "mcp": False}, False), ({**base, "mcp": True}, True), (base, True)):
        with make(settings, books, StubGateway(health=health)) as c:   # an older gateway sends no mcp: it listened
            login(c, "jr")
            assert c.get(CHAT).json()["gateway"]["mcp"] is want, health.get("mcp")
    with make(settings, books, StubGateway(away=True)) as c:
        login(c, "jr")
        assert c.get(CHAT).json()["gateway"]["mcp"] is None
