"""The model loop against the fake Anthropic server, with a scripted NAS on the other side of the frames."""
import asyncio
from datetime import datetime, timezone

import anthropic
import pytest

from steward_boundary import PROTOCOL
from steward_boundary.canonical import canonical
from steward_boundary.tools import DECLINED
from steward_gateway.config import MAX_TOKENS
from steward_gateway.prices import estimate_nd, reserve_price
from steward_gateway.prompt import request_body
from steward_gateway.config import FALLBACK_BETA
from steward_gateway.ledger import Ledger
from steward_gateway.loop import TurnDeps, run_turn
from steward_gateway.mac import load_or_create_key, mac
from steward_gateway.redact.patterns import PatternDetector
from tests.gateway.fake_anthropic import FakeAnthropic, Reply, text, thinking, tool_use
from tests.gateway.fakes import NameListDetector
from tests.servers import serve_in_thread
from tests.waiting import CEILING

NOW = datetime(2026, 10, 20, 17, 0, tzinfo=timezone.utc)
ACCOUNTS = {"accounts": [{"account": "Account 1", "account_type": "checking", "tax_treatment": "none", "owner": "Joint",
                          "balance_cents": 1_450_000, "as_of": "2026-10-12", "arrives": "feed", "sync_behind": False,
                          "active": True}]}


def start_frame(question="Are we spending more on dining than last year?", history=(), book_id=1, kind="household",
                asker="Person 1", today="2026-10-20"):
    return {"type": "start", "protocol": PROTOCOL, "turn_id": "t_00000000000000a1", "book_id": book_id, "user_id": 2,
            "question": question, "context": {"today": today, "book_kind": kind, "asker": asker},
            "history": list(history), "fingerprints": {"salt": "2" * 32, "hashes": []}, "issued": []}


class FakeNas:
    def __init__(self, results=None, record_reply="recorded", cancel=False):
        self.frames, self.queue = [], None
        self.results = results or (lambda calls: [{"id": c["id"], "name": c["name"], "content": ACCOUNTS, "error": None}
                                                  for c in calls])
        self.record_reply, self.cancel = record_reply, cancel

    async def send(self, frame):
        self.queue = self.queue or asyncio.Queue()
        self.frames.append(frame)
        if frame["type"] == "record":
            await self.queue.put({"type": self.record_reply, "seq": frame["seq"]})
        elif frame["type"] == "tool_calls":
            await self.queue.put({"type": "cancel", "reason": "not_a_member"} if self.cancel else
                                 {"type": "tool_results", "seq": frame["seq"], "results": self.results(frame["calls"])})

    async def receive(self, kinds, timeout):
        return await asyncio.wait_for(self.queue.get(), timeout)

    def kinds(self):
        return [f["type"] for f in self.frames]

    def of(self, kind):
        return [f for f in self.frames if f["type"] == kind]


def turn(cfg, script, start=None, nas=None, cap_cents=1000, stopped=False, with_client=True, detectors=None):
    fake, nas = FakeAnthropic(script), nas or FakeNas()
    ledger = Ledger(cfg.ledger_path, cfg.timezone, cap_cents, cfg.max_cap_cents, cfg.default_model)
    key = load_or_create_key(cfg.history_key_path)
    with serve_in_thread(fake.app()) as url:
        async def go():
            client = anthropic.AsyncAnthropic(api_key="test-key-not-real", base_url=url, max_retries=0) if with_client else None
            deps = TurnDeps(config=cfg, ledger=ledger, client=client, mac_key=key, stopped=lambda: stopped, now=lambda: NOW,
                            detectors=[PatternDetector(), NameListDetector()] if detectors is None else detectors)
            try:
                return await run_turn(start or start_frame(), nas, deps)
            finally:
                if client is not None:
                    await client.close()
        frame = asyncio.run(go())
    return frame, fake, nas, ledger, key


