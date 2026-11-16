"""Gateway logging (spec 3.1): turn ids, timings, token counts and costs only, never question text, tool results or
the key. Hardened in Task 2.5 (the Task 6 security review):

- log_event() is how gateway code logs: an event name and fields from ALLOWED_FIELDS. Numbers pass as they are;
  error_message is the one free-text field (Anthropic's reason for a refusal, see api_error_reason): it is scrubbed,
  one line, at most 300 characters;
  each string field must have its field's shape (a turn id, a status word, an exception type...) or it becomes
  "[dropped]"; any other field is left out.
- ScrubFilter sits on every root handler and on the HTTP and SDK loggers. A record from gateway code that isn't an
  event keeps only its message template (the values are dropped). A record from any other logger is scrubbed:
  keys (sk-ant-..., even cut short), Authorization and x-api-key headers, bearer tokens, long base64 or hex runs,
  emails, and every digit beyond the 4 the masking rule allows. An exception keeps its traceback's code locations
  and exception types, never its message.
- setup_logging() keeps httpx, httpcore, anthropic and the model libraries at WARNING, and sends uvicorn's loggers
  through the root handler so its records are filtered too."""
from __future__ import annotations

import logging
import re
import sys
import traceback
from decimal import Decimal
from typing import Any

from steward_boundary.text import mask_numbers

KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-.]*")
_HEADER_RE = re.compile(
    r"""(?i)\b(authorization|proxy-authorization|x-api-key|api[-_]?key|cookie|set-cookie)\b(['"]?\s*[:=]\s*['"]?)"""
    r"""(?:(?:bearer|basic)\s+)?[^\s'",;}\]]+""")
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{6,}")
_OTHER_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}")
_LONG_RE = re.compile(r"[A-Za-z0-9+/_=\-]{24,}")
_EMAIL_RE = re.compile(r"[\w.+%'-]+@[\w-]+(?:\.[\w-]+)+")

ALLOWED_FIELDS = frozenset({
    "event", "turn_id", "book_id", "user_id", "seq", "step", "status", "stop", "check", "model", "error_type",
    "error_kind", "error_message",
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cost_nd", "reserved_nd", "ms",
    "count", "bytes", "parts", "requests", "request_id", "guessed", "examples",
    "rows", "categorized", "pages", "lines", "ok"})
_WORD = re.compile(r"^[a-z][a-z0-9_.\-]{0,47}$")
_SHAPES = {
    "event": _WORD, "status": _WORD, "stop": _WORD, "check": _WORD, "error_kind": _WORD,
    "turn_id": re.compile(r"^t_[0-9a-f]{16}$"),
    "model": re.compile(r"^claude-[a-z0-9.\-]{1,40}$"),
    "request_id": re.compile(r"^req_[A-Za-z0-9_]{1,80}$"),
    "error_type": re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,80}$"),
}
QUIET = ("httpx", "httpx2", "httpcore", "anthropic", "huggingface_hub", "transformers", "urllib3", "websockets",
         "presidio-analyzer", "presidio_analyzer", "gliner", "torch", "fastapi")
_OURS = "steward_gateway"


def _secrets_out(text: str) -> str:
    text = _HEADER_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[secret]", text)
    text = KEY_RE.sub("[key]", text)
    text = _OTHER_KEY_RE.sub("[key]", text)
    text = _BEARER_RE.sub(lambda m: f"{m.group(1)} [secret]", text)
    text = _LONG_RE.sub(lambda m: "[secret]" if re.search(r"[A-Za-z]", m.group()) and re.search(r"[0-9]", m.group())
                        else m.group(), text)
    return _EMAIL_RE.sub("[email]", text)


def scrub(text: str) -> str:
    """Free text made safe for a log line: no key, header value, token, email, or more than 4 digits."""
    return mask_numbers(_secrets_out(str(text)))


MESSAGE_CAP = 300


