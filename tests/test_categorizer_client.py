"""The NAS's link to the categorizer (spec 6.1, rulings 8, 10, 11): digits masked before sending, the pairing token,
batches of up to 50, never transfer or uncategorized from the model, and a miss remembered for the catch-up."""
import json
import threading

import httpx2
import pytest

from steward.services.categorizer_client import HttpModelClient, NullModelClient, client_for
from tests.waiting import CEILING


def make(handler, **kw):
    kw.setdefault("cooldown_s", 0)
    return HttpModelClient("http://gateway-box:8430/v1/categorize", timeout_s=0.2, transport=httpx2.MockTransport(handler),
                           **kw)


def test_digits_are_masked_and_the_token_is_sent():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json={"category": "dining", "merchant": "Harbor Grill"})
    c = make(handler, token="t" * 64)
    assert c.categorize("HARBOR GRILL 4417002918 OAKHAVEN", -4100) == ("dining", "Harbor Grill")
    assert seen["auth"] == "Bearer " + "t" * 64
    assert "4417002918" not in seen["body"]["description"] and seen["body"]["description"].startswith("HARBOR GRILL ")
    assert seen["body"]["amount_cents"] == -4100


def test_long_descriptions_are_cut_to_200_characters():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json={"rows": [{"category": "dining", "merchant": None}]})
    make(handler).categorize_batch([("CAFE " * 80, -1)])
    assert len(seen["body"]["rows"][0]["description"]) == 200


def test_a_batch_goes_to_the_batch_address_and_keeps_its_order():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json={"rows": [{"category": "dining", "merchant": "Bean Cafe"},
                                                   {"category": "uncategorized", "merchant": None}]})
    c = make(handler)
    assert c.categorize_batch([("BEAN CAFE", -500), ("POS PURCHASE", -900)]) == [("dining", "Bean Cafe"), None]
    assert seen["path"] == "/v1/categorize/batch"
    assert seen["body"] == {"rows": [{"description": "BEAN CAFE", "amount_cents": -500},
                                     {"description": "POS PURCHASE", "amount_cents": -900}]}
    assert c.categorize_batch([]) == []
    with pytest.raises(ValueError):
        c.categorize_batch([("X", -1)] * 51)


def test_the_nas_never_takes_transfer_or_uncategorized_from_the_model():
    c = make(lambda r: httpx2.Response(200, json={"rows": [{"category": "transfer", "merchant": None},
                                                           {"category": "uncategorized", "merchant": None},
                                                           {"category": "lambos", "merchant": None}]}))
    assert c.categorize_batch([("A", -1), ("B", -1), ("C", -1)]) == [None, None, None]
    c = make(lambda r: httpx2.Response(200, json={"category": "transfer", "merchant": None}))
    assert c.categorize("ONLINE PAYMENT", -1) is None


def test_the_nas_never_takes_reimbursement_from_the_model():
    """Reimbursable spec, Privacy: only people and rules sort a repayment."""
    c = make(lambda r: httpx2.Response(200, json={"rows": [{"category": "reimbursement", "merchant": None}]}))
    assert c.categorize_batch([("ACME CORP EXP", 50_000)]) == [None]
    c = make(lambda r: httpx2.Response(200, json={"category": "uncategorized", "merchant": None,
                                                  "guess": "reimbursement", "confidence": 0.4}))
    c.features = frozenset({"guess"})
    g = c.categorize("ACME CORP EXP", 50_000)
    assert not g and g.category is None and g.pct == 40


def test_a_batch_reply_of_the_wrong_length_or_shape_is_a_failure():
    for body in ({"rows": [{"category": "dining", "merchant": None}]}, {"rows": "x"}, ["a list"], {"rows": [1, 2]}):
        c = make(lambda r, b=body: httpx2.Response(200, json=b))
        c.missed = False
        assert c.categorize_batch([("A", -1), ("B", -1)]) is None
        assert "could not be read" in c.last_error and c.missed is True


def test_missed_starts_true_survives_success_and_is_set_by_failure_and_cool_off():
    clock, fail = [100.0], [True]

    def handler(request):
        if fail[0]:
            return httpx2.Response(503, json={"error": "The categorizer on this machine isn't answering."})
        return httpx2.Response(200, json={"rows": [{"category": "dining", "merchant": None}]})
    c = make(handler, cooldown_s=60, now=lambda: clock[0])
    assert c.missed is True
    c.missed = False
    assert c.categorize_batch([("CAFE", -1)]) is None and c.missed is True and "HTTP 503" in c.last_error
    c.missed = False
    clock[0] = 130.0                                # still cooling off: nothing is asked, but the miss is remembered
    assert c.categorize_batch([("CAFE", -1)]) is None and c.missed is True
    clock[0] = 161.0
    fail[0] = False
    c.missed = False
    assert c.categorize_batch([("CAFE", -1)]) == [("dining", None)]
    assert c.missed is False and c.last_error is None