def test_a_plain_answer_is_recorded_first_then_streamed(gw_cfg):
    done, fake, nas, ledger, _ = turn(gw_cfg, lambda b, n: Reply([text("You spent $812.40 on dining in September.")]))
    assert done["stop"] == "end_turn" and done["line"] is None and done["requests"] == 1 and done["cost_nd"] > 0
    kinds = nas.kinds()
    assert kinds[:3] == ["redacted", "record", "sent"] and kinds[-2:] == ["assistant", "done"]
    assert "".join(f["delta"] for f in nas.of("text")) == "You spent $812.40 on dining in September."
    assert [p["part"] for p in nas.of("record")[0]["parts"]] == ["question", "system"]
    body = fake.requests[0]
    assert nas.of("record")[0]["model"] == body["model"]               # the sent log names the model (PRIV-15)
    assert body["model"] == "claude-opus-5-5" and body["max_tokens"] == 16_000 and body["stream"] is True
    assert body["thinking"] == {"type": "adaptive"} and body["output_config"] == {"effort": "medium"}
    assert body["fallbacks"] == "default" and body["tool_choice"] == {"type": "auto"}
    assert body["cache_control"] == {"type": "ephemeral"}
    assert FALLBACK_BETA in fake.headers[0]["anthropic-beta"]
    assert body["messages"][-2] == {"role": "user", "content": [{"type": "text",
                                                                 "text": "Are we spending more on dining than last year?"}]}
    assert body["messages"][-1] == {"role": "system", "content": "Today is Tuesday, October 20, 2026. This is a "
                                                                 "household book. The person asking is Person 1."}
    assert ledger.state(NOW, gw_cfg)["spent_cents"] >= 0 and ledger.state(NOW, gw_cfg)["reserved_cents"] == 0


def test_the_question_is_redacted_before_it_is_checked_and_sent(gw_cfg):
    q = "Did Tom Becker get the check? Write to tom@example.com"
    done, fake, nas, _, _ = turn(gw_cfg, lambda b, n: Reply([text("I can't see that.")]), start_frame(question=q))
    assert nas.of("redacted")[0]["text"] == "Did [name] get the check? Write to [email]"
    assert fake.requests[0]["messages"][-2]["content"][0]["text"] == "Did [name] get the check? Write to [email]"


def test_a_tool_round_keeps_thinking_and_records_the_result(gw_cfg):
    def script(body, n):
        if n == 1:
            return Reply([thinking("sig-1"), tool_use("toolu_01", "accounts", {"include_closed": False})],
                         stop_reason="tool_use")
        return Reply([text("Account 1 holds $14,500.00.")])
    done, fake, nas, _, _ = turn(gw_cfg, script)
    assert done["stop"] == "end_turn" and done["requests"] == 2
    assert nas.of("status")[0]["tool"] == "accounts"
    assert nas.of("tool_calls")[0]["calls"] == [{"id": "toolu_01", "name": "accounts", "input": {"include_closed": False}}]
    second = nas.of("record")[1]["parts"]
    assert second == [{"part": "tool_result", "payload": {"tool_use_id": "toolu_01", "name": "accounts",
                                                          "is_error": False, "content": ACCOUNTS},
                       "sha256": second[0]["sha256"], "bytes": second[0]["bytes"]}]
    msgs = fake.requests[1]["messages"]
    assert msgs[-2]["role"] == "assistant"
    assert msgs[-2]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig-1"}
    assert msgs[-1] == {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_01",
                                                     "content": canonical(ACCOUNTS).decode(), "is_error": False}]}


def test_the_prefix_is_identical_across_books_people_and_days(gw_cfg):
    reply = lambda b, n: Reply([text("ok")])
    _, a, _, _, _ = turn(gw_cfg, reply, start_frame())
    _, b, _, _, _ = turn(gw_cfg, reply, start_frame(book_id=3, kind="parent", asker="Person 3", today="2026-11-02"))
    for field in ("tools", "system"):
        assert canonical(a.requests[0][field]) == canonical(b.requests[0][field])
    assert a.requests[0]["messages"][-1] != b.requests[0]["messages"][-1]


def test_eight_steps_then_a_plain_stop(gw_cfg):
    script = lambda b, n: Reply([tool_use(f"toolu_{n:02d}", "accounts", {"include_closed": False})], stop_reason="tool_use")
    done, fake, nas, _, _ = turn(gw_cfg, script)
    assert done["stop"] == "steps" and done["line"] == "I stopped after 8 steps. Try asking about one part of this at a time."
    assert len(fake.requests) == 8 and len(nas.of("tool_calls")) == 7


def test_a_check_stops_the_turn_and_nothing_more_is_sent(gw_cfg):
    holdings = {"holdings": [{"symbol": "a@b.co", "asset_class": "other", "account": "Account 1", "value_cents": 1,
                              "cost_basis_cents": None, "as_of": "2026-10-01"}], "totals_by_asset_class": []}
    nas = FakeNas(results=lambda calls: [{"id": c["id"], "name": "holdings", "content": holdings, "error": None}
                                         for c in calls])
    script = lambda b, n: Reply([tool_use("toolu_01", "holdings", {})], stop_reason="tool_use")
    done, fake, nas, _, _ = turn(gw_cfg, script, nas=nas)
    # a symbol is proven by its schema (letters only), so the schema check is the one that fires
    assert (done["stop"], done["check"], done["path"]) == ("stopped_check", "schema", "parts[0].content.holdings[0].symbol")
    assert len(fake.requests) == 1 and len(nas.of("record")) == 1


