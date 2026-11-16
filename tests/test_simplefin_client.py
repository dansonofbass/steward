import base64
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from steward.services.simplefin.client import (
    SimplefinError, claim, fetch_accounts, parse_setup_token, split_access_url,
)
from tests.fake_simplefin import make_fake


HOSTS = ("testserver",)


def test_parse_setup_token():
    url = "http://testserver/claim/abc"
    assert parse_setup_token(base64.b64encode(url.encode()).decode(), HOSTS) == url
    with pytest.raises(ValueError):
        parse_setup_token("not base64!!")


def test_claim_once():
    app, state = make_fake()
    with TestClient(app) as http:
        access = claim(http, "http://testserver/claim/abc", HOSTS)
        assert split_access_url(access) == ("http://testserver/simplefin", "demo", "demo")
        with pytest.raises(SimplefinError):
            claim(http, "http://testserver/claim/abc", HOSTS)


def test_fetch_accounts_converts_and_drops_pending():
    app, state = make_fake()
    # 2026-10-13 02:00 UTC is 2026-10-12 in Los Angeles
    bal_epoch = int(datetime(2026, 10, 13, 2, 0, tzinfo=timezone.utc).timestamp())
    state.add_account("c1", "Big Bank", "bigbank", "acct-1", 1450_00, bal_epoch, txns=[
        ("t1", int(datetime(2026, 10, 3, 19, 0, tzinfo=timezone.utc).timestamp()), -54_12, "GREENLEAF MARKET #12"),
        ("t2", 0, -10_00, "PENDING THING", True),
    ])
    with TestClient(app) as http:
        access = claim(http, "http://testserver/claim/abc", HOSTS)
        s = fetch_accounts(http, access, start=None, allowed_hosts=HOSTS)
    assert s.connections[0].name == "Big Bank" and s.accounts[0].balance_cents == 1450_00
    assert s.accounts[0].balance_date == date(2026, 10, 12)
    assert [t.id for t in s.accounts[0].transactions] == ["t1"]
    assert s.accounts[0].transactions[0].posted_at == date(2026, 10, 3)


def test_fetch_errors_and_403():
    app, state = make_fake()
    state.add_account("c1", "Marcus", "marcus", "a1", 0, 1_700_000_000)
    state.fail_conn = "c1"
    with TestClient(app) as http:
        access = claim(http, "http://testserver/claim/abc", HOSTS)
        s = fetch_accounts(http, access, start=None, allowed_hosts=HOSTS)
        assert s.accounts == [] and s.errors[0].code == "con.auth" and s.errors[0].conn_id == "c1"
        with pytest.raises(SimplefinError) as e:
            fetch_accounts(http, "http://bad:creds@testserver/simplefin", start=None, allowed_hosts=HOSTS)
        assert "revoked" in str(e.value)


def _tok(url):
    return base64.b64encode(url.encode()).decode()


def test_setup_token_rejects_bad_targets():
    with pytest.raises(SimplefinError):
        parse_setup_token(_tok("http://127.0.0.1:5000/x"))
    with pytest.raises(SimplefinError):
        parse_setup_token(_tok("https://evil.example/claim/x"))
    with pytest.raises(ValueError):
        parse_setup_token(_tok("just some words"))
    assert parse_setup_token(_tok("https://bridge.simplefin.org/simplefin/claim/x"))
    app, _ = make_fake()
    with TestClient(app) as http:
        with pytest.raises(SimplefinError):
            claim(http, "https://evil.example/claim/x")
        with pytest.raises(SimplefinError, match="isn't allowed"):
            fetch_accounts(http, "https://u:p@evil.example/simplefin", start=None)


def test_split_access_url_unquotes_and_validates():
    assert split_access_url("https://us%40e:p%2Fw@h.example:8443/simplefin/") == (
        "https://h.example:8443/simplefin", "us@e", "p/w")
    with pytest.raises(SimplefinError):
        split_access_url("not a url")


def test_naive_start_rejected():
    with pytest.raises(ValueError):
        fetch_accounts(None, "http://u:p@testserver/simplefin", datetime(2026, 1, 1), allowed_hosts=HOSTS)


def test_status_messages():
    class R:
        def __init__(self, code, text="", js=None):
            self.status_code, self.text, self._js = code, text, js

        def json(self):
            if self._js is None:
                raise ValueError("no json")
            return self._js

    class H:
        def __init__(self, r):
            self.r = r

        def get(self, *a, **k):
            return self.r

    url = "http://u:p@testserver/simplefin"
    with pytest.raises(SimplefinError) as e:
        fetch_accounts(H(R(402)), url, None, allowed_hosts=HOSTS)
    assert str(e.value) == "SimpleFIN says the subscription needs payment."
    with pytest.raises(SimplefinError) as e:
        fetch_accounts(H(R(403)), url, None, allowed_hosts=HOSTS)
    assert str(e.value) == "SimpleFIN access was revoked. Link it again in Settings."
    for r in (R(200, "<html>"), R(200, "[]", [])):
        with pytest.raises(SimplefinError) as e:
            fetch_accounts(H(r), url, None, allowed_hosts=HOSTS)
        assert str(e.value) == "SimpleFIN sent a reply that could not be read."


