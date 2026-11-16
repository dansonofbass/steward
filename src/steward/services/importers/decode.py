"""Bytes to text, and what a file is (import/export spec P22; Layout detection › Order 1). Encodings are UTF-8,
cp1252 and UTF-16 (by its BOM). An Excel file, or a ZIP renamed to .csv, is refused in plain words. Nothing here
writes anything anywhere: the file lives in memory only (P3)."""
from __future__ import annotations

EXCEL = "Excel files can't be read yet. Save it as CSV and try again."
NOT_OURS = "Not a CSV, OFX or QFX file."
UNREADABLE = "This file couldn't be read as a CSV. Save it again as a plain CSV and try once more."
DECIMAL_COMMA = "Amounts like 1.234,56 can't be read yet."
NO_ROWS = "This file has no rows."
NO_OFX_ROWS = "No transactions were found in this OFX/QFX file."
DELIMITERS = (",", ";", "\t", "|")
_TEXT_NAMES = (".csv", ".tsv", ".txt")
_OFX_NAMES = (".ofx", ".qfx")
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"     # an old .xls


class FileRefused(ValueError):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16")             # the BOM picks the byte order and is dropped
        except UnicodeDecodeError:
            raise FileRefused(UNREADABLE) from None
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def kind_of(name: str, raw: bytes, text: str) -> str:
    """"ofx" or "csv". An OFX file is recognized by its header within the first 4,000 characters or by its name (as
    today's detect); a CSV by its name or by a delimiter in its first non-blank line."""
    lower = name.lower()
    if raw[:4] == b"PK\x03\x04" or raw[:8] == _OLE or lower.endswith((".xlsx", ".xls")):
        raise FileRefused(EXCEL)
    head = text[:4000].upper()
    if "<OFX>" in head or "OFXHEADER" in head or lower.endswith(_OFX_NAMES):
        return "ofx"
    if "\x00" in text:
        raise FileRefused(NOT_OURS)
    if lower.endswith(_TEXT_NAMES):
        return "csv"
    first = next((line for line in text.splitlines() if line.strip()), "")
    if any(d in first for d in DELIMITERS):
        return "csv"
    raise FileRefused(NOT_OURS)
