"""The monthly spending ledger (spec 9.1), in SQLite in the gateway's state folder. Before each Anthropic request the
worst case is reserved; reservations are serialized (a lock and BEGIN IMMEDIATE), so concurrent turns can't overshoot
together. After the response the reservation settles to the real cost. A reservation left open by a crash settles at
its full amount (ruling 1). The sent list keeps (time, sha256, bytes, book, channel) of every recorded part sent, with
no content, for the NAS's nightly cross-check (spec 4.6)."""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from steward_gateway.config import ANSWER_MODELS, MAX_TOKENS, GatewayConfig
from steward_gateway.prices import MIN_REQUEST_BYTES, ND_PER_CENT, cents, estimate_nd, reserve_price

SCHEMA = """
CREATE TABLE IF NOT EXISTS spend (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, month TEXT NOT NULL, book_id INTEGER, user_id INTEGER, turn_id TEXT,
  channel TEXT NOT NULL, model TEXT NOT NULL, reserved_nd INTEGER NOT NULL, cost_nd INTEGER,
  status TEXT NOT NULL CHECK (status IN ('reserved', 'settled', 'released')));
CREATE INDEX IF NOT EXISTS spend_month ON spend (month, status);
CREATE TABLE IF NOT EXISTS sent (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, book_id INTEGER,
  channel TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sent_at ON sent (at);
CREATE TABLE IF NOT EXISTS setting (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
COMMITTED = "COALESCE(SUM(CASE status WHEN 'reserved' THEN reserved_nd WHEN 'settled' THEN cost_nd ELSE 0 END), 0)"


class CapReached(Exception):
    """This request would take the month past the cap. Nothing was sent."""


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat()


class Ledger:
    def __init__(self, path: Path, tz: str, default_cap_cents: int, max_cap_cents: int, default_model: str):
        self.path, self.tz = path, ZoneInfo(tz)
        self.default_cap_cents, self.max_cap_cents, self.default_model = default_cap_cents, max_cap_cents, default_model
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    def month(self, now: datetime) -> str:
        return now.astimezone(self.tz).strftime("%Y-%m")

    def settle_stale(self) -> int:
        with self._lock, self._conn() as c:
            return c.execute("UPDATE spend SET cost_nd = reserved_nd, status = 'settled' WHERE status = 'reserved'").rowcount

    def _setting(self, c: sqlite3.Connection, key: str) -> str | None:
        row = c.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def cap_cents(self) -> int:
        with self._conn() as c:
            v = self._setting(c, "cap_cents")
        return int(v) if v is not None else self.default_cap_cents

    def _check_cap(self, value) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= self.max_cap_cents:
            raise ValueError(f"Choose a budget from $1 to ${self.max_cap_cents // 100}.")

    @staticmethod
    def _check_model(model) -> None:
        if model not in ANSWER_MODELS:
            raise ValueError("Choose Claude Opus 5.5 or Claude Sonnet 5.5.")

    def update_settings(self, *, cap_cents=None, model=None) -> None:
        """Check every value given, then save them all in one transaction: both or neither (final review)."""
        if cap_cents is not None:
            self._check_cap(cap_cents)
        if model is not None:
            self._check_model(model)
        rows = [(k, v) for k, v in (("cap_cents", None if cap_cents is None else str(cap_cents)), ("model", model))
                if v is not None]
        with self._lock, self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                c.executemany("INSERT INTO setting (key, value) VALUES (?, ?) "
                              "ON CONFLICT (key) DO UPDATE SET value = excluded.value", rows)
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise

    def set_cap_cents(self, value: int) -> None:
        self.update_settings(cap_cents=value)

    def model(self) -> str:
        with self._conn() as c:
            return self._setting(c, "model") or self.default_model

    def set_model(self, model: str) -> None:
        self.update_settings(model=model)

    def reserve(self, *, now: datetime, book_id: int | None, user_id: int | None, turn_id: str | None, channel: str,
                model: str, estimate_nd: int) -> int:
        with self._lock, self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                month = self.month(now)
                committed = c.execute(f"SELECT {COMMITTED} FROM spend WHERE month = ?", (month,)).fetchone()[0]
                cap = int(self._setting(c, "cap_cents") or self.default_cap_cents) * ND_PER_CENT
                if committed + estimate_nd > cap:
                    raise CapReached()
                rid = c.execute(
                    "INSERT INTO spend (at, month, book_id, user_id, turn_id, channel, model, reserved_nd, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reserved')",
                    (_iso(now), month, book_id, user_id, turn_id, channel, model, estimate_nd)).lastrowid
                c.execute("COMMIT")
                return rid
            except BaseException:
                c.execute("ROLLBACK")
                raise

    def settle(self, rid: int, cost_nd: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE spend SET cost_nd = ?, status = 'settled' WHERE id = ? AND status = 'reserved'",
                      (cost_nd, rid))

    def release(self, rid: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE spend SET cost_nd = 0, status = 'released' WHERE id = ? AND status = 'reserved'", (rid,))

    def state(self, now: datetime, cfg: GatewayConfig) -> dict:
        month = self.month(now)
        with self._conn() as c:
            spent, reserved = c.execute(
                "SELECT COALESCE(SUM(CASE WHEN status = 'settled' THEN cost_nd ELSE 0 END), 0), "
                "COALESCE(SUM(CASE WHEN status = 'reserved' THEN reserved_nd ELSE 0 END), 0) FROM spend WHERE month = ?",
                (month,)).fetchone()
            questions = c.execute("SELECT COUNT(DISTINCT turn_id) FROM spend WHERE month = ? AND channel = 'chat' "
                                  "AND status = 'settled'", (month,)).fetchone()[0]
        cap = self.cap_cents()
        worst = estimate_nd(MIN_REQUEST_BYTES, MAX_TOKENS, reserve_price(cfg, self.model()))
        return {"month": month, "cap_cents": cap, "max_cap_cents": self.max_cap_cents, "spent_cents": cents(spent),
                "reserved_cents": cents(reserved), "questions": questions,
                "warn": spent * 10 >= cap * ND_PER_CENT * 8,
                "can_ask": spent + reserved + worst <= cap * ND_PER_CENT, "model": self.model()}

    def usage(self, now: datetime, months: int = 12) -> dict:
        current = now.astimezone(self.tz)
        index = current.year * 12 + current.month - 1
        wanted = [f"{(index - i) // 12:04d}-{(index - i) % 12 + 1:02d}" for i in range(months - 1, -1, -1)]
        with self._conn() as c:
            rows = {r["month"]: r for r in c.execute(
                "SELECT month, COALESCE(SUM(cost_nd), 0) AS spent, "
                "COUNT(DISTINCT CASE WHEN channel = 'chat' THEN turn_id END) AS questions "
                "FROM spend WHERE status = 'settled' GROUP BY month")}
            by_book = [{"book_id": r["book_id"], "spent_cents": cents(r["spent"]), "questions": r["questions"]}
                       for r in c.execute(
                "SELECT book_id, COALESCE(SUM(cost_nd), 0) AS spent, "
                "COUNT(DISTINCT CASE WHEN channel = 'chat' THEN turn_id END) AS questions FROM spend "
                "WHERE status = 'settled' AND month = ? AND book_id IS NOT NULL GROUP BY book_id", (wanted[-1],))]
            by_person = [{"book_id": r["book_id"], "user_id": r["user_id"], "spent_cents": cents(r["spent"]),
                          "questions": r["questions"]} for r in c.execute(
                "SELECT book_id, user_id, COALESCE(SUM(cost_nd), 0) AS spent, "
                "COUNT(DISTINCT CASE WHEN channel = 'chat' THEN turn_id END) AS questions FROM spend "
                "WHERE status = 'settled' AND month = ? AND user_id IS NOT NULL GROUP BY book_id, user_id",
                (wanted[-1],))]
        return {"month": wanted[-1], "cap_cents": self.cap_cents(),
                "months": [{"month": m, "spent_cents": cents(rows[m]["spent"]) if m in rows else 0,
                            "questions": rows[m]["questions"] if m in rows else 0} for m in wanted],
                "by_book": by_book, "by_person": by_person}

    def record_sent(self, now: datetime, items: Sequence[tuple[str, int]], book_id: int | None, channel: str) -> None:
        with self._lock, self._conn() as c:
            c.executemany("INSERT INTO sent (at, sha256, bytes, book_id, channel) VALUES (?, ?, ?, ?, ?)",
                          [(_iso(now), sha, size, book_id, channel) for sha, size in items])

    def sent_since(self, since: datetime) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT at, sha256, bytes, book_id, channel FROM sent WHERE at >= ? ORDER BY id", (_iso(since),))]
