"""Issue #8 (gate finding SEC-8): the API answers only at Steward's own names. A page served from a name that is later
pointed at 127.0.0.1 (DNS rebinding) calls Steward as its own origin, so api/origin.py lets its writes through, with
that name in Host. The session cookie isn't sent, but the routes that need no sign-in are open to it: a lockout, a
username probe, a reset email. So /api/ answers only when Host names STEWARD_BASE_URL's host, a loopback name (the
demo, the healthchecks, a curl on the box) or a name in STEWARD_ALLOWED_HOSTS. Any other name gets 421.

Only the name is compared, never the port: a rebinding page reaches Steward's own port under its own name. tailscale
serve and steward-proxy's Caddy pass the browser's Host through (tests/test_host_check.py). Pages off the API (the
built web app) are served at any name: they hold no data, and every call they make is checked here. Pure ASGI, inside
SecurityHeaders, so a 421 carries the headers, and outside everything else, so nothing behind it runs."""
import ipaddress
import json
import re

LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
WRONG_HOST = ("Steward doesn't answer at this address. Open it at the address in STEWARD_BASE_URL, or add this name "
              "to STEWARD_ALLOWED_HOSTS.")
LABEL = r"[a-z0-9]([a-z0-9_-]*[a-z0-9])?"
NAME = re.compile(rf"{LABEL}(\.{LABEL})*")
PORT = re.compile(r"(:[0-9]{1,5})?")


def plain_name(text: str) -> str:
    """A host name or IP address in lower case, with no trailing dot and an IPv6 address unbracketed; "" when the text
    is neither. An IPv6 address may come with or without its brackets: urlsplit's hostname drops them."""
    t = text.strip().lower()
    bracketed = t.startswith("[") and t.endswith("]")
    if bracketed:
        t = t[1:-1]
    if bracketed or ":" in t:
        try:
            return str(ipaddress.IPv6Address(t))
        except ValueError:
            return ""
    t = t.removesuffix(".")
    return t if len(t) <= 253 and NAME.fullmatch(t) else ""


def host_name(header: str) -> str:
    """The name in a Host header without its port: "[::1]:8420" is "::1", "Steward.LAN.:443" is "steward.lan"."""
    h = header.strip()
    end = h.find("]") + 1 if h.startswith("[") else (h.find(":") if ":" in h else len(h))
    if end <= 0 or not PORT.fullmatch(h[end:]):
        return ""
    return plain_name(h[:end])


def on_api(path: str) -> bool:
    """Whether the check applies. A path that isn't origin-form counts: uvicorn's h11 parser leaves an absolute-form
    target ("http://other/api/...") whole in the path, and "*" has no path at all."""
    return path == "/api" or path.startswith("/api/") or not path.startswith("/")


def the_host(headers) -> str:
    """The request's one Host header, "" when it has none or more than one. uvicorn's default parser passes repeats
    through, and Starlette reads the first while dict() would keep the last, so a repeat is refused, not resolved."""
    found = [v for k, v in headers if k == b"host"]
    return found[0].decode("latin-1") if len(found) == 1 else ""


class HostCheck:
    def __init__(self, app, names: frozenset[str]):
        self.app = app
        self.names = names
        self.refusal = json.dumps({"error": WRONG_HOST}).encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not on_api(scope["path"]):
            return await self.app(scope, receive, send)
        if host_name(the_host(scope["headers"])) in self.names:
            return await self.app(scope, receive, send)
        await send({"type": "http.response.start", "status": 421, "headers": [
            (b"content-type", b"application/json"), (b"content-length", str(len(self.refusal)).encode())]})
        await send({"type": "http.response.body", "body": self.refusal})
