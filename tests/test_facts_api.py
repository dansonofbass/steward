from datetime import datetime, timezone

import pytest
from tests.factories import make_user



def login(client, db):
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})


@pytest.mark.parametrize("key, good, bad", [
    ("next_dollar.cash_months", ["1", "6", "24"], ["0", "25", "6.5", "six"]),
    ("next_dollar.debt_rate_bp", ["0", "700", "10000"], ["-1", "10001", "7.5", "7%"]),
    ("health.hsa_plan", ["yes", "no", "unsure"], ["Yes", "maybe", ""]),
    ("jr.payroll_hsa_cents", ["0", "875000", "10000000"], ["-1", "10000001", "60.5", "six"]),
    ("jr.payroll_k401_cents", ["0", "2450000", "10000000"], ["-1", "10000001", "1,000"]),
    ("giving.outside_cents", ["0", "5000", "10000000"], ["-1", "10000001", "50.5", "fifty"]),
])
def test_next_dollar_facts(client, db, key, good, bad):
    login(client, db)
    for v in good:
        assert client.post("/api/b/ours/facts", json={"key": key, "value": v}).status_code == 201, v
    for v in bad:
        r = client.post("/api/b/ours/facts", json={"key": key, "value": v})
        assert r.status_code == 422, v
    assert client.get("/api/b/ours/facts").json()["facts"][key]["value"] == good[-1]


def test_facts_keep_history_latest_wins(client, db):
    login(client, db)
    assert client.post("/api/b/ours/facts", json={"key": "home.value_cents", "value": "85000000", "as_of": "2025-01-01"}).status_code == 201
    assert client.post("/api/b/ours/facts", json={"key": "home.value_cents", "value": "90000000", "as_of": "2026-10-01"}).status_code == 201
    facts = client.get("/api/b/ours/facts").json()["facts"]
    assert facts["home.value_cents"]["value"] == "90000000"
    hist = client.get("/api/b/ours/facts/home.value_cents/history").json()["history"]
    assert [h["value"] for h in hist] == ["90000000", "85000000"]


def test_unknown_key(client, db):
    login(client, db)
    r = client.post("/api/b/ours/facts", json={"key": "favorite.color", "value": "blue"})
    assert r.status_code == 422 and r.json()["error"] == "Unknown fact key."


def test_empty_facts(client, db):
    login(client, db)
    r = client.get("/api/b/ours/facts")
    assert r.status_code == 200 and r.json() == {"facts": {}}


def test_requires_sign_in(client):
    assert client.get("/api/b/ours/facts").status_code == 401
    assert client.get("/api/b/ours/facts/state/history").status_code == 401
    assert client.post("/api/b/ours/facts", json={"key": "state", "value": "CA"}).status_code == 401


def test_same_as_of_later_entry_wins(client, db):
    login(client, db)
    for v in ("single", "mfj"):
        client.post("/api/b/ours/facts", json={"key": "filing_status", "value": v, "as_of": "2026-01-01"})
    assert client.get("/api/b/ours/facts").json()["facts"]["filing_status"]["value"] == "mfj"
    hist = client.get("/api/b/ours/facts/filing_status/history").json()["history"]
    assert [h["value"] for h in hist] == ["mfj", "single"]


@pytest.mark.parametrize("key,bad,good,msg", [
    ("home.value_cents", "8500.00", "85000000", "Enter a whole number of cents."),
    ("home.value_cents", "1,000", "-5", "Enter a whole number of cents."),
    ("mortgage.rate_bp", "287.55", "287.5", "Enter basis points with at most one decimal place."),
    ("mortgage.rate_bp", "10000.5", "312", "Enter a percentage between 0 and 100."),
    ("jr.dob", "2026-13-40", "1980-02-29", "Enter a date like 2026-10-12."),
    ("mortgage.payoff_date", "soon", "2045-06-01", "Enter a date like 2026-10-12."),
    ("state", "ZZ", "CA", "Choose a state."),
    ("filing_status", "married", "mfj", "Choose single, mfj, mfs or hoh."),
    ("jr.k401_pct_bp", "12000", "800", "Enter a percentage between 0 and 100."),
    ("employer.match_cap_bp", "-1", "600", "Enter a percentage between 0 and 100."),
    ("jr.k401_roth_share_bp", "abc", "0", "Enter a whole number of basis points."),
    ("jr.salary_cents", "-5", "16000000", "Enter an amount that isn't negative."),
    ("health.premium_cents", "1.5", "1680000", "Enter a whole number of cents."),
    ("mortgage.payment_cents", "-268000", "268000", "Enter an amount that isn't negative."),
    ("jr.salary_cents", "1000000001", "1000000000", "Enter an amount up to $10,000,000."),
    ("mortgage.payment_cents", "10000001", "10000000", "Enter an amount up to $100,000."),
    ("health.premium_cents", "100000001", "100000000", "Enter an amount up to $1,000,000."),
])
def test_value_validation(client, db, key, bad, good, msg):
    login(client, db)
    r = client.post("/api/b/ours/facts", json={"key": key, "value": bad})
    assert r.status_code == 422 and r.json() == {"error": msg}
    assert client.get(f"/api/b/ours/facts/{key}/history").json()["history"] == []
    assert client.post("/api/b/ours/facts", json={"key": key, "value": good}).status_code == 201


