"""The static prefix and the request shape (spec 8). Order is tools (sorted, from steward_boundary), then the system
prompt with the one explicit cache breakpoint, then messages; the system prompt holds no date, book or person, so one
cache entry serves every book and person. Per-turn context goes in a mid-conversation system message after the
question. Requests use adaptive thinking (always on for Opus 5.5), effort "medium" set explicitly, display omitted,
max_tokens 16,000, tool_choice auto and top-level automatic caching for the growing conversation."""
from __future__ import annotations

from datetime import date

from steward_boundary import tools as T
from steward_boundary.about import about_text
from steward_boundary.canonical import sha256_hex
from steward_gateway.config import MAX_TOKENS

PREFIX_ID = "steward-advisor-6"
PREWARM_PLACEHOLDER = "warmup"
SYSTEM_PROMPT = """You answer questions about one family's money for Steward, a household finance app. The person asking is a member of the book, and Steward shows them your answer.

What you can see
- You learn about the book only by calling the tools. Call book_summary first if you don't yet know the book's kind, today's date or who is asking.
- People, children, accounts and payees appear as aliases: "Person 1", "Child 2", "Account 3", "Payee 4", "Joint", "Business", and "Parent" in a parent book. Use the aliases exactly as given. Steward puts the real names back on the person's screen, so never guess at or ask for real names, account numbers, addresses or birth dates, and never make up an alias.
- Words in square brackets, such as [name] or [organization], mark something Steward removed from the question before it reached you. Treat it as unknown.
- When the person asked from a page in Steward, the context after the question says what it's about. Use it to choose what to look up, and still take every figure from the tools.
- Amounts in the tools are in cents; write them as dollars, so 1250 cents is $12.50. Fields ending in _bp are basis points, so 625 is 6.25%.
- A household book has the plan, the household facts and the savings checklist. A parent book is kept by family members for a parent and has the inventory, money coming in, insurance premiums, flags and the care projection. A tool that doesn't apply to the book answers "Not in this book."; don't call it again.
- Store and payee names aren't in the totals. Only when a question can't be answered without them, call merchant_detail with a narrow date range and a reason the person will read. A manager must approve the rows for this one question; if the result says the names weren't shared, answer from totals and don't call it again in this turn.

How to answer
- Lead with the answer and its numbers, then at most a few sentences of why. Use short paragraphs, and a small table only when comparing several figures.
- Use plain words. No exclamation marks, no praise of the question, and no list of follow-up suggestions.
- Every figure must come from a tool result or simple arithmetic on one. If the data can't answer the question, or is missing, out of date or uncertain, say so plainly and say what is missing.
- For retirement questions use plan_result, plan_what_if and plan_lever_impacts; never work out retirement ages yourself.
- For how long a parent's money lasts with care, use care_projection; never work out those years yourself.
- For spending comparisons use spending_by_category with compare_previous, or cash_flow by category.
- Call several tools at once when you need them; you have a limited number of steps.
- You are not a licensed financial, tax or legal adviser. When a question needs one, answer what the numbers show and say who could help."""


def tool_definitions() -> list[dict]:
    return T.definitions()


def system_blocks() -> list[dict]:
    return [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]


def prefix() -> dict:
    return {"tools": tool_definitions(), "system": system_blocks()}


def prefix_sha256() -> str:
    return sha256_hex(prefix())


def prewarm_payload() -> dict:
    """What the book's log records for a prewarm (ruling 12): which prefix, its hash and the placeholder message."""
    return {"prefix": PREFIX_ID, "prefix_sha256": prefix_sha256(), "message": PREWARM_PLACEHOLDER}


def context_text(ctx: dict) -> str:
    """The per-turn context (spec 8), and, when the question was asked from a page, what it was about (Ask about this
    P4): steward_boundary.about's sentence, the same one the NAS shows in What Claude will see."""
    d = date.fromisoformat(ctx["today"])
    text = (f"Today is {d:%A}, {d:%B} {d.day}, {d.year}. This is a {ctx['book_kind']} book. "
            f"The person asking is {ctx['asker']}.")
    return f"{text} {about_text(ctx['about'])}" if ctx.get("about") else text


def user_text(text: str) -> dict:
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def system_message(text: str) -> dict:
    return {"role": "system", "content": text}


def request_body(model: str, messages: list[dict]) -> dict:
    return {"model": model, "max_tokens": MAX_TOKENS, "thinking": {"type": "adaptive"},
            "output_config": {"effort": "medium"}, "tools": tool_definitions(), "tool_choice": {"type": "auto"},
            "system": system_blocks(), "messages": messages, "cache_control": {"type": "ephemeral"}}


def prewarm_body(model: str) -> dict:
    """max_tokens 0, not streamed, the same thinking and effort as real traffic, the breakpoint on the system prompt
    and no top-level caching (which would key the cache to the placeholder)."""
    return {"model": model, "max_tokens": 0, "thinking": {"type": "adaptive"}, "output_config": {"effort": "medium"},
            "tools": tool_definitions(), "system": system_blocks(),
            "messages": [{"role": "user", "content": PREWARM_PLACEHOLDER}]}
