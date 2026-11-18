"""The NAS's only link to the gateway (spec 3.2): HTTP for health, redaction, usage, settings, the sent list and
prewarm, and a WebSocket the NAS opens for each turn. The gateway never connects to the NAS. The token comes from
pairing (ruling 14) and lives in data/advisor.token, mode 600; it isn't derived from steward.key."""
from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import httpx2

from steward import gateway_name
from steward.settings import Settings
from steward_boundary.pairing import PAIR_ALPHABET

REFUSED = "{gateway} refused that."


class GatewayUnavailable(Exception):
    """The gateway didn't answer: asleep, off, or not reachable."""


class GatewayRefused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class GatewayClient:
    def __init__(self, url: str, token: str, *, http: httpx2.Client | None = None, timeout: float = 10.0):
        self.url, self.token = url.rstrip("/"), token
        self._http = http or httpx2.Client(timeout=timeout)
        self._own = http is None

    def close(self) -> None:
        if self._own:
            self._http.close()

    def _call(self, method: str, path: str, **kw) -> dict:
        try:
            r = self._http.request(method, self.url + path, headers={"Authorization": f"Bearer {self.token}"}, **kw)
        except httpx2.HTTPError:
            raise GatewayUnavailable() from None
        if r.status_code >= 400:
            try:
                message = gateway_name.fill(r.json().get("error") or REFUSED)
            except ValueError:
                message = gateway_name.fill(REFUSED)
            raise GatewayRefused(r.status_code, message)
        return r.json()

    def health(self) -> dict:
        return self._call("GET", "/v1/health")

    def redact(self, text: str, issued: list[str] | None = None) -> dict:
        body = {"text": text} if issued is None else {"text": text, "issued": issued}
        return self._call("POST", "/v1/redact", json=body)

    def title(self, text: str) -> str | None:
        return self._call("POST", "/v1/title", json={"text": text}, timeout=5.0).get("title")

    def usage(self) -> dict:
        return self._call("GET", "/v1/usage")

    def settings(self) -> dict:
        return self._call("GET", "/v1/settings")

    def set_settings(self, **fields) -> dict:
        return self._call("POST", "/v1/settings", json=fields)

    def sent_since(self, since: datetime) -> dict:
        return self._call("GET", "/v1/sent", params={"since": since.isoformat()})

    def instructions(self) -> dict:
        """The fixed instructions and tool definitions behind a Getting ready row's hash (public issue #3)."""
        return self._call("GET", "/v1/instructions")

    def prewarm_plan(self, book_id: int, user_id: int) -> dict:
        return self._call("POST", "/v1/prewarm/plan", json={"book_id": book_id, "user_id": user_id})

    def prewarm(self, book_id: int, user_id: int, sha256: str) -> dict:
        return self._call("POST", "/v1/prewarm", json={"book_id": book_id, "user_id": user_id, "sha256": sha256})

    def connect(self, timeout: float = 5.0):
        from websockets.exceptions import InvalidHandshake
        from websockets.sync.client import connect
        try:
            return connect("ws" + self.url[4:] + "/v1/turn", additional_headers={"Authorization": f"Bearer {self.token}"},
                           open_timeout=timeout, close_timeout=2, max_size=2 ** 24)
        except (OSError, TimeoutError, InvalidHandshake):
            raise GatewayUnavailable() from None


def read_token(settings: Settings) -> str | None:
    p = settings.advisor_token_path
    return (p.read_text().strip() or None) if p.exists() else None


def client_from_settings(settings: Settings) -> GatewayClient | None:
    token = read_token(settings)
    return GatewayClient(settings.gateway_url, token) if settings.gateway_url and token else None


def new_code() -> str:
    raw = "".join(secrets.choice(PAIR_ALPHABET) for _ in range(16))
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def _write_token(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".new")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def pair(token_path: Path, url: str, code: str, *, http: httpx2.Client, sleep=time.sleep, wait_s: float = 600,
         every_s: float = 2) -> str:
    """Poll the gateway until `steward-gateway pair <code>` has armed it, then keep the token it answers once."""
    deadline = time.monotonic() + wait_s
    while True:
        try:
            r = http.post(url.rstrip("/") + "/v1/pair", json={"code": code}, timeout=5)
        except httpx2.HTTPError:
            r = None
        if r is not None and r.status_code == 200:
            _write_token(token_path, r.json()["token"])
            return "paired"
        if r is not None and r.status_code == 403:
            return "refused"
        if time.monotonic() >= deadline:
            return "timeout"
        sleep(every_s)


@dataclass(frozen=True)
class PairAnswer:
    outcome: Literal["paired", "refused", "not_waiting", "away"]
    tries_left: int | None = None


def pair_once(token_path: Path, url: str, code: str, *, http) -> PairAnswer:
    """Guided setup spec 6.2: one POST, no polling; the window is armed, because the person reads the code from it."""
    try:
        r = http.post(url.rstrip("/") + "/v1/pair", json={"code": code}, timeout=10)
    except httpx2.HTTPError:
        return PairAnswer("away")
    if r.status_code == 200:
        try:
            _write_token(token_path, r.json()["token"])
        except (ValueError, KeyError, TypeError):
            return PairAnswer("away")
        return PairAnswer("paired")
    if r.status_code == 403:
        try:
            left = r.json().get("tries_left")
        except (ValueError, AttributeError):
            left = None
        return PairAnswer("refused", left if isinstance(left, int) and not isinstance(left, bool) else None)
    if r.status_code == 404:
        return PairAnswer("not_waiting")
    return PairAnswer("away")
