"""Issue #14: where the page's CSP reports what it blocked (api/headers.py), so a CSP regression after a release shows
in Steward's log. Two shapes arrive: report-uri's {"csp-report": {...}} (Firefox, Safari) and the Reporting API's
list of {"type": "csp-violation", "body": {...}} (Chromium, through report-to).

A line holds two things only: the directive, when it is a directive's name, and what was blocked, as the browser's
keyword (inline, eval, trusted-types-sink and the like) or as an origin, with "this address" for one of Steward's own
names, since an install's host name can be a family's name. Never the page's address, the blocked file's path or
query, or the sample of script the browser quotes: a page address can hold a search or a book's slug (claim P10).

It needs no sign-in (a report can come from the sign-in page), it is limited per device (ratelimit.CSP_REPORT), and,
like every write, it is taken only from Steward's own pages (api/origin.py). Anything it can't read is dropped
without a word: the answer is always 204."""
import json
import logging
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response

from steward.api.hosts import plain_name
from steward.auth.ratelimit import CSP_REPORT, limit

log = logging.getLogger(__name__)
router = APIRouter()

MAX_BYTES = 64 * 1024
MAX_REPORTS = 10
DIRECTIVE = re.compile(r"[a-z][a-z-]{0,39}")
KEYWORDS = frozenset({"inline", "eval", "wasm-eval", "data", "blob", "trusted-types-sink", "trusted-types-policy",
                      "self", "unsafe-inline"})


def _bodies(payload) -> list[dict]:
    """The violation bodies in either shape, as (directive, blocked) dicts of whatever the browser sent."""
    if isinstance(payload, dict) and isinstance(payload.get("csp-report"), dict):
        r = payload["csp-report"]
        return [{"directive": r.get("effective-directive") or r.get("violated-directive"), "blocked": r.get("blocked-uri")}]
    if isinstance(payload, list):
        return [{"directive": b.get("effectiveDirective"), "blocked": b.get("blockedURL")}
                for item in payload if isinstance(item, dict) and item.get("type") == "csp-violation"
                and isinstance(b := item.get("body"), dict)]
    return []


def directive_of(value) -> str:
    """A directive's name, or "other". Old browsers send violated-directive with its sources: keep the name."""
    name = value.split(" ", 1)[0].strip().lower() if isinstance(value, str) else ""
    return name if DIRECTIVE.fullmatch(name) else "other"


def blocked_of(value, own: frozenset[str]) -> str:
    """The browser's keyword, an origin, "this address", or "other"; never a path, a query or anything typed."""
    text = value.strip().lower() if isinstance(value, str) else ""
    if text in KEYWORDS:
        return text
    if ":" not in text:
        return "other"
    try:
        u = urlsplit(text)
        host = plain_name(u.hostname or "")
        port = u.port
    except ValueError:
        return "other"
    if u.scheme in ("data", "blob"):
        return u.scheme
    if not re.fullmatch(r"[a-z][a-z0-9+.-]{0,30}", u.scheme or "") or not host:
        return "other"
    if host in own:
        return "this address"
    return f"{u.scheme}://" + (f"[{host}]" if ":" in host else host) + (f":{port}" if port else "")


@router.post("/api/csp-report", status_code=204, dependencies=[Depends(limit("csp-report", CSP_REPORT))])
async def csp_report(request: Request):
    raw = await request.body()
    try:
        payload = json.loads(raw) if len(raw) <= MAX_BYTES else None
    except (ValueError, UnicodeDecodeError):
        payload = None
    own = request.app.state.settings.api_hosts
    for body in _bodies(payload)[:MAX_REPORTS]:
        log.warning("CSP blocked %s: %s", directive_of(body["directive"]), blocked_of(body["blocked"], own))
    return Response(status_code=204)