def one_batch_gateway(each_s: float, seen: dict):
    """A fake gateway that works through batches in turn, as the gateway's does (one Ollama prompt at a time), on a
    virtual clock. A batch that arrives while others are in the gateway waits `each_s` for each of them, then takes
    `each_s` itself, and gets a timeout, as from the network, when that passes the client's read timeout. No real time
    passes. seen["most"] is the most batches that were ever in the gateway at once."""
    lock = threading.Lock()
    seen.update(inside=0, most=0)

    def handler(request):
        with lock:
            ahead = seen["inside"]
            seen["inside"] += 1
            seen["most"] = max(seen["most"], seen["inside"])
        try:
            if (ahead + 1) * each_s > request.extensions["timeout"]["read"]:
                raise httpx2.ReadTimeout("timed out", request=request)
            return httpx2.Response(200, json={"rows": [{"category": "dining", "merchant": None}]})
        finally:
            with lock:
                seen["inside"] -= 1
    return handler


def test_batches_sent_at_once_wait_their_turn_before_their_timeout_starts():
    """An import, a sync and the catch-up can each send a batch at once. The gateway works through them in turn, so
    the third used to wait two batches inside its own timeout (on the gateway two batches of 50 at 25 to 32 s each, of
    60 s), time out and lose its rows. The NAS now sends one batch at a time, so each timeout counts from when the
    gateway takes that batch."""
    seen, out = {}, []
    c = make(one_batch_gateway(0.2, seen), batch_timeout_s=0.5)
    c.missed = False
    go = threading.Barrier(3)

    def one():
        go.wait(CEILING)
        out.append(c.categorize_batch([("CAFE", -1)]))
    threads = [threading.Thread(target=one) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(CEILING)
    assert not any(t.is_alive() for t in threads)
    assert out == [[("dining", None)]] * 3 and c.missed is False and c.last_error is None
    assert seen["most"] == 1                        # sent in turn, never two at once


def test_the_null_client_answers_nothing_and_never_misses():
    n = NullModelClient()
    assert n.categorize_batch([("A", -1), ("B", -2)]) is None and n.missed is False


def test_client_for_prefers_the_override_then_the_paired_gateway(settings):
    assert isinstance(client_for(settings), NullModelClient)
    paired = settings.model_copy(update={"gateway_url": "http://gateway-box:8430"})
    assert isinstance(client_for(paired), NullModelClient)          # no token yet: not paired
    paired.advisor_token_path.write_text("t" * 64)
    c = client_for(paired)
    assert isinstance(c, HttpModelClient) and c.url == "http://gateway-box:8430/v1/categorize"
    assert c._headers == {"Authorization": "Bearer " + "t" * 64}
    c.close()
    dev = paired.model_copy(update={"categorizer_url": "http://localhost:9000/categorize"})
    d = client_for(dev)
    assert d.url == "http://localhost:9000/categorize" and d._headers == {}
    d.close()


def test_a_batch_waits_long_enough_for_the_categorizer_on_gateway(settings):
    """Deploy day, 2026-10-24: a batch of 50 took about 24 s on the gateway (Ollama one request at a time), and the old
    fixed 10 s wait made every batch a miss. The wait is a setting, 60 s by default."""
    paired = settings.model_copy(update={"gateway_url": "http://gateway-box:8430"})
    paired.advisor_token_path.write_text("t" * 64)
    c = client_for(paired)
    assert c.batch_timeout_s == 60.0
    c.close()
    slower = paired.model_copy(update={"categorizer_batch_timeout_s": 120.0})
    s = client_for(slower)
    assert s.batch_timeout_s == 120.0
    s.close()


def test_transaction_text_is_masked_before_ollama_and_never_goes_to_anthropic(settings):
    """Controller addition: every request goes only to the paired gateway (which asks Ollama on loopback), with digits
    masked, and nothing in the client can reach an Anthropic host."""
    import inspect

    import steward.services.categorizer_client as module

    seen = []

    def handler(request):
        seen.append((request.url.host, request.content.decode()))
        if request.url.path.endswith("/batch"):
            return httpx2.Response(200, json={"rows": [{"category": "dining", "merchant": None}] * 2})
        return httpx2.Response(200, json={"category": "dining", "merchant": None})
    c = make(handler, token="t" * 64)
    c.categorize("SQ *HARBOR GRILL 4417002918 CARD 5500005555555559", -100)
    c.categorize_batch([("HARBOR GRILL 4417002918", -1), ("ACCT 123456789012", -2)])
    assert seen and all(host == "gateway-box" for host, _ in seen)
    for _, body in seen:
        assert not any(run in body for run in ("4417002918", "5500005555555559", "123456789012"))
    assert "anthropic" not in inspect.getsource(module).lower()
    paired = settings.model_copy(update={"gateway_url": "http://gateway-box:8430"})
    paired.advisor_token_path.write_text("t" * 64)
    real = client_for(paired)
    assert "anthropic" not in real.url
    real.close()



def test_business_hint_reads_only_whole_percents():
    from steward.services.categorizer_client import business_of
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json={"rows": [
            {"category": "subscriptions", "merchant": None, "business": 87},
            {"category": "subscriptions", "merchant": None, "business": 87.5},
            {"category": "subscriptions", "merchant": None, "business": "87"},
            {"category": "subscriptions", "merchant": None, "business": 101},
            {"category": "subscriptions", "merchant": None, "business": True},
            {"category": "subscriptions", "merchant": None}]})
    hits = make(handler).categorize_batch([("NOTEFLOW PRO 4417002918", -2900)] * 6)
    assert [business_of(h) for h in hits] == [87, None, None, None, None, None]
    assert hits[0] == ("subscriptions", None, 87) and hits[5] == ("subscriptions", None)
    assert business_of(None) is None
    assert all(set(r) == {"description", "amount_cents"} and "4417002918" not in r["description"]
               for r in seen["body"]["rows"])