def test_an_approvable_hash_still_stops_an_ordinary_result(gw_cfg):
    """Plan B Task 1: payee hashes travel apart in `approvable`, but until an approved merchant_rows part exists every
    part is scanned against both sets, so splitting them lets nothing new through."""
    from steward_boundary.fingerprint import hashes_for
    holdings = {"holdings": [{"symbol": "SBOX", "asset_class": "other", "account": "Account 1", "value_cents": 1,
                              "cost_basis_cents": None, "as_of": "2026-10-01"}], "totals_by_asset_class": []}
    nas = FakeNas(results=lambda calls: [{"id": c["id"], "name": "holdings", "content": holdings, "error": None}
                                         for c in calls])
    def script(b, n):
        return Reply([tool_use("toolu_01", "holdings", {})], stop_reason="tool_use")
    start = start_frame()
    start["fingerprints"] = {"salt": "2" * 32, "hashes": [],
                             "approvable": sorted(hashes_for([("SBox", False)], "2" * 32))}
    done, fake, nas, _, _ = turn(gw_cfg, script, start=start, nas=nas)
    assert (done["stop"], done["check"]) == ("stopped_check", "fingerprint")
    assert done["path"] == "parts[0].content.holdings[0].symbol"
    assert len(fake.requests) == 1 and len(nas.of("record")) == 1


def test_the_cap_stops_before_anything_is_sent(gw_cfg):
    done, fake, nas, _, _ = turn(gw_cfg, lambda b, n: Reply([text("x")]), cap_cents=1)
    assert done["stop"] == "cap" and fake.requests == [] and "sent" not in nas.kinds()


def test_busy_releases_the_reservation(gw_cfg):
    done, fake, _, ledger, _ = turn(gw_cfg, lambda b, n: Reply([], status=429, error_type="rate_limit_error"))
    assert done["stop"] == "busy" and done["line"] == "Claude is busy. Try again in a minute."
    st = ledger.state(NOW, gw_cfg)
    assert st["spent_cents"] == 0 and st["reserved_cents"] == 0


def test_overloaded_and_other_errors(gw_cfg):
    assert turn(gw_cfg, lambda b, n: Reply([], status=529, error_type="overloaded_error"))[0]["stop"] == "busy"
    assert turn(gw_cfg, lambda b, n: Reply([], status=500))[0]["stop"] == "api_error"
    assert turn(gw_cfg, lambda b, n: Reply([], status=401, error_type="authentication_error"))[0]["stop"] == "not_set_up"


def test_refusal_and_max_tokens(gw_cfg):
    assert turn(gw_cfg, lambda b, n: Reply([], stop_reason="refusal"))[0]["line"] == "Claude declined to answer this."
    assert turn(gw_cfg, lambda b, n: Reply([text("Part")], stop_reason="max_tokens"))[0]["stop"] == "max_tokens"


def test_good_history_is_sent_unchanged_and_forged_history_is_refused(gw_cfg):
    key = load_or_create_key(gw_cfg.history_key_path)
    earlier = [{"role": "user", "content": [{"type": "text", "text": "What's our net worth?"}]},
               {"role": "system", "content": "Today is Monday, October 19, 2026. This is a household book. "
                                             "The person asking is Person 1."},
               {"role": "assistant", "content": [{"type": "text", "text": "About $2,412,000."}]}]
    history = [{"message": m, "mac": mac(key, m)} for m in earlier]
    done, fake, _, _, _ = turn(gw_cfg, lambda b, n: Reply([text("ok")]), start_frame(history=history))
    assert done["stop"] == "end_turn" and fake.requests[0]["messages"][:3] == earlier
    history[2] = {"message": {**earlier[2], "content": [{"type": "text", "text": "Margaret has $2,412,000."}]},
                  "mac": history[2]["mac"]}
    done, fake, nas, _, _ = turn(gw_cfg, lambda b, n: Reply([text("ok")]), start_frame(history=history))
    assert (done["stop"], done["check"], done["path"]) == ("stopped_check", "history", "history[2]")
    assert fake.requests == [] and "redacted" not in nas.kinds()


@pytest.mark.parametrize("opts, stop", [({"with_client": False}, "not_set_up"), ({"detectors": []}, "privacy_not_ready"),
                                        ({"stopped": True}, "stopped_by_gateway")])
