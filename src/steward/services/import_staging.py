"""Files staged for one batch (import/export spec P2, P3, P38-P40): in this process's memory only, bound to the
person and the book, gone after 30 idle minutes, at commit, on removal and on restart. A 200 MB cap counts what every
batch holds: each upload's decoded text, each file's table and parse, and its one held re-parse. A person keeps at most
3 open batches per book. Nothing from a file touches disk before commit, and nothing here talks to a model (P1)."""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from steward.services.importers.decode import NO_OFX_ROWS, FileRefused, decode, kind_of
from steward.services.importers.layouts import (Layout, Parsed, Table, check_amounts, identify, layout_key, parse,
                                                read_table)
from steward.services.importers.ofx import statements

IDLE = timedelta(minutes=30)
CAP_BYTES = 200 * 1024 * 1024
MAX_FILES = 30
MAX_ROWS = 100_000
EXPIRED = "These files expired. Add them again."
BUSY = "Steward is busy with other files. Try again in a few minutes."
TOO_MANY = "A batch holds up to 30 files. Import these, then add the rest."
TOO_MANY_ROWS = "A batch holds up to 100,000 rows. Import these, then add the rest."
SAME_FILE = "This file is already in the batch."
MAX_BATCHES = 3                                  # open batches per person per book; a 4th drops the least recently touched

# What staging holds, in bytes, estimated from counts (cheap, and never under what's held). Measured with tracemalloc on
# CPython 3.12 over the bank fixtures (tests/fixtures/banks) and on 5,000-20,000-row synthetic files: wide 2-character
# cells, mostly empty cells, one 1-character column, long unique and non-ASCII descriptions. Per ASCII cell, beyond its
# characters: 8-50 bytes measured (8 for an empty cell, the shared ""). Per table row: about 170. Per parsed row,
# beyond its description: 160-175 on big files, up to about 580 on 2-row fixtures (the Parsed's own overhead). Every
# estimate came out at 1.0-4.6 times the measured size. A str holds up to 2 bytes a character (non-ASCII), so a table's
# characters and a parse's descriptions count twice.
SLOT_BYTES = 8                                   # a cell's slot in its row's tuple
CELL_BYTES = 56                                  # a non-empty cell's str object, beyond its characters
TABLE_ROW_BYTES = 176                            # a table row: its tuples and its line number
ROW_BYTES = 200                                  # a parsed row or row error, beyond its description
PARSE_BYTES = 2048                               # one Parsed's own tuples and dict
# The check before parsing an upload: held text, table and parse came to 6.6-33 times the raw bytes on files over
# 100 KB (about 20 for a bank-shaped CSV), and up to 46 on 100-byte fixtures where PARSE_BYTES dominates.
RAW_FACTOR = 24


def table_weight(table: Table, size: int) -> int:
    """A CSV's table: its characters (at most the decoded text's bytes, twice), each cell and each row."""
    cells = len(table.header) + sum(len(c) for _, c in table.rows)
    filled = sum(1 for c in table.header if c) + sum(1 for _, row in table.rows for c in row if c)
    return 2 * size + cells * SLOT_BYTES + filled * CELL_BYTES + (len(table.rows) + 1) * TABLE_ROW_BYTES


def parse_weight(parsed: Parsed) -> int:
    return (PARSE_BYTES + (len(parsed.rows) + len(parsed.errors)) * ROW_BYTES
            + 2 * sum(len(r.raw_description) for r in parsed.rows))


class StagingRefused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(18)}"


@dataclass
class Staged:
    token: str
    name: str
    kind: str                                    # csv | ofx
    size: int                                    # the upload's bytes
    sha256: str
    parsed: Parsed
    table: Table | None = None                   # csv only: kept so a changed layout re-parses this one file
    layout: Layout | None = None
    hint_key: str | None = None                  # ofx only: "ofx:<ORG or BANKID>:<last 4>"
    last4: str | None = None
    card: bool = False                           # ofx only: a CCSTMTRS
    weight: int = 0                              # the table and the parse, in bytes (the upload's text is the batch's)
    _reparse: tuple[str, Parsed, int] | None = field(default=None, repr=False)   # the latest: signature, parse, weight

    @property
    def reparse(self) -> Parsed | None:
        return self._reparse[1] if self._reparse else None

    @property
    def held(self) -> int:
        return self.weight + (self._reparse[2] if self._reparse else 0)


@dataclass
class Batch:
    id: str
    user_id: int
    book_id: int
    touched: datetime
    files: dict[str, Staged] = field(default_factory=dict)
    uploads: dict[str, int] = field(default_factory=dict)       # sha256 -> decoded text bytes (P38 and the cap)

    @property
    def rows(self) -> int:
        return sum(len(f.parsed.rows) for f in self.files.values())

    @property
    def held(self) -> int:
        """What this batch holds against the cap: each upload's decoded text, each file's table, parse and re-parse."""
        return sum(self.uploads.values()) + sum(f.held for f in self.files.values())


