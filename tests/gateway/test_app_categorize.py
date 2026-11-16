"""The categorizer's routes (spec 6.1): the pairing token, one row or up to 50, plain errors, and logs that carry
counts and timings, never a description."""
import logging

from fastapi.testclient import TestClient

from steward_gateway.app import create_gateway_app
from steward_gateway.categorize import Answer, Example, Row
from steward_gateway.redact.patterns import PatternDetector
from steward_gateway.secrets import write_private
from tests.gateway.fakes import FakeCategorizer, NameListDetector

TOKEN = "c" * 64
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def client(gw_cfg, categorizer):
    write_private(gw_cfg.token_path, TOKEN)
    app = create_gateway_app(gw_cfg, detectors=[PatternDetector(), NameListDetector()], client=None,
                             categorizer=categorizer)
    return TestClient(app)


def test_one_row(gw_cfg):
    fake = FakeCategorizer(answers=lambda d: Answer("dining", "Maple Leaf Cafe"))
    with client(gw_cfg, fake) as c:
        assert c.post("/v1/categorize", json={"description": "SQ *MAPLE LEAF CAFE", "amount_cents": -1840}).status_code == 401
        r = c.post("/v1/categorize", json={"description": "SQ *MAPLE LEAF CAFE", "amount_cents": -1840}, headers=AUTH)
        assert r.json() == {"category": "dining", "merchant": "Maple Leaf Cafe"}
    assert fake.calls == [[Row("SQ *MAPLE LEAF CAFE", -1840)]]


def test_a_batch_keeps_its_order(gw_cfg):
    fake = FakeCategorizer()
    rows = [{"description": d, "amount_cents": -100} for d in ("HARBOR CAFE", "CHECK ••43", "BEAN CAFE")]
    with client(gw_cfg, fake) as c:
        r = c.post("/v1/categorize/batch", json={"rows": rows}, headers=AUTH)
    assert r.json() == {"rows": [{"category": "dining", "merchant": None}, {"category": "uncategorized", "merchant": None},
                                 {"category": "dining", "merchant": None}]}


def test_bad_bodies_are_422(gw_cfg):
    one = {"description": "X", "amount_cents": -1}
    with client(gw_cfg, FakeCategorizer()) as c:
        for body in ({"description": "X"}, {"description": 3, "amount_cents": 1}, {"description": "X", "amount_cents": True},
                     {"description": "x" * 201, "amount_cents": 1}, [one]):
            r = c.post("/v1/categorize", json=body, headers=AUTH)
            assert (r.status_code, r.json()) == (422, {"error": "That request wasn't understood."}), body
        for body in ({"rows": []}, {"rows": [one] * 51}, {"rows": [one, {"description": "X"}]}, {"rows": "x"}):
            assert c.post("/v1/categorize/batch", json=body, headers=AUTH).status_code == 422, body
        r = c.post("/v1/categorize", content=b"not json", headers={**AUTH, "content-type": "application/json"})
        assert r.status_code == 422


def test_ollama_away_is_503_with_plain_words(gw_cfg):
    with client(gw_cfg, FakeCategorizer(away=True)) as c:
        r = c.post("/v1/categorize", json={"description": "X", "amount_cents": -1}, headers=AUTH)
        assert (r.status_code, r.json()) == (503, {"error": "The categorizer on this machine isn't answering."})
        r = c.post("/v1/categorize/batch", json={"rows": [{"description": "X", "amount_cents": -1}]}, headers=AUTH)
        assert r.status_code == 503


def test_health_says_whether_the_categorizer_is_ready(gw_cfg):
    with client(gw_cfg, FakeCategorizer(ready=False)) as c:
        assert c.get("/v1/health", headers=AUTH).json()["categorizer"] is False
    with client(gw_cfg, FakeCategorizer(ready=True)) as c:
        assert c.get("/v1/health", headers=AUTH).json()["categorizer"] is True


