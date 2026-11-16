from steward_boundary.canonical import canonical
from steward_boundary.text import is_outgoing_safe, is_question_safe
from steward_gateway import prompt as P


def test_the_system_prompt_is_safe_plain_and_names_nobody():
    assert is_outgoing_safe(P.SYSTEM_PROMPT)
    assert "!" not in P.SYSTEM_PROMPT
    for word in ("JR", "Alex", "Sam", "Margaret", "elder", "senior", "patient", "Ours"):
        assert word not in P.SYSTEM_PROMPT.split(), word
    assert "2026" not in P.SYSTEM_PROMPT            # no date in the cached prefix (spec 8.3)


def test_the_prefix_is_byte_identical_every_time():
    assert canonical(P.prefix()) == canonical(P.prefix())
    assert P.prefix()["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert [t["name"] for t in P.prefix()["tools"]] == sorted(t["name"] for t in P.prefix()["tools"])
    assert len(P.prefix_sha256()) == 64
    assert P.prewarm_payload() == {"prefix": "steward-advisor-6", "prefix_sha256": P.prefix_sha256(), "message": "warmup"}


def test_the_context_names_the_day_in_words():
    text = P.context_text({"today": "2026-10-20", "book_kind": "parent", "asker": "Person 3"})
    assert text == "Today is Tuesday, October 20, 2026. This is a parent book. The person asking is Person 3."
    assert is_outgoing_safe(text)


def test_the_request_body():
    msgs = [P.user_text("How much is in savings?"), P.system_message("Today is Tuesday, October 20, 2026.")]
    body = P.request_body("claude-opus-5-5", msgs)
    assert body["model"] == "claude-opus-5-5" and body["max_tokens"] == 16_000
    assert body["thinking"] == {"type": "adaptive"} and body["output_config"] == {"effort": "medium"}
    assert body["tool_choice"] == {"type": "auto"} and body["cache_control"] == {"type": "ephemeral"}
    assert body["tools"] == P.tool_definitions() and body["system"] == P.system_blocks()
    assert body["messages"] == msgs
    assert "stream" not in body and "temperature" not in body


def test_the_prewarm_body_matches_the_prefix():
    body = P.prewarm_body("claude-opus-5-5")
    assert body["max_tokens"] == 0 and "cache_control" not in body
    assert body["tools"] == P.tool_definitions() and body["system"] == P.system_blocks()
    assert body["thinking"] == {"type": "adaptive"} and body["output_config"] == {"effort": "medium"}
    assert body["messages"] == [{"role": "user", "content": "warmup"}]


def test_the_prompt_tells_claude_when_to_ask_for_store_names():
    assert "merchant_detail" in P.SYSTEM_PROMPT and "A manager must approve" in P.SYSTEM_PROMPT


HEAD = "Today is Tuesday, October 20, 2026. This is a household book. The person asking is Person 1."
CASES = [
    ({"kind": "account", "account": "Account 3"}, "It's about Account 3."),
    ({"kind": "category", "category": "dining", "month": "2026-10"},
     "It's about Eating out (category dining) in October 2026."),
    ({"kind": "plan"}, "It's about the retirement plan."),
    ({"kind": "transaction", "date": "2026-10-16", "amount_cents": -8072, "category": "uncategorized",
      "account": "Account 3"},
     "It's about one transaction: $80.72 out on October 16, 2026, category Not sorted yet (uncategorized), in Account 3."),
    ({"kind": "flag", "check": "large", "date": "2026-10-14"}, "It's about a flag from the large check on October 14, 2026."),
    ({"kind": "care", "scenario": 2, "level": "in_home_help"}, "It's about care scenario 2 (in_home_help)."),
    ({"kind": "care"}, "It's about the care projection."),
]


def test_the_context_says_what_the_question_is_about():
    base = {"today": "2026-10-20", "book_kind": "household", "asker": "Person 1"}
    assert P.context_text(base) == HEAD                         # no about: exactly as before
    for about, tail in CASES:
        text = P.context_text({**base, "about": about})
        assert text == f"{HEAD} {tail}"
        assert is_question_safe(text, issued=frozenset({"Person 1", "Account 3"}))


def test_the_prompt_says_how_to_use_the_about_line():
    assert ("When the person asked from a page in Steward, the context after the question says what it's about. Use "
            "it to choose what to look up, and still take every figure from the tools.") in P.SYSTEM_PROMPT