def build(name: str, raw: bytes, today: date, remembered_for: Callable[[str], Layout | None]) -> tuple[str, int, list[Staged]]:
    """Decodes, detects, finds the layout and parses one file: (its SHA-256, its decoded size, one entry per account).
    FileRefused carries the spec's words for a file that can't be read."""
    sha = hashlib.sha256(raw).hexdigest()
    text = decode(raw)
    kind = kind_of(name, raw, text)
    size = len(text.encode("utf-8"))
    if kind == "ofx":
        found = statements(text)
        if all(not s.rows and not s.errors for s in found):
            raise FileRefused(NO_OFX_ROWS)
        many = len(found) > 1
        out = []
        for s in found:
            parsed = Parsed(s.rows, s.errors, {})
            out.append(Staged(_token("f"), f"{name} · ••{s.last4}" if many and s.last4 else name, "ofx", len(raw), sha,
                              parsed, hint_key=s.hint_key, last4=s.last4, card=s.card, weight=parse_weight(parsed)))
        return sha, size, out
    table = read_table(text)
    key = layout_key(table)
    layout = identify(table, key, remembered_for(key))
    check_amounts(table, layout)
    parsed = parse(table, layout, today)
    return sha, size, [Staged(_token("f"), name, "csv", len(raw), sha, parsed, table=table, layout=layout,
                              weight=table_weight(table, size) + parse_weight(parsed))]


class ImportStaging:
    """On app.state (P3). Timed with steward.deps.now(), so tests move it with the fake clock."""

    def __init__(self, cap: int = CAP_BYTES, idle: timedelta = IDLE, max_rows: int = MAX_ROWS):
        self.cap, self.idle, self.max_rows = cap, idle, max_rows
        self._lock = threading.Lock()
        self._batches: dict[str, Batch] = {}

    def _sweep(self, now: datetime) -> None:
        for bid in [b for b, x in self._batches.items() if now - x.touched >= self.idle]:
            del self._batches[bid]

    def _held(self) -> int:
        return sum(b.held for b in self._batches.values())

    def held_bytes(self) -> int:
        with self._lock:
            return self._held()

    def _live(self, batch: Batch) -> None:
        if self._batches.get(batch.id) is not batch:
            raise StagingRefused(410, EXPIRED)

    def _mine(self, user_id: int, book_id: int, batch_id: str) -> Batch:
        b = self._batches.get(batch_id)
        if b is None or b.user_id != user_id or b.book_id != book_id:
            raise StagingRefused(410, EXPIRED)
        return b

    def batch(self, user_id: int, book_id: int, batch_id: str | None, now: datetime) -> Batch:
        with self._lock:
            self._sweep(now)
            if batch_id is None:
                mine = [x for x in self._batches.values() if x.user_id == user_id and x.book_id == book_id]
                if len(mine) >= MAX_BATCHES:
                    del self._batches[min(mine, key=lambda x: x.touched).id]
                b = Batch(_token("b"), user_id, book_id, now)
                self._batches[b.id] = b
                return b
            b = self._mine(user_id, book_id, batch_id)
            b.touched = now
            return b

    find = batch

    def room_for(self, raw_bytes: int, now: datetime) -> None:
        """Before parsing an upload: BUSY when what's held plus this file's worst case would pass the cap."""
        with self._lock:
            self._sweep(now)
            if self._held() + raw_bytes * RAW_FACTOR > self.cap:
                raise StagingRefused(503, BUSY)

    def add(self, batch: Batch, sha: str, size: int, files: list[Staged], now: datetime, others: int = 0) -> None:
        with self._lock:
            self._sweep(now)
            self._live(batch)
            if len(batch.uploads) + others >= MAX_FILES:      # others: the book's staged statements, one batch of 30
                raise StagingRefused(422, TOO_MANY)
            if self._held() + size + sum(f.held for f in files) > self.cap:
                raise StagingRefused(503, BUSY)
            if batch.rows + sum(len(f.parsed.rows) for f in files) > self.max_rows:
                raise StagingRefused(422, TOO_MANY_ROWS)
            batch.uploads[sha] = size
            for f in files:
                batch.files[f.token] = f
            batch.touched = now

    def parsed_for(self, batch: Batch, f: Staged, layout: Layout, today: date, now: datetime) -> Parsed:
        """Spec, Performance: a staged file keeps its parse; a changed layout re-parses this one file. Only the latest
        re-parse is kept, and it counts against the cap: one that would pass it is BUSY, and the held parse stays."""
        if f.table is None or f.layout is None or layout.signature() == f.layout.signature():
            return f.parsed
        sig = json.dumps(layout.signature())
        with self._lock:
            held = f._reparse
        if held is not None and held[0] == sig:
            return held[1]
        parsed = parse(f.table, layout, today)               # outside the lock: the parse is the slow part
        weight = parse_weight(parsed)
        with self._lock:
            self._sweep(now)
            self._live(batch)
            if batch.files.get(f.token) is not f:                # removed meanwhile: its weight would go uncounted
                raise StagingRefused(410, EXPIRED)
            before = f._reparse[2] if f._reparse else 0
            if self._held() - before + weight > self.cap:
                raise StagingRefused(503, BUSY)
            f._reparse = (sig, parsed, weight)
            batch.touched = now
        return parsed

    def drop_file(self, user_id: int, book_id: int, token: str, now: datetime) -> bool:
        with self._lock:
            self._sweep(now)
            b = next((x for x in self._batches.values() if token in x.files), None)
            if b is None or b.user_id != user_id or b.book_id != book_id:
                return False
            gone = b.files.pop(token)
            if not any(f.sha256 == gone.sha256 for f in b.files.values()):
                b.uploads.pop(gone.sha256, None)
            b.touched = now
            return True

    def drop(self, batch_id: str) -> None:
        with self._lock:
            self._batches.pop(batch_id, None)