def test_default_as_of_is_pacific_today(client, db, monkeypatch):
    login(client, db)
    monkeypatch.setattr("steward.clock.now", lambda: datetime(2026, 10, 13, 3, 0, tzinfo=timezone.utc))
    r = client.post("/api/b/ours/facts", json={"key": "state", "value": "CA"})
    assert r.status_code == 201 and r.json()["as_of"] == "2026-10-12"


def test_history_unknown_key_404(client, db):
    login(client, db)
    r = client.get("/api/b/ours/facts/favorite.color/history")
    assert r.status_code == 404 and r.json() == {"error": "Unknown fact key."}


def test_trailing_newline_is_not_an_integer(client, db):
    login(client, db)
    r = client.post("/api/b/ours/facts", json={"key": "home.value_cents", "value": "12\n"})
    assert r.status_code == 422 and r.json() == {"error": "Enter a whole number of cents."}


def test_plan_fact_keys_are_accepted(client, db):
    login(client, db)
    for key, value in (("jr.salary_cents", "16000000"), ("jr.k401_pct_bp", "1000"), ("jr.k401_roth_share_bp", "0"),
                       ("employer.match_rate_bp", "5000"), ("employer.match_cap_bp", "600"),
                       ("mortgage.payment_cents", "300000"), ("health.premium_cents", "1680000")):
        assert client.post("/api/b/ours/facts", json={"key": key, "value": value}).status_code == 201, key
    assert client.get("/api/b/ours/facts").json()["facts"]["employer.match_cap_bp"]["value"] == "600"


def test_a_value_with_thousands_of_digits_is_not_a_whole_number(client, db):
    login(client, db)
    r = client.post("/api/b/ours/facts", json={"key": "jr.salary_cents", "value": "1" * 5000})
    assert r.status_code == 422 and r.json() == {"error": "Enter a whole number of cents."}


@pytest.mark.parametrize("sent", ["ca", "Ca", " CA ", "CA"])
def test_state_is_stored_uppercase(client, db, sent):
    login(client, db)
    r = client.post("/api/b/ours/facts", json={"key": "state", "value": sent})
    assert r.status_code == 201 and r.json()["value"] == "CA"
    assert client.get("/api/b/ours/facts").json()["facts"]["state"]["value"] == "CA"


@pytest.mark.parametrize("bad", ["", "California", "C", "ca1", "XX"])
def test_state_rejects_non_codes(client, db, bad):
    login(client, db)
    r = client.post("/api/b/ours/facts", json={"key": "state", "value": bad})
    assert r.status_code == 422 and r.json() == {"error": "Choose a state."}


def test_state_codes_are_fifty_states_plus_dc():
    from steward.api.facts import STATE_CODES
    assert len(STATE_CODES) == 51 and "DC" in STATE_CODES


def test_a_rate_keeps_one_decimal_of_basis_points(client, db):
    login(client, db)
    r = client.post("/api/b/ours/facts", json={"key": "mortgage.rate_bp", "value": "287.5"})
    assert r.status_code == 201 and r.json()["value"] == "287.5"
    r = client.post("/api/b/ours/facts", json={"key": "jr.k401_pct_bp", "value": "800.5"})
    assert r.status_code == 422 and r.json() == {"error": "Enter a whole number of basis points."}


@pytest.mark.parametrize("key", ["ss.jr.estimate_cents", "ss.spouse.estimate_cents"])
def test_social_security_estimates_are_gone(client, db, key):
    login(client, db)
    r = client.post("/api/b/ours/facts", json={"key": key, "value": "280000"})
    assert r.status_code == 422 and r.json() == {"error": "Unknown fact key."}


@pytest.mark.parametrize("key,good,bad,msg", [
    ("home.owns", "yes", "maybe", "Choose yes or no."),
    ("jr.ss_estimate", "yes", "no", "Say yes to use Steward's estimate."),
    ("spouse.ss_estimate", "yes", "true", "Say yes to use Steward's estimate."),
])
def test_profile_answers_are_facts_with_plain_word_checks(frozen, signed_in, key, good, bad, msg):
    assert signed_in.post("/api/b/ours/facts", json={"key": key, "value": good}).status_code == 201
    r = signed_in.post("/api/b/ours/facts", json={"key": key, "value": bad})
    assert r.status_code == 422 and r.json() == {"error": msg}
