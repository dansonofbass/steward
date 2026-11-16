"""CSV files for download (import/export spec P24, P25): UTF-8 with a BOM, for Excel, and CRLF line ends. Every text
cell that a spreadsheet would read as a formula gets a leading apostrophe; amounts are plain decimals and never
touched."""
from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence

from fastapi import Response

_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def guard(text: str) -> str:
    return "'" + text if text and text.startswith(_FORMULA) else text


def decimal(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"


def write(rows: Iterable[Sequence[str]]) -> bytes:
    buf = io.StringIO(newline="")
    csv.writer(buf, lineterminator="\r\n").writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")


def download(body: bytes, filename: str) -> Response:
    """The browser downloads it natively; nothing caches it. Filenames hold the slug and dates, never a name."""
    return Response(body, media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff"})
