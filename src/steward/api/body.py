"""JSON request bodies parsed by hand, so errors keep milestone 1's {"error": "<plain words>"} shape (spec 8)
instead of FastAPI's validation list."""
import json
from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException, Request

MAX_JSON_BYTES = 64 * 1024
NOT_UNDERSTOOD = "That request wasn't understood."
TOO_LARGE = "That request is too large."


def bad(message: str, status: int = 422) -> HTTPException:
    return HTTPException(status, detail={"error": message})


async def json_object(request: Request) -> dict[str, Any]:
    # Ruling 0: the media type is checked first, on every request. A missing Content-Type is refused too, since a
    # same-site fetch with no body and no Content-Type is a simple request that skips the CORS preflight.
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type != "application/json":
        raise bad(NOT_UNDERSTOOD, 415)
    declared = request.headers.get("content-length", "").strip()
    if declared.isascii() and declared.isdigit() and int(declared) > MAX_JSON_BYTES:
        raise bad(TOO_LARGE, 413)
    buf = bytearray()
    async for chunk in request.stream():     # stop at the cap instead of buffering the whole body first
        buf += chunk
        if len(buf) > MAX_JSON_BYTES:
            raise bad(TOO_LARGE, 413)
    raw = bytes(buf)
    if not raw.strip():
        return {}
    try:
        body = json.loads(raw)
    except ValueError:
        raise bad(NOT_UNDERSTOOD) from None
    if not isinstance(body, dict):
        raise bad(NOT_UNDERSTOOD)
    return body


def whole(value: Any, message: str, lo: int | None = None, hi: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad(message)
    if isinstance(value, float) and not value.is_integer():
        raise bad(message)
    v = int(value)
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise bad(message)
    return v


def text(value: Any, message: str, max_len: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_len:
        raise bad(message)
    return value.strip()


def one_of(value: Any, options: Sequence[str], message: str) -> str:
    if not isinstance(value, str) or value not in options:
        raise bad(message)
    return value
