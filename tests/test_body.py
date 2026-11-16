import pytest
from fastapi import HTTPException

from steward.api.body import one_of, text, whole


@pytest.mark.parametrize("value", [True, "12", 1.5, None, float("inf"), [1]])
def test_whole_refuses_what_isnt_a_whole_number(value):
    with pytest.raises(HTTPException) as e:
        whole(value, "Enter a whole number.")
    assert e.value.status_code == 422 and e.value.detail == {"error": "Enter a whole number."}


def test_whole_accepts_integral_numbers_and_checks_range():
    assert whole(7, "x") == 7 and whole(70.0, "x") == 70
    with pytest.raises(HTTPException):
        whole(5, "x", lo=6)
    with pytest.raises(HTTPException):
        whole(5, "x", hi=4)


def test_text_and_one_of():
    assert text("  Oldest ", "label", 40) == "Oldest"
    for v in ("", "   ", "x" * 41, 5, None):
        with pytest.raises(HTTPException):
            text(v, "label", 40)
    assert one_of("private", ("private", "in_state_public"), "m") == "private"
    with pytest.raises(HTTPException):
        one_of("ivy", ("private",), "m")


def test_json_object_stops_reading_a_body_once_it_is_over_the_cap():
    import asyncio
    from starlette.requests import Request
    from steward.api.body import MAX_JSON_BYTES, json_object
    chunks = [b" " * 40_000] * 50
    served = []

    async def receive():
        if not chunks:
            return {"type": "http.disconnect"}
        served.append(1)
        return {"type": "http.request", "body": chunks.pop(0), "more_body": bool(chunks)}

    req = Request({"type": "http", "method": "POST", "path": "/", "query_string": b"",
                   "headers": [(b"content-type", b"application/json")]}, receive)
    with pytest.raises(HTTPException) as e:
        asyncio.run(json_object(req))
    assert e.value.status_code == 413 and len(served) * 40_000 <= MAX_JSON_BYTES + 40_000


def test_json_object_refuses_a_declared_length_over_the_cap_without_reading():
    import asyncio
    from starlette.requests import Request
    from steward.api.body import json_object

    async def receive():
        raise AssertionError("must not read")

    req = Request({"type": "http", "method": "POST", "path": "/", "query_string": b"",
                   "headers": [(b"content-type", b"application/json"), (b"content-length", b"999999")]}, receive)
    with pytest.raises(HTTPException) as e:
        asyncio.run(json_object(req))
    assert e.value.status_code == 413
