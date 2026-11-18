"""Release spec 2026-11-05, section 6: until the first person exists, Steward answers only its health check, the
setup routes and the page's own files (GET and HEAD outside /api: the shell holds no data, and /setup must load).
Every other route is 503 with the line that says what to do, which RequireAuth shows on any screen. Pure ASGI, inside
the security headers and the origin check. The check is one read per request until someone exists; from then on the
gate stays open without asking."""
import json
from collections.abc import Callable

from steward.auth.setup_link import SETUP_COMMAND

NEEDS_SETUP = f"Run {SETUP_COMMAND} on the server."
READS = frozenset({"GET", "HEAD"})


def passes(method: str, path: str) -> bool:
    if path == "/api/health" or path == "/api/setup" or path.startswith("/api/setup/"):
        return True
    return method in READS and not (path == "/api" or path.startswith("/api/"))


def gate_on(settings, override: bool | None) -> bool:
    """On unless STEWARD_ENV is test (the suite's apps start from an empty directory on purpose); a test passes True."""
    return override if override is not None else settings.env != "test"


class FirstRun:
    def __init__(self, app, has_people: Callable[[], bool]):
        self.app, self.has_people, self.ready = app, has_people, False
        self.refusal = json.dumps({"error": NEEDS_SETUP}).encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.ready or passes(scope["method"], scope["path"]):
            return await self.app(scope, receive, send)
        if self.has_people():
            self.ready = True
            return await self.app(scope, receive, send)
        await send({"type": "http.response.start", "status": 503, "headers": [
            (b"content-type", b"application/json"), (b"content-length", str(len(self.refusal)).encode()),
            (b"retry-after", b"60")]})
        await send({"type": "http.response.body", "body": self.refusal})