def test_logs_carry_counts_never_descriptions(gw_cfg, caplog):
    caplog.set_level(logging.INFO)
    with client(gw_cfg, FakeCategorizer()) as c:
        c.post("/v1/categorize/batch", json={"rows": [{"description": "HARBOR CAFE OAKHAVEN", "amount_cents": -100}]},
               headers=AUTH)
    assert "HARBOR" not in caplog.text and "dining" not in caplog.text
    assert "categorize.done" in caplog.text


def test_business_rides_only_when_there_is_one(gw_cfg):
    fake = FakeCategorizer(answers=lambda d: Answer("subscriptions", None, 87) if "NOTE" in d
                           else Answer("dining", None))
    rows = [{"description": d, "amount_cents": -100} for d in ("NOTEFLOW PRO", "HARBOR CAFE")]
    with client(gw_cfg, fake) as c:
        r = c.post("/v1/categorize/batch", json={"rows": rows}, headers=AUTH)
    assert r.json() == {"rows": [{"category": "subscriptions", "merchant": None, "business": 87},
                                 {"category": "dining", "merchant": None}]}


def test_a_guess_and_its_confidence_ride_in_the_reply_only_when_there(gw_cfg):
    fake = FakeCategorizer(answers=lambda d: Answer("uncategorized", None, None, 0.45, "dining") if "GRILL" in d
                           else Answer("dining", None, None, 0.91))
    rows = [{"description": d, "amount_cents": -100} for d in ("HARBOR GRILL", "BEAN CAFE")]
    with client(gw_cfg, fake) as c:
        r = c.post("/v1/categorize/batch", json={"rows": rows}, headers=AUTH)
    assert r.json() == {"rows": [{"category": "uncategorized", "merchant": None, "confidence": 0.45, "guess": "dining"},
                                 {"category": "dining", "merchant": None, "confidence": 0.91}]}


def test_examples_reach_the_categorizer_and_bad_examples_are_422(gw_cfg):
    fake = FakeCategorizer()
    rows = [{"description": "BEAN CAFE", "amount_cents": -100}]
    good = [{"description": "UNION SERVICE CENTER", "category": "home"}]
    with client(gw_cfg, fake) as c:
        assert c.post("/v1/categorize/batch", json={"rows": rows, "examples": good}, headers=AUTH).status_code == 200
        assert c.post("/v1/categorize/batch", json={"rows": rows}, headers=AUTH).status_code == 200
        assert c.post("/v1/categorize/batch", json={"rows": rows, "examples": None}, headers=AUTH).status_code == 200
        for bad in ([{"description": "X", "category": "transfer"}], [{"description": "X", "category": "reimbursement"}],
                    [{"description": "X", "category": "lambos"}],
                    [{"description": "x" * 201, "category": "home"}], [{"description": 3, "category": "home"}],
                    [{"category": "home"}], good * 41, "x", [1]):
            r = c.post("/v1/categorize/batch", json={"rows": rows, "examples": bad}, headers=AUTH)
            assert (r.status_code, r.json()) == (422, {"error": "That request wasn't understood."}), bad
    assert fake.examples == [[Example("UNION SERVICE CENTER", "home")], [], []]


def test_health_lists_the_categorizer_features(gw_cfg):
    with client(gw_cfg, FakeCategorizer()) as c:
        assert c.get("/v1/health", headers=AUTH).json()["categorizer_features"] == ["guess", "examples"]


def test_logs_count_guesses_and_examples_never_their_words(gw_cfg, caplog):
    caplog.set_level(logging.INFO)
    fake = FakeCategorizer(answers=lambda d: Answer("uncategorized", None, None, 0.4, "home"))
    with client(gw_cfg, fake) as c:
        c.post("/v1/categorize/batch", json={"rows": [{"description": "UNION SERVICE CENTER", "amount_cents": -100}],
                                            "examples": [{"description": "HARBOR GRILL", "category": "dining"}]}, headers=AUTH)
    assert "HARBOR" not in caplog.text and "UNION" not in caplog.text and "home" not in caplog.text
    assert "guessed=1" in caplog.text and "examples=1" in caplog.text
    assert "rows=1" in caplog.text and "categorized=0" in caplog.text
