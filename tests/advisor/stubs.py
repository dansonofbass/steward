"""A scripted gateway for NAS tests that need exact frames: drops, cancels, stops."""
from __future__ import annotations

import json

from steward.advisor.control import Control
from steward.advisor.gateway import GatewayUnavailable
from steward_boundary.canonical import canonical, sha256_hex
from steward_boundary.protocol import START, check_frame


def part(name: str, payload: dict) -> dict:
    return {"part": name, "payload": payload, "sha256": sha256_hex(payload), "bytes": len(canonical(payload))}


class StubWs:
    def __init__(self, frames):
        self.frames, self.sent, self.closed = list(frames), [], False

    def send(self, raw: str) -> None:
        frame = json.loads(raw)
        if frame.get("type") == "start":        # a START without `issued` is what the real gateway refuses
            assert not check_frame(START, frame), check_frame(START, frame)
        self.sent.append(frame)

    def recv(self, timeout=None) -> str:
        if not self.frames:
            raise TimeoutError()
        f = self.frames.pop(0)
        if isinstance(f, BaseException):
            raise f
        if callable(f):                         # a frame built from what the NAS has sent so far
            f = f(self.sent)
        return json.dumps(f)

    def close(self) -> None:
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class StubGateway:
    def __init__(self, frames=(), health=None, away=False, redact=None, usage=None, title=None):
        self.ws, self.connects, self.away = StubWs(frames), 0, away
        self._health = health or {"key_set": True, "redaction_ready": True, "chat_stopped": False, "ollama": False, "categorizer": False,
                                  "budget": {"month": "2026-10", "cap_cents": 1000, "max_cap_cents": 10_000,
                                             "spent_cents": 312, "reserved_cents": 0, "questions": 26, "warn": False,
                                             "can_ask": True, "model": "claude-opus-5-5"}}
        self._redact = redact or (lambda text: {"text": text, "edits": []})
        self._usage = usage
        self._title, self.titled = title, None
        self.settings_calls: list[dict] = []
        self.prewarms: list[tuple] = []

    def connect(self, timeout: float = 5.0):
        self.connects += 1
        if self.away:
            raise GatewayUnavailable()
        return self.ws

    def health(self):
        if self.away:
            raise GatewayUnavailable()
        return self._health

    def redact(self, text, issued=None):
        if self.away:
            raise GatewayUnavailable()
        self.redact_issued = issued
        return self._redact(text)

    def usage(self):
        return self._usage

    def title(self, text):
        self.titled = text
        if self.away:
            raise GatewayUnavailable()
        return self._title

    def set_settings(self, **fields):
        self.settings_calls.append(fields)
        return {"cap_cents": fields.get("cap_cents", 1000), "model": fields.get("model", "claude-opus-5-5")}

    def prewarm_plan(self, book_id, user_id):
        payload = {"prefix": "steward-advisor-1", "prefix_sha256": "0" * 64, "message": "warmup"}
        return {"due": True, "payload": payload, "sha256": sha256_hex(payload), "model": "claude-opus-5-5"}

    def prewarm(self, book_id, user_id, sha256):
        self.prewarms.append((book_id, user_id, sha256))
        return {"sent": True}

    def sent_since(self, since):
        return {"sent": []}

    def close(self):
        pass


class AutoControl(Control):
    """Answers every store-names card at once with `answer` ("send", "decline", "stopped" or "timeout")."""

    def __init__(self, answer: str):
        super().__init__()
        self.answer_with, self.asked, self.digests = answer, [], []

    def wait_for_ok(self, turn_id, call_id, timeout, digest=None):
        self.asked.append(call_id)
        self.digests.append(digest)
        return self.answer_with
