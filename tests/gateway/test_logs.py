"""Gateway logs (spec 3.1; the Task 6 security review): an allow-list of fields, never free text; anything shaped
like a key, a header, an email or a long number is scrubbed; the HTTP and SDK loggers are quiet and filtered."""
import io
import logging

import pytest

from steward_gateway.logs import ALLOWED_FIELDS, KeyFilter, ScrubFilter, log_event, scrub, setup_logging

KEY = "sk-ant-api03-ABCdef_123-xyzXYZ0987654321abcdefghij"
TURN = "t_0123456789abcdef"
@pytest.mark.parametrize("text, gone", [
    (f"refused {KEY}", "sk-ant"),
    ("partial key sk-ant-api03-AB...", "sk-ant"),
    ("headers {'x-api-key': 'abcDEF1234567890', 'content-type': 'json'}", "abcDEF"),
    ("Authorization: Bearer abc.DEF-123_456", "abc.DEF"),
    ("authorization=Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
    ("token ZXhhbXBsZTEyMzQ1Njc4OTBhYmNkZWZnaGlqa2w=", "ZXhhbXBsZTEy"),
    ("hash 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08", "9f86d081"),
    ("mail margaret@example.com today", "margaret@"),
    ("card 4111 1111 1111 1111", "4111 1111"),
])
def test_scrub_removes_keys_headers_emails_and_long_numbers(text, gone):
    assert gone not in scrub(text)


def test_scrub_leaves_plain_words_alone():
    assert scrub("turn ended: end_turn after 3 steps") == "turn ended: end_turn after 3 steps"


def test_an_event_keeps_only_allowed_fields(caplog):
    log = logging.getLogger("steward_gateway.test")
    caplog.handler.addFilter(ScrubFilter())
    with caplog.at_level(logging.INFO, logger="steward_gateway.test"):
        log_event(log, "turn.start", turn_id=TURN, book_id=3, input_tokens=123456, cost_nd=91000000,
                  question="Margaret Ellis at margaret@example.com, 714-555-0102", api_key=KEY,
                  tool_result={"name": "Robert"})
    assert f"turn.start turn_id={TURN} book_id=3 input_tokens=123456 cost_nd=91000000" in caplog.text
    for leak in ("Margaret", "example.com", "555", "sk-ant", "Robert", "question", "api_key"):
        assert leak not in caplog.text
    assert {"event", "turn_id", "book_id", "input_tokens", "cost_nd", "status", "error_type"} <= ALLOWED_FIELDS


def test_an_event_string_that_isnt_shaped_like_its_field_is_dropped(caplog):
    log = logging.getLogger("steward_gateway.test")
    caplog.handler.addFilter(ScrubFilter())
    with caplog.at_level(logging.INFO, logger="steward_gateway.test"):
        log_event(log, "turn.end", turn_id="Margaret Ellis", status="Robert said hi", error_type="Bad key " + KEY)
    assert "Margaret" not in caplog.text and "Robert" not in caplog.text and "sk-ant" not in caplog.text
    assert "turn_id=[dropped]" in caplog.text


def test_a_forced_exception_with_the_key_in_its_message_and_headers_never_reaches_the_log(caplog):
    stream = io.StringIO()
    setup_logging(stream=stream)
    log = logging.getLogger("steward_gateway.loop")
    with caplog.at_level(logging.INFO):
        try:
            raise RuntimeError(f"401 for x-api-key: {KEY} with Authorization: Bearer {KEY} "
                               "asking about Margaret Ellis (margaret@example.com)")
        except RuntimeError:
            log.exception("the request failed for %s", "Margaret Ellis")
    for out in (caplog.text, stream.getvalue()):
        assert out, "nothing was logged"
        for leak in ("sk-ant", "ABCdef", "Bearer", "Margaret", "example.com"):
            assert leak not in out, (leak, out)
        assert "RuntimeError" in out and "the request failed" in out


def test_the_http_and_sdk_loggers_are_quiet_and_scrubbed(caplog):
    stream = io.StringIO()
    setup_logging(stream=stream)
    for name in ("httpx", "httpx2", "httpcore", "anthropic"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING
    with caplog.at_level(logging.INFO):
        logging.getLogger("anthropic._base_client").info("Request options: {'json_data': 'Margaret Ellis'}")
        logging.getLogger("httpx").warning("headers {'x-api-key': '%s', 'authorization': 'Bearer %s'}", KEY, KEY)
    for out in (caplog.text, stream.getvalue()):
        assert "Margaret" not in out and "sk-ant" not in out and "Bearer sk" not in out
        assert "headers" in out


@pytest.mark.parametrize("name", ["presidio-analyzer", "presidio_analyzer", "gliner", "torch", "fastapi"])
def test_the_model_and_framework_loggers_are_quiet(caplog, name):
    """The scrub masks digits, keys and emails but lets names through, so the model libraries and FastAPI stay at
    WARNING (final review, finding 7)."""
    stream = io.StringIO()
    setup_logging(stream=stream)
    lg = logging.getLogger(name)
    assert lg.getEffectiveLevel() >= logging.WARNING
    assert any(isinstance(f, ScrubFilter) for f in lg.filters)
    lg.info("analyzing text: Margaret Ellis called")
    assert "Margaret" not in stream.getvalue()


def test_uvicorn_logs_go_through_the_filter():
    stream = io.StringIO()
    setup_logging(stream=stream)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        assert lg.handlers == [] and lg.propagate
    logging.getLogger("uvicorn.error").error("bad header x-api-key: %s from margaret@example.com", KEY)
    assert "sk-ant" not in stream.getvalue() and "margaret@" not in stream.getvalue()
    assert "bad header" in stream.getvalue()


def test_a_key_never_reaches_a_log_line(caplog):
    log = logging.getLogger("steward_gateway.test")
    log.addFilter(KeyFilter())
    try:
        with caplog.at_level(logging.INFO, logger="steward_gateway.test"):
            log.info("refused key %s for turn %s", KEY, TURN)
    finally:
        log.filters.clear()
    assert "sk-ant" not in caplog.text and "refused key" in caplog.text


def _status_error(body):
    import anthropic
    import httpx2
    resp = httpx2.Response(400, request=httpx2.Request("POST", "https://anthropic.invalid/v1/messages"))
    return anthropic.BadRequestError("Error code: 400", response=resp, body=body)


def test_api_error_reason_reads_anthropics_body():
    from steward_gateway.logs import api_error_reason
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": "a  bad\n field " + "x" * 400}}
    kind, message = api_error_reason(_status_error(body))
    assert kind == "invalid_request_error" and message.startswith("a bad field xxx") and len(message) == 300
    assert api_error_reason(_status_error({"type": "error", "error": {"type": "overloaded_error"}})) == (
        "overloaded_error", "overloaded_error")


@pytest.mark.parametrize("body", [None, "plain text", ["x"], {"error": "x"}, {"error": {"message": 5}}])
def test_api_error_reason_is_empty_for_another_body(body):
    from steward_gateway.logs import api_error_reason
    assert api_error_reason(_status_error(body)) == ("", "")


def test_an_error_message_is_scrubbed_and_error_kind_must_be_a_word(caplog):
    log = logging.getLogger("steward_gateway.test")
    caplog.handler.addFilter(ScrubFilter())
    with caplog.at_level(logging.INFO, logger="steward_gateway.test"):
        log_event(log, "x.failed", error_kind="invalid_request_error", error_message=f"bad {KEY} for margaret@example.com")
        log_event(log, "x.failed", error_kind="Bad Kind")
    assert "error_kind=invalid_request_error" in caplog.text and "error_kind=[dropped]" in caplog.text
    assert "sk-ant" not in caplog.text and "margaret@" not in caplog.text and "[key]" in caplog.text