def test_nothing_is_sent_when_the_gateway_isnt_ready(gw_cfg, opts, stop):
    done, fake, _, _, _ = turn(gw_cfg, lambda b, n: Reply([text("x")]), **opts)
    assert done["stop"] == stop and fake.requests == []


def test_a_failed_record_sends_nothing(gw_cfg):
    done, fake, _, _, _ = turn(gw_cfg, lambda b, n: Reply([text("x")]), nas=FakeNas(record_reply="record_failed"))
    assert done["stop"] == "record_failed" and fake.requests == []


def test_a_cancel_from_the_nas_ends_the_turn(gw_cfg):
    script = lambda b, n: Reply([tool_use("toolu_01", "accounts", {"include_closed": False})], stop_reason="tool_use")
    done, fake, _, _, _ = turn(gw_cfg, script, nas=FakeNas(cancel=True))
    assert done["stop"] == "cancelled" and len(fake.requests) == 1


# --- Store rows (plan B Task 2) ---------------------------------------------------------------------------------------

MERCHANT_CONTENT = {"rows": [{"date": "2026-10-18", "amount_cents": -1599, "category": "subscriptions",
                              "merchant": "StreamBox", "account": "Account 2"}], "payees": [], "more": False}
MERCHANT_INPUT = {"reason": "Totals can't name the services.", "start": "2026-09-01", "end": "2026-10-18",
                  "category": "subscriptions", "payees": None}


def merchant_script(body, n):
    if n == 1:
        return Reply([tool_use("toolu_m1", "merchant_detail", MERCHANT_INPUT)], stop_reason="tool_use")
    return Reply([text("StreamBox costs $15.99 a month.")])


def answering(content=MERCHANT_CONTENT, error=None):
    return lambda calls: [{"id": c["id"], "name": c["name"], "content": content, "error": error} for c in calls]


def test_approved_store_rows_are_recorded_as_merchant_rows(gw_cfg):
    done, fake, nas, _, _ = turn(gw_cfg, merchant_script, nas=FakeNas(results=answering()))
    assert done["stop"] == "end_turn"
    second = nas.of("record")[1]
    assert [p["part"] for p in second["parts"]] == ["merchant_rows"]
    assert second["parts"][0]["payload"]["content"] == MERCHANT_CONTENT


def test_approved_store_rows_go_with_the_conversations_later_questions(gw_cfg):
    """Gate finding PRIV-9: the approved rows are part of the conversation's history, so a follow-up question resends
    them with no new card; nothing new is disclosed, but the docs must not say the names go for one question only."""
    from tests.public_docs import ROOT, flat, ledger_cells
    done, _, nas, _, _ = turn(gw_cfg, merchant_script, nas=FakeNas(results=answering()))
    assert done["stop"] == "end_turn"
    # What the NAS stores as the conversation: each "sent" frame's messages and each assistant message, in order.
    history = [m for f in nas.frames if f["type"] in ("sent", "assistant")
               for m in (f["messages"] if f["type"] == "sent" else [{"message": f["message"], "mac": f["mac"]}])]
    follow_up = start_frame(question="And how does that compare with our savings rate?", history=history)
    done, fake, nas, _, _ = turn(gw_cfg, lambda b, n: Reply([text("About the same.")]), start=follow_up)
    assert done["stop"] == "end_turn"
    assert "StreamBox" in canonical(fake.requests[0]["messages"]).decode()
    assert [p["part"] for f in nas.of("record") for p in f["parts"]] == ["question", "system"]   # no card, no new rows
    for text_ in (ledger_cells("P6")[1], (ROOT / "docs/explanations/privacy.md").read_text(encoding="utf-8")):
        assert "approved rows stay in that conversation" in flat(text_)


def test_a_declined_store_name_call_goes_as_an_ordinary_error_result(gw_cfg):
    done, fake, nas, _, _ = turn(gw_cfg, merchant_script, nas=FakeNas(results=answering(None, DECLINED)))
    assert done["stop"] == "end_turn"
    assert [p["part"] for p in nas.of("record")[1]["parts"]] == ["tool_result"]


def test_an_empty_store_name_result_goes_as_an_ordinary_tool_result(gw_cfg):
    """Preflight ruling P1: a merchant_detail call that finds no rows and no payees has no card (plan B ruling 5),
    so it isn't approved store rows and goes as a plain tool_result."""
    empty = {"rows": [], "payees": [], "more": False}
    done, fake, nas, _, _ = turn(gw_cfg, merchant_script, nas=FakeNas(results=answering(empty)))
    assert done["stop"] == "end_turn"
    second = nas.of("record")[1]
    assert [p["part"] for p in second["parts"]] == ["tool_result"]
    assert second["parts"][0]["payload"]["content"] == empty


