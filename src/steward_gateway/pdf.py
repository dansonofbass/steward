"""Opening statement PDFs for the NAS (remote-reading amendment P57-P61). A NAS whose kernel can't install the
sandbox's seccomp filter sends each statement here; this machine's own copy of the sandbox (steward_pdf) opens it,
behind the same rlimits and filter plus a Landlock wall, one child at a time. Nothing here touches Ollama or the GPU, so
it never waits for the categorizer. The PDF lives in this request's memory and the child's stdin only: never a file, a
cache, a ledger row or a log line. Health lists extract and render, and the routes run, only once this machine's check
shows the filter, the wall and a canary read inside both (P58). Nothing here can reach Anthropic."""
from __future__ import annotations

import asyncio
import base64
import functools
from collections.abc import Callable

from fastapi import HTTPException, Request

from steward_pdf.sandbox import MAX_BYTES, MAX_PAGES, can_wall, confinement, run_extract, run_render

PDF_OFF = "This machine can't open PDFs safely right now."
NOT_UNDERSTOOD = {"error": "That request wasn't understood."}
TOO_LARGE = {"error": "That request is too large."}


class PdfOff(Exception):
    """This machine's check didn't show the filter, the wall and the canary holding (P58)."""


@functools.cache
def _report() -> dict:
    """The check, once per gateway process: the kernel doesn't change under a running service."""
    return confinement()


class PdfReader:
    def __init__(self, *, check: Callable[[], dict] = _report, extract=run_extract, render=run_render):
        self._check, self._extract, self._render = check, extract, render
        self._ok: bool | None = None
        self._one = asyncio.Semaphore(1)

    async def ok(self) -> bool:
        if self._ok is None:
            self._ok = can_wall(await asyncio.to_thread(self._check))
        return self._ok

    async def features(self) -> list[str]:
        return ["extract", "render"] if await self.ok() else []

    async def extract(self, data: bytes | bytearray) -> dict:
        """The child's answer as the parent's checks left it: {"pages": [...]} or {"error": key}."""
        if not await self.ok():
            raise PdfOff()
        async with self._one:
            out = await asyncio.to_thread(self._extract, data)      # P59: the child itself refuses without the wall
        return {"error": out.error} if out.error else {"pages": out.pages}

    async def render(self, data: bytes | bytearray, n: int) -> dict:
        """One page's picture as render_page wrote it (checked again by the parent), or {"error": key}."""
        if not await self.ok():
            raise PdfOff()
        async with self._one:
            pic = await asyncio.to_thread(self._render, data, n)
        if pic.error:
            return {"error": pic.error}
        return {"png": base64.b64encode(pic.png).decode("ascii"), "width_px": pic.width, "height_px": pic.height,
                "n": n}

    async def close(self) -> None:
        pass


def page_of(request: Request) -> int:
    raw = request.query_params.get("page", "")
    if not (raw.isascii() and raw.isdigit()) or not 1 <= int(raw) <= MAX_PAGES:
        raise HTTPException(422, detail=NOT_UNDERSTOOD)
    return int(raw)


async def read_pdf_body(request: Request) -> bytearray:
    """P57, P61: application/pdf only, read into memory as it streams (never multipart, never a temp file); BodyCap
    already refused a declared or streamed body past 15 MB + 64 KB."""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/pdf":
        raise HTTPException(415, detail=NOT_UNDERSTOOD)
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > MAX_BYTES:
            raise HTTPException(413, detail=TOO_LARGE)
    if not buf:
        raise HTTPException(422, detail=NOT_UNDERSTOOD)
    return buf
