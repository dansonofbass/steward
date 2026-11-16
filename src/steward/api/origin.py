"""Open-source evaluation 6.4: a write reaches the API only from Steward's own pages. The session cookie's
SameSite=Lax stops other sites' forms but not a sibling host on the same domain (another app at blog.example.com is
"same-site" with steward.example.com), and the raw-body and multipart routes (imports, statements, Social Security,
positions) take bodies no JSON check guards. Pure ASGI, like BodyLimit, and outside it: a refused write is answered
before a byte of its body is read.

The browser's own word decides (Sec-Fetch-Site, sent by every current browser): same-origin passes, and so does
none (the person typed or bookmarked it); same-site and cross-site are refused. An older browser without it is
judged by its Origin, which must be Steward's address (STEWARD_BASE_URL) or this request's own scheme and Host. A
request with neither header came from no browser (the CLI, the gateway's grant calls with a bearer token, tests),
and CSRF needs a browser, so it passes."""
import json
from urllib.parse import urlsplit

UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})
PASSES = frozenset({b"same-origin", b"none"})
REFUSED = "That request came from another site."


def origin_of(url: str) -> str:
    """scheme://host[:port], lowercased, as a browser writes an Origin."""
    u = urlsplit(url.strip())
    return f"{u.scheme}://{u.netloc}".lower()


def allowed(method: str, path: str, headers: dict[bytes, bytes], scheme: str, base_url: str) -> bool:
    if method not in UNSAFE or not path.startswith("/api/"):
        return True
    site = headers.get(b"sec-fetch-site")
    if site is not None:
        return site.strip().lower() in PASSES
    origin = headers.get(b"origin")
    if origin is None:
        return True
    host = headers.get(b"host", b"").decode("latin-1").strip().lower()
    own = {origin_of(base_url)} | ({f"{scheme}://{host}"} if host else set())
    return origin.decode("latin-1").strip().lower() in own


class SameOrigin:
    def __init__(self, app, base_url: str):
        self.app = app
        self.base_url = base_url
        self.refusal = json.dumps({"error": REFUSED}).encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or allowed(scope["method"], scope["path"], dict(scope["headers"]),
                                              scope.get("scheme", "http"), self.base_url):
            return await self.app(scope, receive, send)
        await send({"type": "http.response.start", "status": 403, "headers": [
            (b"content-type", b"application/json"), (b"content-length", str(len(self.refusal)).encode())]})
        await send({"type": "http.response.body", "body": self.refusal})