def test_a_result_under_another_tools_name_is_refused(gw_cfg):
    """Task 6.5: a result must carry its call's name, so rows can't be relabelled into the looser store-rows checks
    (or a store result hidden under another tool's name)."""
    relabel = lambda calls: [{"id": c["id"], "name": "merchant_detail", "content": MERCHANT_CONTENT, "error": None}
                             for c in calls]
    script = lambda b, n: Reply([tool_use("toolu_a", "accounts", {"include_closed": False})], stop_reason="tool_use") \
        if n == 1 else Reply([text("Done.")])
    done, fake, nas, _, _ = turn(gw_cfg, script, nas=FakeNas(results=relabel))
    assert done["stop"] == "bad_request" and len(fake.requests) == 1
    assert len(nas.of("record")) == 1


def test_a_cancel_while_a_card_waits_ends_the_turn_with_nothing_reserved(gw_cfg):
    """Task 6.5: when the NAS cancels during a card's wait (Stop, the browser gone, the timeout), the turn ends at once
    and no reservation stays open; the only request sent was the one already settled."""
    class CancellingNas(FakeNas):
        async def send(self, frame):
            if frame["type"] == "tool_calls":
                self.frames.append(frame)
                self.queue = self.queue or asyncio.Queue()
                await self.queue.put({"type": "cancel", "reason": "stopped"})
                return
            await super().send(frame)

    done, fake, nas, ledger, _ = turn(gw_cfg, merchant_script, nas=CancellingNas())
    assert done["stop"] == "cancelled" and len(fake.requests) == 1
    assert statuses(ledger) == ["settled"] and nothing_open(ledger, gw_cfg)


def test_the_gateway_waits_longer_for_a_card_than_for_other_results(gw_cfg):
    waits = []

    class TimingNas(FakeNas):
        async def receive(self, kinds, timeout):
            if "tool_results" in kinds:
                waits.append(timeout)
            return await super().receive(kinds, timeout)

    turn(gw_cfg, merchant_script, nas=TimingNas(results=answering()))
    turn(gw_cfg, lambda b, n: Reply([tool_use("toolu_a", "accounts", {"include_closed": False})], stop_reason="tool_use")
         if n == 1 else Reply([text("Done.")]), nas=TimingNas())
    assert waits == [660.0, 180.0]


# --- Reservations: sized on the full request body, released on every failure path (preflight ruling 4), except a
# request that was sent and then cancelled or dropped with no usage back, which counts in full (chunk 2 ruling) ------


def statuses(ledger):
    with ledger._conn() as c:
        return [r[0] for r in c.execute("SELECT status FROM spend ORDER BY id")]


def nothing_open(ledger, cfg):
    st = ledger.state(NOW, cfg)
    return st["reserved_cents"] == 0 and "reserved" not in statuses(ledger)


class SpyLedger(Ledger):
    reserved: list = None

    def reserve(self, **kw):
        self.reserved = (self.reserved or []) + [kw["estimate_nd"]]
        return super().reserve(**kw)


class Stream:
    """A stand-in for client.beta.messages.stream(): what the SDK would do, scripted per test."""

    def __init__(self, enter=None, events=()):
        self.enter, self.events = enter, events

    async def __aenter__(self):
        if self.enter:
            await self.enter()
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            for e in self.events:
                yield e()
        return gen()


class StubClient:
    def __init__(self, make):
        self.beta = type("B", (), {"messages": type("M", (), {"stream": staticmethod(make)})})()


def run_stub(cfg, make, nas=None, reply_timeout=180.0):
    ledger = SpyLedger(cfg.ledger_path, cfg.timezone, 1000, cfg.max_cap_cents, cfg.default_model)
    deps = TurnDeps(config=cfg, ledger=ledger, client=StubClient(make), mac_key=load_or_create_key(cfg.history_key_path),
                    stopped=lambda: False, now=lambda: NOW, detectors=[PatternDetector(), NameListDetector()],
                    reply_timeout=reply_timeout)
    return ledger, deps, nas or FakeNas()


