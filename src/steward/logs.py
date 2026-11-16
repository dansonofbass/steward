"""Steward's own log lines (release spec 2026-11-05, section 6; claim P10, "Logs don't carry your money").

- uvicorn's access log is off: it wrote each request's address with its query string, so a search
  (GET /api/b/ours/transactions?q=…) put the search text in `docker logs`.
- RequestLog writes one line per request instead: the method, the route's path template (/api/b/{slug}/transactions,
  so no query string, book slug or id appears), the status and the milliseconds. A refusal made before routing (the
  first-run gate, an origin refusal) has no route, and logs "-".
- QuietExceptions sits on the one handler configure() installs: a traceback keeps its code locations and exception
  types, never its message, which can carry a description, an amount or a recipient.
- A line about a book names it by id, never by slug: a parent book's slug is the parent's name. Words another program
  wrote go through outside_text(). tests/test_quiet_logs.py scans every log call for both.
configure() is for `steward serve` only; tests and the other commands keep Python's defaults."""
from __future__ import annotations

import logging
import re
import sys
import time
import traceback

from steward.inventory.present import scrub_text

REQUESTS = "steward.http"
# Steward's own start lines at INFO, under the root's WARNING: where PDF statements are opened (install gate INS-11).
START_LINES = ("steward.services.statements.where",)
FORMAT = "%(levelname)s:     %(message)s"      # uvicorn's own look, so docker logs read as before
NOT_LOGGED = "(message not logged)"
OUTSIDE_CAP = 160
_WEB_ADDRESS = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s\"'<>]*", re.I)
log = logging.getLogger(REQUESTS)


def outside_text(text: object) -> str:
    """Words another program wrote, such as SimpleFIN's error or the passkey library's reason, made fit for a log line:
    the first line only, no web address or origin (an install's host name can be a family's name), no email address,
    no more than its last 4 digits, and at most OUTSIDE_CAP characters. A person's name in that text can't be found
    this way, so the line around it should make sense without the text."""
    first = (str(text).splitlines() or [""])[0]
    return (scrub_text(_WEB_ADDRESS.sub("(web address)", first)) or "")[:OUTSIDE_CAP]


def path_template(scope) -> str:
    """The matched route's template. FastAPI 0.143 keeps included routers, so scope["route"] is the router's own
    APIRoute (its path lacks the include prefix); the full template is on the effective route context."""
    ctx = (scope.get("fastapi") or {}).get("effective_route_context")
    for path in (getattr(ctx, "path", None), getattr(scope.get("route"), "path", None)):
        if isinstance(path, str) and path:
            return path
    return "-"


class RequestLog:
    """Pure ASGI and outermost, so it sees every answer's status, refusals included."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        start, status = time.perf_counter(), [500]

        async def sending(message):
            if message["type"] == "http.response.start":
                status[0] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, sending)
        finally:
            log.info("%s %s %d %dms", scope["method"], path_template(scope), status[0],
                     round((time.perf_counter() - start) * 1000))


def exception_summary(exc_info) -> str:
    """The traceback's code locations and the exception types in its chain, never a message."""
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
    lines.append(" <- ".join(names) + f" {NOT_LOGGED}")
    return "\n".join(lines)


class QuietExceptions(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info:
            record.exc_text = exception_summary(record.exc_info)
            record.exc_info = None
        elif record.exc_text and NOT_LOGGED not in record.exc_text:
            record.exc_text = "(traceback not logged)"        # another handler formatted it first, message and all
        record.stack_info = None
        return True


def configure(stream=None) -> logging.Handler:
    """One handler on the root with QuietExceptions, the root at WARNING as before, uvicorn's loggers through it
    (uvicorn.error at INFO for "Started server process" and "Uvicorn running on", uvicorn.access off), and the request
    log and START_LINES at INFO. A second call replaces the first one's handler."""
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(logging.Formatter(FORMAT))
    handler.addFilter(QuietExceptions())
    handler._steward_handler = True
    root = logging.getLogger()
    root.handlers[:] = [h for h in root.handlers if not getattr(h, "_steward_handler", False)]
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.CRITICAL + 1)   # off, whatever turns it on
    log.setLevel(logging.INFO)
    for name in START_LINES:
        logging.getLogger(name).setLevel(logging.INFO)
    return handler
