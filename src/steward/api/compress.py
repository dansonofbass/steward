"""Phase 18: API reads go out gzipped when the browser asks (they went out uncompressed: /accounts 5.6 KB, /home and
/plan more). GET and HEAD under /api/ only:
- the static files have their own precompressed copies (steward.web);
- a write's answer may carry a secret (a new grant), so nothing an attacker could guess at is compressed;
- Ask's stream is a POST.
Encrypted downloads and PDFs gain nothing, so they are left as they are. A browser that refuses gzip (q=0) gets none."""
from starlette.datastructures import Headers
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES, GZipMiddleware

from steward.web import accepts

MIN_BYTES = 1024
LEVEL = 6
EXCLUDED = (*DEFAULT_EXCLUDED_CONTENT_TYPES, "application/octet-stream", "application/pdf")


class CompressReads:
    def __init__(self, app):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=MIN_BYTES, compresslevel=LEVEL, exclude_content_types=EXCLUDED)

    async def __call__(self, scope, receive, send):
        if (scope["type"] == "http" and scope["method"] in ("GET", "HEAD") and scope["path"].startswith("/api/")
                and accepts(Headers(scope=scope).get("accept-encoding", ""), "gzip")):
            return await self.gzip(scope, receive, send)
        return await self.app(scope, receive, send)