from steward.services.categorizer_client import Guess, features_from  # noqa: E402


def test_a_guess_is_read_only_when_advertised_and_only_if_allowed():
    """Review Focus 2."""
    body = {"rows": [{"category": "uncategorized", "merchant": None, "confidence": 0.45, "guess": "dining"},
                     {"category": "uncategorized", "merchant": None, "confidence": 0.5, "guess": "transfer"},
                     {"category": "uncategorized", "merchant": None, "confidence": 0.5, "guess": "lambos"},
                     {"category": "uncategorized", "merchant": None, "confidence": 0.55},
                     {"category": "uncategorized", "merchant": None, "confidence": "high", "guess": "home"},
                     {"category": "dining", "merchant": "Bean Cafe", "confidence": 0.9}]}
    rows = [("A", -1)] * 6
    c = make(lambda r: httpx2.Response(200, json=body))
    assert c.categorize_batch(rows) == [None, None, None, None, None, ("dining", "Bean Cafe")]   # not advertised
    c.features = frozenset({"guess", "examples"})
    out = c.categorize_batch(rows)
    assert out == [Guess("dining", 45), Guess(None, 50), Guess(None, 50), Guess(None, 55), Guess("home", None),
                   ("dining", "Bean Cafe")]
    assert not any(out[:5]) and out[5]                 # a Guess is falsy: "did the model sort it" keeps its meaning


def test_a_confidence_that_is_not_a_number_in_range_is_dropped():
    odd = [True, -0.1, 1.5, float("inf"), float("nan"), None, [0.5]]
    body = {"rows": [{"category": "uncategorized", "merchant": None, "confidence": v, "guess": "home"} for v in odd]}
    c = make(lambda r: httpx2.Response(200, text=json.dumps(body)))    # json.dumps writes Infinity and NaN; Python reads them back
    c.features = frozenset({"guess"})
    assert c.categorize_batch([("A", -1)] * len(odd)) == [Guess("home", None)] * len(odd)


def test_examples_are_masked_and_capped_before_they_leave():
    """Review Focus 3: examples go out only when advertised, through the same mask as rows, at most 40."""
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json={"rows": [{"category": "dining", "merchant": None}]})
    c = make(handler)
    examples = [(f"UNION SERVICE CENTER 4417002918 #{i}", "home") for i in range(45)]
    c.categorize_batch([("BEAN CAFE", -500)], examples)
    assert "examples" not in seen[0]                   # an old gateway never sees them
    c.features = frozenset({"examples"})
    c.categorize_batch([("BEAN CAFE", -500)], examples)
    sent = seen[1]["examples"]
    assert len(sent) == 40 and sent[0]["category"] == "home"
    assert "4417002918" not in json.dumps(sent) and all(len(e["description"]) <= 200 for e in sent)
    c.categorize_batch([("BEAN CAFE", -500)], [])
    assert "examples" not in seen[2]


def test_features_come_from_health():
    assert features_from(None) == frozenset()
    assert features_from({"categorizer": True}) == frozenset()
    assert features_from({"categorizer_features": ["guess", "examples", "later"]}) == frozenset({"guess", "examples", "later"})
    assert features_from({"categorizer_features": "guess"}) == frozenset()