def test_the_reservation_is_the_estimate_over_the_full_request_body(gw_cfg):
    def script(body, n):
        if n == 1:
            return Reply([tool_use("toolu_01", "accounts", {"include_closed": False})], stop_reason="tool_use")
        return Reply([text("done")])
    ledger = SpyLedger(gw_cfg.ledger_path, gw_cfg.timezone, 1000, gw_cfg.max_cap_cents, gw_cfg.default_model)
    fake = FakeAnthropic(script)
    deps_kw = dict(config=gw_cfg, ledger=ledger, mac_key=load_or_create_key(gw_cfg.history_key_path),
                   stopped=lambda: False, now=lambda: NOW, detectors=[PatternDetector(), NameListDetector()])
    with serve_in_thread(fake.app()) as url:
        async def go():
            client = anthropic.AsyncAnthropic(api_key="test-key-not-real", base_url=url, max_retries=0)
            try:
                return await run_turn(start_frame(), FakeNas(), TurnDeps(client=client, **deps_kw))
            finally:
                await client.close()
        asyncio.run(go())
    price = reserve_price(gw_cfg, gw_cfg.default_model)
    for body, reserved in zip(fake.requests, ledger.reserved):
        sent = {k: v for k, v in body.items() if k not in ("stream", "fallbacks")}
        assert reserved == estimate_nd(len(canonical(sent)), MAX_TOKENS, price)
        assert sent == request_body(sent["model"], sent["messages"])
    assert len(ledger.reserved) == 2 and ledger.reserved[1] > ledger.reserved[0]


def test_a_record_that_never_comes_back_releases_the_reservation(gw_cfg):
    class Silent(FakeNas):
        async def send(self, frame):
            self.queue = self.queue or asyncio.Queue()
            self.frames.append(frame)
    ledger, deps, nas = run_stub(gw_cfg, lambda **kw: pytest.fail("nothing may be sent"), Silent(), reply_timeout=0.05)
    done = asyncio.run(run_turn(start_frame(), nas, deps))
    assert done["stop"] == "dropped" and "sent" not in nas.kinds()
    assert statuses(ledger) == ["released"] and nothing_open(ledger, gw_cfg)


def test_a_failed_record_releases_the_reservation(gw_cfg):
    ledger, deps, nas = run_stub(gw_cfg, lambda **kw: pytest.fail("nothing may be sent"),
                                 FakeNas(record_reply="record_failed"))
    assert asyncio.run(run_turn(start_frame(), nas, deps))["stop"] == "record_failed"
    assert statuses(ledger) == ["released"] and nothing_open(ledger, gw_cfg)


@pytest.mark.parametrize("status, kind", [(429, "rate_limit_error"), (500, "api_error"), (401, "authentication_error")])
def test_api_errors_release_the_reservation(gw_cfg, status, kind):
    ledger = turn(gw_cfg, lambda b, n: Reply([], status=status, error_type=kind))[3]
    assert statuses(ledger) == ["released"] and nothing_open(ledger, gw_cfg)


def test_a_dead_connection_releases_the_reservation(gw_cfg):
    def refuse(**kw):
        raise anthropic.APIConnectionError(request=None)
    ledger, deps, nas = run_stub(gw_cfg, refuse)
    assert asyncio.run(run_turn(start_frame(), nas, deps))["stop"] == "api_error"
    assert statuses(ledger) == ["released"] and nothing_open(ledger, gw_cfg)


def test_a_turn_cancelled_after_sending_counts_in_full(gw_cfg):
    entered = asyncio.Event()

    async def hang():
        entered.set()                           # the request is in flight (sent and recorded just before it)
        await asyncio.Event().wait()
    ledger, deps, nas = run_stub(gw_cfg, lambda **kw: Stream(enter=hang))

    async def go():
        task = asyncio.create_task(run_turn(start_frame(), nas, deps))
        await asyncio.wait_for(entered.wait(), CEILING)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(go())
    assert statuses(ledger) == ["settled"] and nothing_open(ledger, gw_cfg)
    # The NAS is told what the cancelled request was charged, so the turn shows its real cost (final review, 1).
    (done,) = nas.of("done")
    assert (done["stop"], done["requests"], done["cost_nd"]) == ("cancelled", 1, ledger.reserved[0])


def test_an_unexpected_exception_while_sending_counts_in_full(gw_cfg):
    async def boom():
        raise RuntimeError("the SDK broke")
    ledger, deps, nas = run_stub(gw_cfg, lambda **kw: Stream(enter=boom))
    with pytest.raises(RuntimeError):
        asyncio.run(run_turn(start_frame(), nas, deps))
    assert statuses(ledger) == ["settled"] and nothing_open(ledger, gw_cfg)


def test_a_socket_that_dies_before_the_sent_frame_releases_the_reservation(gw_cfg):
    class Dies(FakeNas):
        async def send(self, frame):
            await super().send(frame)
            if frame["type"] == "sent":
                raise ConnectionError("the NAS closed the socket")
    ledger, deps, nas = run_stub(gw_cfg, lambda **kw: pytest.fail("nothing may be sent"), Dies())
    with pytest.raises(ConnectionError):
        asyncio.run(run_turn(start_frame(), nas, deps))
    assert statuses(ledger) == ["released"] and nothing_open(ledger, gw_cfg)