def test_params_reach_server_and_pending_dropped():
    app, state = make_fake()
    state.add_account("c1", "Bank", "b", "a1", 100, 1_700_000_000, txns=[
        ("t1", 1_700_000_100, -1_00, "OK"),
        ("t2", 1_700_000_200, -2_00, "STILL PENDING", True),
    ])
    with TestClient(app) as http:
        access = claim(http, "http://testserver/claim/abc", HOSTS)
        s = fetch_accounts(http, access, datetime(2023, 1, 1, tzinfo=timezone.utc), pending=True, allowed_hosts=HOSTS)
    assert state.calls[-1] == {"start-date": str(int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp())),
                               "pending": "1", "version": "2"}
    assert [t.id for t in s.accounts[0].transactions] == ["t1"]


def test_bad_record_skipped_not_fatal():
    app, state = make_fake()
    state.add_account("c1", "Good", "g", "a1", 12_34, 1_700_000_000)
    state.add_account("c1", "Bad", "g", "a2", 0, 1_700_000_000, txns=[("t1", 1_700_000_100, 5, "x")])
    with TestClient(app) as http:
        access = claim(http, "http://testserver/claim/abc", HOSTS)
        payload = state.payload(None, False)
        payload["accounts"][1]["transactions"][0]["amount"] = "1.005"
        payload["accounts"][0]["balance"] = "12.3400"
        http.get = lambda *a, **k: type("R", (), {"status_code": 200, "json": lambda self: payload})()
        s = fetch_accounts(http, access, None, allowed_hosts=HOSTS)
    assert [a.id for a in s.accounts] == ["a1"] and s.accounts[0].balance_cents == 12_34
    assert s.errors[0].code == "steward.parse" and s.errors[0].account_id == "a2"
    assert "a2" in s.errors[0].msg


def test_network_failures_become_simplefin_errors():
    import httpx2
    import pytest as _pytest
    from steward.services.simplefin.client import SimplefinError, claim, fetch_accounts

    def boom(request):
        raise httpx2.ConnectError("down")

    with httpx2.Client(transport=httpx2.MockTransport(boom)) as http:
        with _pytest.raises(SimplefinError, match="Couldn't reach SimpleFIN"):
            claim(http, "http://testserver/claim/x", allowed_hosts=("testserver",))
        with _pytest.raises(SimplefinError, match="Couldn't reach SimpleFIN"):
            fetch_accounts(http, "http://u:p@testserver/simplefin", start=None, allowed_hosts=("testserver",))


def test_v1_errors_list_becomes_link_level_problems():
    app, state = make_fake()
    state.add_account("c1", "Bank", "b", "a1", 100, 1_700_000_000)
    state.v1_errors = ["Rate limit exceeded", "Another thing"]
    with TestClient(app) as http:
        access = claim(http, "http://testserver/claim/abc", HOSTS)
        s = fetch_accounts(http, access, start=None, allowed_hosts=HOSTS)
    assert [(e.code, e.msg, e.conn_id, e.account_id) for e in s.errors] == [
        ("gen", "Rate limit exceeded", None, None), ("gen", "Another thing", None, None)]


def test_fake_requires_version_2():
    app, _ = make_fake()
    with TestClient(app) as http:
        r = http.get("/simplefin/accounts", auth=("demo", "demo"))
    assert r.status_code == 400 and r.json() == {"error": "version required"}


def test_holdings_are_read_when_sent_and_a_bad_one_is_skipped_not_the_account():
    from steward.services.simplefin.client import SfHolding, _parse_account
    a = {"id": "a1", "name": "Taxable", "conn_id": "c1", "balance": "180000.00", "balance-date": 1_700_000_000,
         "transactions": [],
         "holdings": [{"id": "h1", "symbol": "VTI", "description": "Vanguard Total Stock Market ETF", "shares": "400.1234",
                       "market_value": "108,000.004", "cost_basis": "90000", "currency": "USD"},
                      {"id": "h2", "symbol": "", "description": "Cash sweep", "market_value": "72000"},
                      {"id": "h3", "symbol": "XYZ", "description": "No value"},
                      {"id": "h4", "symbol": "ABC", "description": "Bad value", "market_value": "lots"},
                      "not a holding"]}
    acct = _parse_account(a)
    assert acct.holdings == [SfHolding("VTI", "Vanguard Total Stock Market ETF", 400_123, 108_000_00, 90_000_00),
                             SfHolding(None, "Cash sweep", 0, 72_000_00, None)]
    assert acct.balance_cents == 180_000_00
    assert _parse_account({**a, "holdings": None}).holdings is None
    del a["holdings"]
    assert _parse_account(a).holdings is None
