"""Open-source evaluation 6.6: security headers, outermost of the app's layers, so a refusal (403, 413, 421) carries
them too. Added only when the answer doesn't set them already, so a download's own headers stay single.
- Every answer: nosniff and no-referrer (nothing in Steward reads Referer, and a current browser's same-origin fetch
  still sends its Origin; some older browsers, from before Sec-Fetch-Site, send Origin: null instead, and api/origin.py
  refuses those writes), and HSTS when the request came over HTTPS. Behind tailscale serve or steward-proxy that is the proxies'
  X-Forwarded-Proto, which `steward serve` trusts (STEWARD_TRUSTED_PROXIES); never on http://localhost.
- HTML answers (index.html, the only page): the CSP, COOP, and issue #14's layers: X-Frame-Options beside
  frame-ancestors for clients that read only the older header, a Permissions-Policy that turns off device features
  Steward never uses (passkeys, the clipboard and sound keep their defaults), and Reporting-Endpoints for the CSP's
  report-to. Downloads are attachments of fixed types and JSON is never rendered, and a CSP on a PDF or SVG can upset
  the browser's own viewer.
The CSP allows only Steward's own files, plus the inline first-paint script by its hash (steward.web) and the select
chevron's data: image (styles/base.css). React's style props go through the CSSOM, which style-src doesn't govern.
Trusted Types (issue #14): a string may reach an HTML sink only through the one named policy celebrate.ts makes for
its fixed SVG. What the CSP blocks is reported to /api/csp-report (api/csp_report.py): report-to for Chromium,
report-uri for the browsers without the Reporting API."""
from starlette.datastructures import MutableHeaders

EVERY = (("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"))
HSTS = ("Strict-Transport-Security", "max-age=31536000")
TRUSTED_TYPES_POLICY = "celebrate"
REPORT_PATH = "/api/csp-report"
REPORT_GROUP = "csp"
OFF = ("accelerometer", "camera", "display-capture", "geolocation", "gyroscope", "hid", "magnetometer", "microphone",
       "midi", "payment", "serial", "usb")
PAGE = (("Cross-Origin-Opener-Policy", "same-origin"),
        ("X-Frame-Options", "DENY"),
        ("Permissions-Policy", ", ".join(f"{f}=()" for f in OFF)),
        ("Reporting-Endpoints", f'{REPORT_GROUP}="{REPORT_PATH}"'))


def content_security_policy(script_hashes: tuple[str, ...]) -> str:
    return "; ".join((
        "default-src 'self'",
        "script-src " + " ".join(("'self'", *script_hashes)),
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "require-trusted-types-for 'script'",
        f"trusted-types {TRUSTED_TYPES_POLICY}",
        f"report-uri {REPORT_PATH}",
        f"report-to {REPORT_GROUP}",
    ))


class SecurityHeaders:
    def __init__(self, app, csp: str):
        self.app = app
        self.csp = csp

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        https = scope.get("scheme") == "https"

        async def with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in EVERY:
                    headers.setdefault(name, value)
                if https:
                    headers.setdefault(*HSTS)
                if headers.get("content-type", "").startswith("text/html"):
                    headers.setdefault("Content-Security-Policy", self.csp)
                    for name, value in PAGE:
                        headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, with_headers)