def test_a_stream_that_drops_before_its_first_event_counts_in_full(gw_cfg):
    def die():
        raise anthropic.APIConnectionError(request=None)
    ledger, deps, nas = run_stub(gw_cfg, lambda **kw: Stream(events=[die]))
    assert asyncio.run(run_turn(start_frame(), nas, deps))["stop"] == "api_error"
    assert statuses(ledger) == ["settled"] and nothing_open(ledger, gw_cfg)


def test_a_stream_that_fails_midway_is_charged_in_full_and_nothing_stays_reserved(gw_cfg):
    def die():
        raise anthropic.APIConnectionError(request=None)
    ledger, deps, nas = run_stub(gw_cfg, lambda **kw: Stream(events=[lambda: type("E", (), {"type": "ping"})(), die]))
    done = asyncio.run(run_turn(start_frame(), nas, deps))
    assert done["stop"] == "api_error"
    assert statuses(ledger) == ["settled"] and nothing_open(ledger, gw_cfg)
    assert ledger.state(NOW, gw_cfg)["spent_cents"] > 0
    assert (done["requests"], done["cost_nd"]) == (1, ledger.reserved[0])      # the done frame carries the charge


# --- Turn logs carry counts and ids through the scrub filter (final review, finding 8) -------------------------------
def _gateway_log(caplog):
    import logging

    from steward_gateway.logs import ScrubFilter
    caplog.handler.addFilter(ScrubFilter())
    caplog.set_level(logging.INFO, logger="steward_gateway")
    return caplog


def test_a_turns_logs_carry_its_counts_and_ids(gw_cfg, caplog):
    import re
    _gateway_log(caplog)
    done = turn(gw_cfg, lambda b, n: Reply([text("You spent $812.40 on dining.")]))[0]
    out = caplog.text
    assert "[values not logged]" not in out
    assert re.search(r"turn\.request turn_id=t_00000000000000a1 step=1 model=claude-opus-5-5 input_tokens=\d+ "
                     r"cache_write_tokens=\d+ cache_read_tokens=\d+ output_tokens=\d+ cost_nd=\d+", out), out
    assert re.search(rf"turn\.done turn_id=t_00000000000000a1 stop=end_turn requests=1 cost_nd={done['cost_nd']} "
                     r"ms=\d+", out), out
    assert "812" not in out and "dining" not in out


def test_a_failed_request_logs_its_status_and_request_id(gw_cfg, caplog):
    _gateway_log(caplog)
    turn(gw_cfg, lambda b, n: Reply([], status=500))
    assert ("turn.request_failed turn_id=t_00000000000000a1 step=1 status=500 request_id=req_fake_1 "
            "error_type=InternalServerError") in caplog.text, caplog.text


def test_a_refused_request_logs_anthropics_reason(gw_cfg, caplog):
    _gateway_log(caplog)
    turn(gw_cfg, lambda b, n: Reply([], status=400, error_type="invalid_request_error",
                                    error_message="messages.0.content:  Input should be a valid\nlist"))
    assert ("error_type=BadRequestError error_kind=invalid_request_error "
            "error_message=messages.0.content: Input should be a valid list") in caplog.text, caplog.text


def test_a_refusal_with_another_body_logs_no_reason(gw_cfg, caplog):
    _gateway_log(caplog)
    turn(gw_cfg, lambda b, n: Reply([], status=400, error_body=["not", "an", "error"]))
    assert "turn.request_failed" in caplog.text and "error_type=BadRequestError" in caplog.text
    assert "error_message" not in caplog.text and "error_kind" not in caplog.text, caplog.text


def test_a_dead_connection_logs_its_error_type(gw_cfg, caplog):
    def refuse(**kw):
        raise anthropic.APIConnectionError(request=None)
    _gateway_log(caplog)
    ledger, deps, nas = run_stub(gw_cfg, refuse)
    asyncio.run(run_turn(start_frame(), nas, deps))
    assert "turn.request_failed turn_id=t_00000000000000a1 step=1 error_type=APIConnectionError" in caplog.text


def test_models_that_dont_load_log_the_error_type(caplog, monkeypatch):
    import sys
    from types import ModuleType
    _gateway_log(caplog)
    broken = ModuleType("gliner")                      # importing GLiNER from it raises ImportError
    monkeypatch.setitem(sys.modules, "gliner", broken)
    monkeypatch.setitem(sys.modules, "torch", ModuleType("torch"))
    from steward_gateway.redact import load_real_detectors
    assert load_real_detectors()[0] == []
    assert "redaction.load_failed error_type=ImportError" in caplog.text, caplog.text


