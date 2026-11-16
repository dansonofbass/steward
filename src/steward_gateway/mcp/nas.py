"""The gateway's client for Steward on the NAS, used only for Claude Code (spec 7, ruling 2). Every request carries the
grant and the gateway's pairing token (final review ruling I1a: the grant alone opens nothing); the NAS opens the book
through open_book_by_grant. Nothing here logs a result."""
from __future__ import annotations

from collections.abc import Callable

import httpx2


class NasAway(Exception):
    """The NAS didn't answer, or answered with something that isn't JSON."""


class NasRefused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


NOT_PAIRED = "This machine isn't paired with Steward yet. Run steward advisor pair where Steward runs."


class NasClient:
    def __init__(self, base_url: str, gateway_token: Callable[[], str | None], *,
                 http: httpx2.AsyncClient | None = None, timeout: float = 30.0):
        self.base = base_url.rstrip("/")
        self._gateway_token = gateway_token          # read per request, so pairing later needs no restart
        self._http = http or httpx2.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._http.aclose()

    async def _call(self, method: str, path: str, grant: str, body: dict | None = None) -> dict:
        paired = self._gateway_token()
        if not paired:
            raise NasRefused(503, NOT_PAIRED)
        kw = {"json": body} if body is not None else {}
        headers = {"Authorization": f"Bearer {grant}", "X-Steward-Gateway": paired}
        try:
            r = await self._http.request(method, self.base + path, headers=headers, **kw)
        except httpx2.HTTPError:
            raise NasAway() from None
        if r.status_code >= 400:
            try:
                message = r.json().get("error") or "Steward refused that."
            except (ValueError, AttributeError):
                message = "Steward refused that."
            raise NasRefused(r.status_code, message)
        try:
            out = r.json()
        except ValueError:
            raise NasAway() from None
        if not isinstance(out, dict):
            raise NasAway()
        return out

    async def tools(self, slug: str, grant: str) -> dict:
        return await self._call("GET", f"/api/b/{slug}/advisor/tools", grant)

    async def call(self, slug: str, grant: str, name: str, input: dict) -> dict:
        return await self._call("POST", f"/api/b/{slug}/advisor/tools/{name}", grant, {"input": input})

    async def finish(self, slug: str, grant: str, call_id: str, outcome: str, check: str | None = None,
                     path: str | None = None) -> dict:
        body = {"outcome": outcome} if outcome == "sent" else {"outcome": outcome, "check": check, "path": path}
        return await self._call("POST", f"/api/b/{slug}/advisor/calls/{call_id}", grant, body)
