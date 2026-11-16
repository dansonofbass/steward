"""Stand-ins for the real models in tests that must run without a GPU or the models group (ruling 8). The real
GLiNER-PII and Presidio run in tests/gateway/test_models_eval.py under `-m models`."""
from __future__ import annotations

import re

from steward_gateway.redact import Span

# Third-party names that appear in the fictional PII set but in no book (spec 11.2): the model layer's job.
# "Jonah Wexler" is added to the plan's list (preflight ruling 11) so Task 25's whole THIRD_PARTY list is covered.
THIRD_PARTY_NAMES = ("Tom Becker", "Tom", "Dr. Alvarez", "Alvarez", "Priya Nair", "Priya", "Coach Dunmore", "Dunmore",
                     "Aunt Rosalind", "Rosalind", "Greenfield Pediatrics", "Hollis & Crane LLP", "Jonah Wexler", "Jonah",
                     "Wexler")


class NameListDetector:
    """Tags exact, case-insensitive matches of a fixed list of fictional names, the way GLiNER would."""
    name = "gliner"

    def __init__(self, names=THIRD_PARTY_NAMES):
        alts = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
        self._re = re.compile(rf"(?<![\w])(?:{alts})(?![\w])", re.IGNORECASE)

    def detect(self, text: str) -> list[Span]:
        # Every hit is a person: GLiNER no longer reads organizations (ruling of 2026-10-24), and the real model reads
        # an unknown firm's name as a person when it reads it at all.
        return [Span(m.start(), m.end(), "[name]", "gliner") for m in self._re.finditer(text)]


class FakeOllama:
    """Stands in for steward_gateway.ollama.Ollama (the title model). Every gateway a test builds gets one unless the
    test passes its own (tests/conftest.py), so no test reaches the real Ollama the gateway runs on 127.0.0.1:11434."""

    def __init__(self, title=None, up=True, accelerated=None):
        self._title, self.up, self.asked, self._accelerated = title, up, [], accelerated

    async def answering(self):
        return self.up

    async def accelerated(self):
        return self._accelerated

    async def title(self, text):
        self.asked.append(text)
        return self._title

    async def close(self):
        pass


class FakeCategorizer:
    """Stands in for steward_gateway.categorize.Categorizer: answers from a function of the description."""

    def __init__(self, answers=None, away=False, ready=True):
        from steward_gateway.categorize import Answer
        self.answer = answers or (lambda d: Answer("dining", None) if "CAFE" in d else Answer("uncategorized", None))
        self.away, self._ready, self.calls, self.examples = away, ready, [], []

    async def categorize(self, rows, examples=()):
        from steward_gateway.categorize import CategorizerAway
        self.calls.append(list(rows))
        self.examples.append(list(examples))
        if self.away:
            raise CategorizerAway()
        return [self.answer(r.description) for r in rows]

    async def ready(self):
        return self._ready

    async def close(self):
        pass


class FakeNas:
    """Stands in for steward_gateway.mcp.nas.NasClient: one book, a fixed result, and a record of what was finished."""
    CALL_ID = "mcp_0123456789abcdef"

    def __init__(self, content=None, *, hashes=(), refuse=None, away=False, record=True, bad_hash=False):
        from steward_boundary import tools as T
        self.content = content if content is not None else {"debts": []}
        self.hashes, self.refuse, self.away, self.record, self.bad_hash = list(hashes), refuse, away, record, bad_hash
        self.calls, self.finished, self.part = [], [], None
        self.tool_names = [t.name for t in T.TOOLS if "household" in t.books]      # merchant_detail included

    def _check(self):
        from steward_gateway.mcp.nas import NasAway, NasRefused
        if self.away:
            raise NasAway()
        if self.refuse:
            raise NasRefused(*self.refuse)

    async def tools(self, slug, grant):
        self._check()
        return {"book_id": 1, "book_kind": "household", "chat": True, "tools": list(self.tool_names)}

    async def call(self, slug, grant, name, input):
        from steward_boundary.canonical import canonical, sha256_hex
        self.calls.append((slug, grant, name, input))
        self._check()
        payload = {"tool_use_id": self.CALL_ID, "name": name, "is_error": False, "content": self.content}
        self.part = {"part": "tool_result", "payload": payload,
                     "sha256": "0" * 64 if self.bad_hash else sha256_hex(payload), "bytes": len(canonical(payload))}
        return {"call_id": self.CALL_ID, "book_id": 1, "part": self.part,
                "fingerprints": {"salt": "4" * 32, "hashes": self.hashes}}

    async def finish(self, slug, grant, call_id, outcome, check=None, path=None):
        from steward_gateway.mcp.nas import NasRefused
        self.finished.append((call_id, outcome, check, path))
        if not self.record:
            raise NasRefused(404, "That call has expired. Call the tool again.")
        return {"recorded": outcome == "sent", "sha256": self.part["sha256"], "bytes": self.part["bytes"]}

    async def close(self):
        pass


class FakeStatementModel:
    """Stands in for steward_gateway.statements.StatementModel: answers a fixed layout, or one made from the pages."""
    layout_model = "stand-in"
    vision_model = "stand-in-vision"

    def __init__(self, answer=None, away=False, features=("layout",), page=None):
        self.answer, self.away, self._features, self.calls = answer, away, list(features), []
        self.page_answer, self.page_calls = page, []

    async def features(self):
        return list(self._features)

    async def layout(self, pages, hint):
        from steward_gateway.statements import StatementsAway
        self.calls.append((pages, hint))
        if self.away or self.answer is None:
            raise StatementsAway()
        return self.answer(pages, hint) if callable(self.answer) else self.answer

    async def page(self, request):
        from steward_gateway.statements import StatementsAway
        self.page_calls.append(request)
        if self.away or self.page_answer is None:
            raise StatementsAway()
        return self.page_answer(request) if callable(self.page_answer) else self.page_answer

    async def close(self):
        pass
