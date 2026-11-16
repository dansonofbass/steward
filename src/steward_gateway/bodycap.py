"""The gateway's request-body cap (PDF statements spec P29), counted while the body streams and before routing, as the
NAS's api/limits.BodyLimit does: a declared Content-Length over the cap is refused at once, and a chunked body is
stopped when it passes it, so no handler's request.json() ever reads an oversized body. 512 KB for a statement
layout, 5 MB for a scanned page, 15 MB + 64 KB for a whole PDF to open (remote-reading P57), 1 MB for every other route (none needs more today; the largest is a 50-row categorizer batch with 40
examples, about 25 KB)."""
from __future__ import annotations

import json
import re

KB, MB = 1024, 1024 * 1024
DEFAULT = MB
LIMITS = ((re.compile(r"^/v1/statements/layout/?$"), 512 * KB), (re.compile(r"^/v1/statements/page/?$"), 5 * MB),
          (re.compile(r"^/v1/statements/(?:extract|render)/?$"), 15 * MB + 64 * KB))
TOO_LARGE = "That request is too large."


def limit_for(path: str) -> int:
    return next((limit for pattern, limit in LIMITS if pattern.match(path)), DEFAULT)


class BodyCap:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = limit_for(scope["path"])
        payload = json.dumps({"error": TOO_LARGE}).encode()
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
        seen, exceeded = 0, False

        async def counted():
            nonlocal seen, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            event = await receive()
            if event["type"] == "http.request":
                seen += len(event.get("body", b""))
                if seen > limit:
                    exceeded = True
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