def api_error_reason(e: Any) -> tuple[str, str]:
    """(kind, message) from an Anthropic error's body, `{"type": "error", "error": {"type": ..., "message": ...}}`:
    the kind is error.type, the message is error.message (or the kind when there is none), whitespace collapsed and cut
    to 300 characters. ("", "") when the body isn't that shape."""
    body = getattr(e, "body", None)
    err = body.get("error") if isinstance(body, dict) else None
    if not isinstance(err, dict):
        return "", ""
    kind = err.get("type") if isinstance(err.get("type"), str) else ""
    message = err.get("message") if isinstance(err.get("message"), str) else ""
    return kind, (" ".join(message.split()) or kind)[:MESSAGE_CAP]


def _field(key: str, value: Any) -> str | None:
    if key not in ALLOWED_FIELDS:
        return None
    if key in ("error_kind", "error_message") and value == "":
        return None
    if key == "error_message":
        return f"{key}={scrub(' '.join(str(value).split())[:MESSAGE_CAP])}"
    if isinstance(value, bool) or isinstance(value, (int, float, Decimal)):
        return f"{key}={value}"
    shape = _SHAPES.get(key)
    if isinstance(value, str) and shape is not None and shape.fullmatch(value):
        return f"{key}={value}"
    return f"{key}=[dropped]"


def _event_message(event: Any, fields: dict) -> str:
    head = event if isinstance(event, str) and _WORD.fullmatch(event) else "[dropped]"
    return " ".join([head, *(f for k, v in fields.items() if (f := _field(k, v)) is not None)])


def _exception_summary(exc_info) -> str:
    """The traceback's code locations and the exception types in its chain, never a message (which can carry a key
    or a header)."""
    etype, exc, tb = exc_info
    lines = ["Traceback (most recent call last):"]
    lines += [f'  File "{f.filename}", line {f.lineno}, in {f.name}' for f in traceback.extract_tb(tb)]
    names, seen = [], set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        names.append(type(exc).__qualname__)
        exc = exc.__cause__ or exc.__context__
    if not names and etype is not None:
        names.append(etype.__qualname__)
    lines.append(" <- ".join(names) + " (message not logged)")
    return _secrets_out("\n".join(lines))


class ScrubFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "_steward_scrubbed", False):
            return True
        fields = getattr(record, "steward_fields", None)
        if fields is not None:
            message = _event_message(record.msg, fields)
        elif record.name == _OURS or record.name.startswith(_OURS + "."):
            message = scrub(record.msg if isinstance(record.msg, str) else type(record.msg).__name__)
            if record.args:
                message += " [values not logged]"
        else:
            try:
                message = scrub(record.getMessage())
            except Exception:  # a bad format string mustn't break logging, nor show its arguments
                message = scrub(str(record.msg))
        record.msg, record.args = message, ()
        if record.exc_info:
            record.exc_text = _exception_summary(record.exc_info)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = scrub(record.exc_text)
        if record.stack_info:
            record.stack_info = None
        record._steward_scrubbed = True
        return True


KeyFilter = ScrubFilter          # the name Task 6 gave it


def log_event(logger: logging.Logger, event: str, /, *, level: int = logging.INFO, **fields: Any) -> None:
    """Log one event with allow-listed fields: `log_event(log, "turn.end", turn_id=..., status="end_turn",
    input_tokens=1200, cost_nd=...)`. Fields off the list are left out; strings that don't fit their field are
    "[dropped]"."""
    logger.log(level, event, extra={"steward_fields": dict(fields)})


def setup_logging(stream=None) -> None:
    """One filtered handler on the root logger (and the filter on any handler already there), the noisy libraries
    at WARNING with the filter on them too, and uvicorn's loggers sent through the root."""
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler._steward_handler = True
    root = logging.getLogger()
    # a second call replaces the handler the first one added
    root.handlers[:] = [h for h in root.handlers if not getattr(h, "_steward_handler", False)]
    for h in [*root.handlers, handler]:
        if not any(isinstance(f, ScrubFilter) for f in h.filters):
            h.addFilter(ScrubFilter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for name in QUIET:
        lg = logging.getLogger(name)
        lg.setLevel(logging.WARNING)
        if not any(isinstance(f, ScrubFilter) for f in lg.filters):
            lg.addFilter(ScrubFilter())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
