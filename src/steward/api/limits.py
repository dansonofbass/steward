"""Request-body caps enforced while the body streams in (pure ASGI). The handlers' own size checks run after
Starlette's multipart parser has already spooled the whole body to memory or disk, and Content-Length is absent
with chunked transfer encoding, so only counting bytes as they arrive keeps one request from filling the disk."""
import json
import re

from steward.api import imports, ss
from steward.api.statements import MAX_PDF, TOO_BIG as PDF_TOO_BIG
from steward.inventory.files import MAX_BYTES as FILE_MAX, TOO_BIG as FILE_TOO_BIG

MB = 1024 * 1024
OVERHEAD = MB  # multipart framing and form fields around the file
DEFAULT = (MB, "That request is too large.")
_BOOK = r"^/api/b/[^/]+"
# (path pattern, limit in bytes, the route's existing too-big message); first match wins, everything else is DEFAULT.
LIMITS = (
    (re.compile(_BOOK + r"/inventory/files/?$"), FILE_MAX + OVERHEAD, FILE_TOO_BIG),
    (re.compile(_BOOK + r"/import/files/?$"), imports.MAX_BYTES + OVERHEAD, "That file is bigger than 5 MB."),
    (re.compile(_BOOK + r"/import/statements/?$"), MAX_PDF + 64 * 1024, PDF_TOO_BIG),
    (re.compile(_BOOK + r"/ss/import/?$"), ss.MAX_BYTES + OVERHEAD, ss.TOO_BIG),
    (re.compile(_BOOK + r"/accounts/\d+/positions(/preview)?/?$"), MB, "That file is bigger than 1 MB."),
    (re.compile(_BOOK + r"/inventory/tax-forms/csv/?$"), MB + OVERHEAD, "That file is bigger than 1 MB."),
)


def limit_for(path: str) -> tuple[int, str]:
    for pattern, limit, message in LIMITS:
        if pattern.match(path):
            return limit, message
    return DEFAULT


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit, message = limit_for(scope["path"])
        payload = json.dumps({"error": message}).encode()
        started = False

        async def refuse():
            nonlocal started
            started = True
            await send({"type": "http.response.start", "status": 413, "headers": [
                (b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]})
            await send({"type": "http.response.body", "body": payload})

        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            return await refuse()

        seen = 0
        exceeded = False

        async def counted():
            nonlocal seen, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            event = await receive()
            if event["type"] == "http.request":
                seen += len(event.get("body", b""))
                if seen > limit:
                    exceeded = True  # stop reading; whatever the app answers is replaced by the 413
                    return {"type": "http.disconnect"}
            return event

        async def guarded(event):
            nonlocal started
            if exceeded:
                if not started:
                    await refuse()
                return
            if event["type"] == "http.response.start":
                started = True
            await send(event)

        try:
            await self.app(scope, counted, guarded)
        except Exception:
            if not exceeded:
                raise
        if exceeded and not started:
            await refuse()
