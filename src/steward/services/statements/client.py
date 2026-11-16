"""The NAS's link to the statement reader on the gateway (PDF statements spec, The NAS side; P27, P31). Built by
categorizer_client.client_for's rule: the paired gateway with its token, else nothing. One request at a time (a
lock), with a 150-second timeout (the gateway's is 120). Never raises: a failure returns None and leaves plain words
in last_error. The answer is held to the wire's schema again before the reader uses it."""
from __future__ import annotations

import base64
import threading

import httpx2

from steward import gateway_name
from steward_boundary.statements_wire import page_answer_errors, shape_errors
from steward_pdf.sandbox import OUT_CAP, Outcome, Rendered, parse_extract, parse_render

LAYOUT_TIMEOUT_S = 150.0
PAGE_TIMEOUT_S = 120.0
PDF_TIMEOUT_S = 150.0          # remote-reading P57: the gateway's child has 90 s, and one runs at a time
TOO_SLOW = "{gateway} took too long to answer"
UNREACHABLE = "could not reach {gateway}"
ERROR_STATUS = "{gateway} answered with an error (HTTP {status})"
UNREADABLE = "{gateway} sent a reply that could not be read"
AWAY = "away"                  # P66: no answer, a timeout, or 503 (the gateway can't open PDFs now): wait, spend no try


def statement_features(health: dict | None) -> frozenset[str] | None:
    """What the gateway says its statement reader can do; None from a gateway too old to say (P27)."""
    if not isinstance(health, dict) or not isinstance(health.get("statement_features"), list):
        return None
    return frozenset(f for f in health["statement_features"] if isinstance(f, str))


def remote_state(client, health: dict | None, feature: str = "layout") -> str:
    """P31: answering, waiting (away, or the model isn't pulled), old (no statement_features) or unpaired."""
    if not getattr(client, "paired", False):
        return "unpaired"
    if health is None:
        return "waiting"
    feats = statement_features(health)
    if feats is None:
        return "old"
    return "answering" if feature in feats else "waiting"


class NullStatementClient:
    paired = False
    last_error: str | None = None
    last_model: str | None = None

    def layout(self, pages: list[dict], hint: dict | None) -> dict | None:
        return None

    def page(self, *a, **k) -> dict | None:
        return None

    def extract(self, data) -> str:
        return AWAY

    def render(self, data, n: int) -> str:
        return AWAY

    def close(self) -> None:
        pass


class HttpStatementClient:
    paired = True

    def __init__(self, base_url: str, token: str, *, transport: httpx2.BaseTransport | None = None,
                 layout_timeout_s: float = LAYOUT_TIMEOUT_S):
        self.base_url, self.layout_timeout_s = base_url.rstrip("/"), layout_timeout_s
        self._client = httpx2.Client(timeout=layout_timeout_s, transport=transport)
        self._headers = {"Authorization": f"Bearer {token}"}
        self._one = threading.Lock()
        self.last_error: str | None = None
        self.last_model: str | None = None            # which model gave the last layout (statement_layout.model)

    def close(self) -> None:
        self._client.close()

    def layout(self, pages: list[dict], hint: dict | None) -> dict | None:
        with self._one:
            try:
                r = self._client.post(self.base_url + "/v1/statements/layout", json={"pages": pages, "hint": hint},
                                      headers=self._headers, timeout=self.layout_timeout_s)
            except httpx2.TimeoutException:
                self.last_error = gateway_name.fill(TOO_SLOW)
                return None
            except Exception:                         # noqa: BLE001 - any failure means "not answering"
                self.last_error = gateway_name.fill(UNREACHABLE)
                return None
        if r.status_code != 200:
            self.last_error = gateway_name.fill(ERROR_STATUS).replace("{status}", str(r.status_code))
            return None
        try:
            body = r.json()
        except Exception:                             # noqa: BLE001 - not JSON
            body = None
        layout = body.get("layout") if isinstance(body, dict) else None
        if layout is None or shape_errors(layout):
            self.last_error = gateway_name.fill(UNREADABLE)
            return None
        model = body.get("model")
        self.last_model = model[:60] if isinstance(model, str) and model.strip() and model.isprintable() else "unknown"
        self.last_error = None
        return layout

    def page(self, png: bytes, n: int, of: int, width: int, height: int, want: str = "rows") -> dict | None:
        """P26: one page picture to the paired gateway (the NAS waits 120 s; the gateway's limit is 90). Never raises."""
        body = {"page": n, "of": of, "image": base64.b64encode(png).decode("ascii"), "width_px": width,
                "height_px": height, "want": want}
        with self._one:
            try:
                r = self._client.post(self.base_url + "/v1/statements/page", json=body, headers=self._headers,
                                      timeout=PAGE_TIMEOUT_S)
            except httpx2.TimeoutException:
                self.last_error = gateway_name.fill(TOO_SLOW)
                return None
            except Exception:                         # noqa: BLE001 - any failure means "not answering"
                self.last_error = gateway_name.fill(UNREACHABLE)
                return None
        if r.status_code != 200:
            self.last_error = gateway_name.fill(ERROR_STATUS).replace("{status}", str(r.status_code))
            return None
        try:
            got = r.json()
        except Exception:                             # noqa: BLE001 - not JSON
            got = None
        answer = got.get("page") if isinstance(got, dict) else None
        if answer is None or page_answer_errors(answer):
            self.last_error = gateway_name.fill(UNREADABLE)
            return None
        model = got.get("model")
        self.last_model = model[:60] if isinstance(model, str) and model.strip() and model.isprintable() else "unknown"
        self.last_error = None
        return answer

    def extract(self, data: bytes) -> Outcome | str | None:
        """Remote-reading P57, P62: the PDF to the gateway's sandbox, raw; its answer checked exactly as the local
        child's stdout would be. AWAY when the gateway can't be reached, timed out or can't open PDFs now (503); None
        when it answered with any other error. Never raises."""
        got = self._pdf("/v1/statements/extract", data)
        return parse_extract(got[0]) if isinstance(got, tuple) else got

    def render(self, data: bytes, n: int) -> Rendered | str | None:
        got = self._pdf(f"/v1/statements/render?page={n}", data)
        return parse_render(got[0], n) if isinstance(got, tuple) else got

    def _pdf(self, path: str, data: bytes):
        """(the body, or None when it ran past 16 MB), AWAY or None. The answer is read as it streams and stopped
        past the child's own output cap."""
        headers = {**self._headers, "Content-Type": "application/pdf"}
        with self._one:
            try:
                with self._client.stream("POST", self.base_url + path, content=bytes(data), headers=headers,
                                         timeout=PDF_TIMEOUT_S) as r:
                    if r.status_code != 200:
                        self.last_error = gateway_name.fill(ERROR_STATUS).replace("{status}", str(r.status_code))
                        return AWAY if r.status_code == 503 else None
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        buf += chunk
                        if len(buf) > OUT_CAP:
                            self.last_error = gateway_name.fill(UNREADABLE)
                            return (None,)
            except httpx2.TimeoutException:
                self.last_error = gateway_name.fill(TOO_SLOW)
                return AWAY
            except Exception:                         # noqa: BLE001 - any failure to reach it means "away"
                self.last_error = gateway_name.fill(UNREACHABLE)
                return AWAY
        self.last_error = None
        return (bytes(buf),)


def statement_client_for(settings) -> HttpStatementClient | NullStatementClient:
    from steward.advisor.gateway import read_token
    token = read_token(settings) if settings.gateway_url else None
    if settings.gateway_url and token:
        return HttpStatementClient(settings.gateway_url, token)
    return NullStatementClient()
