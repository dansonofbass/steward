"""Spec 2026-11-05, section 7, and the plan's privacy rule: the gateway's name is for people's screens. It never
rides in what goes to Claude: not the question, not Steward's instructions, not a tool's result."""
import json

from steward import gateway_name
from tests.advisor.rig import gateway_rig
from tests.advisor.test_turn import ask, env_for, household  # noqa: F401  (household is a fixture)
from tests.gateway.fake_anthropic import Reply, text, tool_use


def test_the_gateway_name_never_reaches_claude(tmp_path, books, ours, household):
    gateway_name.configure("Zebra-Box")

    def script(body, n):
        if n == 1:
            return Reply([tool_use("toolu_01", "book_summary", {})], stop_reason="tool_use")
        return Reply([text("Person 1's net worth is about $2.4 million.")])

    with gateway_rig(tmp_path, script) as rig:
        events = ask(env_for(books, ours, household, rig.client), "What's our net worth?")
        sent = json.dumps(rig.fake.requests)
    assert events[-1]["type"] == "done" and len(rig.fake.requests) == 2
    assert "Zebra" not in sent
