"""Serve the built web app (web/dist) from the same process as the API."""
import base64
import hashlib
import mimetypes
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

DEFAULT_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
ASSET_CACHE = "public, max-age=31536000, immutable"  # Vite hashes asset names, so they never change in place
# The build writes both beside each asset over 1 KB (web/scripts/precompress.mjs); the first the browser takes wins.
PACKED = (("br", ".br"), ("gzip", ".gz"))
REFUSED = frozenset({"q=0", "q=0.0", "q=0.00", "q=0.000"})

# The built index.html's inline scripts (the first-paint sky phase), any <script> without src=. The CSP allows each
# by its hash (steward.api.headers).
INLINE_SCRIPT = re.compile(r"<script\b(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script\s*>", re.S | re.I)


def inline_script_hashes(dist: Path | None) -> tuple[str, ...]:
    """The CSP sources ('sha256-...') for index.html's inline scripts, read once when the app is made. Vite copies
    web/index.html's inline script into dist byte for byte, so the hash follows any edit with no hand-kept value.
    read_text's universal newlines match the browser, which hashes the script with CR LF already made LF."""
    index = (dist or DEFAULT_DIST).resolve() / "index.html"
    if not index.is_file():
        return ()
    html = index.read_text(encoding="utf-8")
    return tuple(f"'sha256-{base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()}'"
                 for body in INLINE_SCRIPT.findall(html) if body.strip())


def accepts(header: str, coding: str) -> bool:
    """Whether an Accept-Encoding header takes `coding`: named, and not with q=0."""
    for part in header.lower().split(","):
        name, *params = (p.strip() for p in part.split(";"))
        if name == coding:
            return not any(p.replace(" ", "") in REFUSED for p in params)
    return False


def asset_response(file: Path, accept: str) -> FileResponse:
    """A hashed asset, from its precompressed copy when the browser takes one (phase 18: the JS and CSS went out
    uncompressed, 606 KB on a first open, 400-700 ms on cellular)."""
    headers = {"Cache-Control": ASSET_CACHE, "Vary": "Accept-Encoding"}
    for coding, suffix in PACKED:
        packed = file.with_name(file.name + suffix)
        if accepts(accept, coding) and packed.is_file():
            return FileResponse(packed, media_type=mimetypes.guess_type(file.name)[0],
                                headers={**headers, "Content-Encoding": coding})
    return FileResponse(file, headers=headers)


def mount_web(app: FastAPI, dist: Path | None) -> None:
    dist = (dist or DEFAULT_DIST).resolve()
    index = dist / "index.html"
    if not index.is_file():
        return  # no build present: API only (development runs Vite's dev server with a proxy)

    not_found = {"error": "Not found."}

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def spa(path: str, request: Request):
        if path == "api" or path.startswith("api/") or request.method not in ("GET", "HEAD"):
            return JSONResponse(not_found, status_code=404)
        candidate = None
        if path:
            try:
                candidate = (dist / path).resolve()
            except (ValueError, OSError):
                candidate = None  # e.g. a null byte in the path: treat as no such file
        if candidate is not None and candidate.is_file() and candidate.is_relative_to(dist):
            if path.startswith("assets/"):
                return asset_response(candidate, request.headers.get("accept-encoding", ""))
            return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
        if path.startswith("assets/"):
            return JSONResponse(not_found, status_code=404)  # a stale tab after a redeploy must not get HTML as a script
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