def test_a_start_on_another_protocol_is_refused_and_nothing_is_recorded(gw_cfg):
    """Ask about this P11: an older NAS's frame ends bad_request before redaction, recording or any request."""
    frame, fake, nas, _, _ = turn(gw_cfg, lambda body, n: Reply([text("never sent")]),
                                  start={**start_frame(), "protocol": PROTOCOL - 1})
    assert (frame["stop"], frame["line"]) == ("bad_request", "Claude couldn't answer just now.")
    assert nas.kinds() == ["done"] and fake.requests == []


def test_the_about_line_is_in_the_context_part_and_recorded_first(gw_cfg):
    start = start_frame()
    start["context"] = {**start["context"], "about": {"kind": "category", "category": "dining", "month": "2026-10"}}
    frame, fake, nas, _, _ = turn(gw_cfg, lambda body, n: Reply([text("You spent $812.40.")]), start=start)
    assert frame["stop"] == "end_turn"
    system = next(p for p in nas.of("record")[0]["parts"] if p["part"] == "system")
    assert system["payload"]["text"].endswith(" It's about Eating out (category dining) in October 2026.")
    assert fake.requests[0]["messages"][1] == {"role": "system", "content": system["payload"]["text"]}


@pytest.mark.parametrize("about, identifier", [
    ({"kind": "care", "scenario": 2, "level": "memory_care"}, ("Sunrise Memory Care", True)),
    ({"kind": "care"}, ("Sunrise Memory Care", True)),
    ({"kind": "category", "category": "entertainment", "month": "2026-10"}, ("Fun", False)),
], ids=["care-scenario", "care", "category"])
def test_an_identifier_that_shares_the_about_lines_words_doesnt_stop_the_first_request(gw_cfg, about, identifier):
    """Argon follow-up 1: a parent book's contact "Sunrise Memory Care", or an account named "Fun", fingerprints words
    the about sentence is made of. The sentence is typed vocabulary (protocol.ABOUT), so its words aren't
    fingerprinted; the question still is."""
    from steward_boundary.fingerprint import hashes_for
    start = start_frame(question="Is this normal?", kind="parent" if about["kind"] == "care" else "household")
    start["context"] = {**start["context"], "about": about}
    start["fingerprints"] = {"salt": "2" * 32, "hashes": sorted(hashes_for([identifier], "2" * 32))}
    frame, fake, nas, _, _ = turn(gw_cfg, lambda body, n: Reply([text("Yes.")]), start=start)
    assert (frame["stop"], frame["check"], frame["path"]) == ("end_turn", None, None)
    start["question"] = f"Is {identifier[0].split()[0]} higher than usual?"
    frame, fake, nas, _, _ = turn(gw_cfg, lambda body, n: Reply([text("never sent")]), start=start)
    assert (frame["stop"], frame["check"], frame["path"]) == ("stopped_check", "fingerprint", "parts[0].text")
    assert fake.requests == []


def test_a_care_about_turn_that_calls_care_projection_completes(gw_cfg):
    """Review of Argon follow-up 1: the care_projection result carries the same words as enums (level "memory_care"),
    so with the contact "Sunrise Memory Care" the turn must get past the tool result too, not just the first request."""
    from steward_boundary.fingerprint import hashes_for
    from tests.gateway.test_checks import CARE_RESULT
    start = start_frame(question="How long does the money last?", kind="parent")
    start["context"] = {**start["context"], "about": {"kind": "care", "scenario": 1, "level": "memory_care"}}
    start["fingerprints"] = {"salt": "2" * 32, "hashes": sorted(hashes_for([("Sunrise Memory Care", True)], "2" * 32))}
    nas = FakeNas(results=lambda calls: [{"id": c["id"], "name": c["name"], "content": CARE_RESULT, "error": None}
                                         for c in calls])

    def script(body, n):
        if n == 1:
            return Reply([tool_use("toolu_c1", "care_projection", {})], stop_reason="tool_use")
        return Reply([text("It lasts until 2031.")])
    frame, fake, nas, _, _ = turn(gw_cfg, script, start=start, nas=nas)
    assert (frame["stop"], frame["check"], frame["path"]) == ("end_turn", None, None)
    assert len(fake.requests) == 2
    assert [p["part"] for p in nas.of("record")[1]["parts"]] == ["tool_result"]
