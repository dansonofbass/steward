"""The Playwright suite's fake gateway answers by the question's words and never needs a key (spec 11.5)."""
import importlib.util
from pathlib import Path

from tests.gateway.fake_anthropic import Reply

spec = importlib.util.spec_from_file_location("fake_gateway", Path(__file__).parents[1] / "web" / "e2e" / "fake_gateway.py")
fg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fg)


def body(question, results=()):
    msgs = [{"role": "user", "content": [{"type": "text", "text": question}]}, {"role": "system", "content": "ctx"}]
    for i, r in enumerate(results):
        msgs += [{"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": "x", "input": {}}]},
                 {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "{}", "is_error": r}]}]
    return {"messages": msgs}


def names(reply: Reply):
    return [b.get("name") or b["type"] for b in reply.blocks]


def test_the_script_walks_each_scripted_question():
    assert names(fg.script(body("Are we spending more on dining?"), 1)) == ["spending_by_category"]
    assert names(fg.script(body("Are we spending more on dining?", [False]), 2)) == ["text"]
    assert names(fg.script(body("Which subscriptions did we add?"), 1)) == ["recurring"]
    assert names(fg.script(body("Which subscriptions did we add?", [False]), 2)) == ["merchant_detail"]
    approved = fg.script(body("Which subscriptions did we add?", [False, False]), 3).blocks[0]["text"]
    declined = fg.script(body("Which subscriptions did we add?", [False, True]), 3).blocks[0]["text"]
    assert approved.startswith("Here they are") and declined.startswith("From totals")
    assert names(fg.script(body("Is there anything odd this month?"), 1)) == ["flags"]
    assert names(fg.script(body("How much is in savings?"), 1)) == ["text"]


def test_the_prewarm_body_gets_a_plain_answer():
    # The gateway's prewarm sends a string placeholder with no text blocks (ledger ruling P10).
    assert names(fg.script({"messages": [{"role": "user", "content": "warm"}]}, 1)) == ["text"]


def test_the_store_name_detector_tags_the_invented_store():
    (span,) = fg.StoreNameDetector().detect("Pay Bright Smile Ortho $6,400?")
    assert (span.label, span.layer) == ("[organization]", "gliner")
    assert fg.E2E_TOKEN == "e2e0" * 16
