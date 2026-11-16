"""The statement reader (PDF statements spec P6, P7, P17, P22, P31-P33, P44; plan Engineering choices 5, 6, 10, 11).
One daemon thread on app.state.statements and one job at a time across every book: first files to extract (a learned
layout reads right after, on the NAS alone), then new layouts (the gateway), oldest first within each. PDF bytes live
only in this object's memory, under a 300 MB process cap counted as allocated and 30 files a person, and go as soon as
a file's lines are staged. Book writes are short IMMEDIATE transactions, never held across the sandbox or a gateway
call (the import commit's rule). Where the NAS can't confine the sandbox, every PDF is opened by the gateway's copy of it
(remote-reading P54, P63): files wait in this memory while it's away. Tests never start the thread; run_once() steps it."""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from steward import deps, gateway_name
from steward.db.models import Account, StatementLayout, StatementStage
from steward.services.statements import layouts, stage
from steward.services.statements import scan as scan_read
from steward.services.statements.client import AWAY, remote_state, statement_features
from steward.services.statements.copy import BUSY, HELD
from steward.services.statements.propose import Proposal, propose, read_all
from steward.services.statements.rules import Reading
from steward_pdf.sandbox import run_extract, run_render
from steward.services.statements.stage import SCAN_MARK, is_scanning

__all__ = ["SCAN_MARK", "is_scanning", "StatementReader", "Busy"]       # the mark lives in stage (no import cycle)
log = logging.getLogger(__name__)
CAP_BYTES = 300 * 1024 * 1024
PER_PERSON = 30
IDLE_S = 60.0
SWEEP_EVERY = timedelta(hours=1)
WORKING = ("queued", "waiting")
KEEP = ("queued", "reading", "waiting")                  # states whose bytes are still needed
KEEP_ERRORS = ("page_failed", "read_failed")              # errors whose bytes are kept for Try again
PLACES = ("local", "gateway")
SUFFIX = re.compile(r" · (?:••\d{4}|\d+)$")             # the account suffix store() gives a combined statement's lines


class Busy(Exception):
    pass


@dataclass
class Held:
    user_id: int
    data: bytearray


@dataclass(frozen=True)
class Job:
    order: int
    updated: datetime
    book: object
    stage_id: int
    kind: str                            # extract | layout | scan
    state: str = "queued"                # queued | waiting, as _jobs read it


def _scan_start() -> str:
    return json.dumps({"scan": True, "pages": []})


class StatementReader:
    def __init__(self, books, client, health: Callable[[], dict | None], peek: Callable[[], dict | None], *,
                 place: str = "local", extract=None, render=None, today: Callable[[], date] = deps.today,
                 now: Callable[[], datetime] = deps.now, cap: int = CAP_BYTES, per_person: int = PER_PERSON):
        self.books, self.client, self.health, self.peek = books, client, health, peek
        self._today, self._now = today, now
        self.cap, self.per_person = cap, per_person
        self._png = 0                                            # the page picture held right now (P26)
        self._inflight = 0                                       # a PDF's copy on its way to the gateway (P65)
        self._away = False                                       # the gateway didn't answer since the last wake (P66)
        self._lock = threading.Lock()
        self._held: dict[tuple[int, int], Held] = {}
        self._reserved: dict[int, tuple[int, int]] = {}          # rid -> (user_id, bytes)
        self._next = 0
        self._wake, self._stop = threading.Event(), threading.Event()
        self._thread: threading.Thread | None = None
        self.swept_at: datetime | None = None
        self.place = place
        if extract is not None:
            self._extract = extract
        if render is not None:
            self._render = render

    @property
    def place(self) -> str:
        return self._place

    @place.setter
    def place(self, value: str) -> None:
        """P54: local runs the sandbox here; gateway asks the gateway's copy of it, through the client."""
        if value not in PLACES:
            raise ValueError(value)
        self._place = value
        self._extract, self._render = ((run_extract, run_render) if value == "local"
                                       else (self._remote_extract, self._remote_render))

    def _remote_extract(self, data):
        return self._sending(data, lambda body: self.client.extract(body))

    def _remote_render(self, data, n: int):
        return self._sending(data, lambda body: self.client.render(body, n))

    def _sending(self, data, call):
        body = bytes(data)
        with self._lock:
            self._inflight += len(body)
        try:
            return call(body)
        finally:
            with self._lock:
                self._inflight -= len(body)

    # ------------------------------------------------------------------ memory (P7, Engineering choice 11)
    def held_bytes(self) -> int:
        with self._lock:
            return (sum(n for _, n in self._reserved.values()) + sum(sys.getsizeof(h.data) for h in self._held.values())
                    + self._png + self._inflight)

    def reserve(self, user_id: int, n: int) -> int:
        """Before an upload is read: Busy past the process cap or the person's 30 files."""
        with self._lock:
            used = (sum(b for _, b in self._reserved.values()) + sum(sys.getsizeof(h.data) for h in self._held.values())
                    + self._png + self._inflight)
            mine = sum(1 for u, _ in self._reserved.values() if u == user_id) + \
                sum(1 for h in self._held.values() if h.user_id == user_id)
            if mine >= self.per_person or used + n > self.cap:
                raise Busy()
            self._next += 1
            self._reserved[self._next] = (user_id, n)
            return self._next

    def release(self, rid: int) -> None:
        with self._lock:
            self._reserved.pop(rid, None)

    def hold(self, book_id: int, stage_id: int, user_id: int, data: bytearray, rid: int) -> None:
        with self._lock:
            self._reserved.pop(rid, None)
            self._held[(book_id, stage_id)] = Held(user_id, data)
        self.wake()

    def drop(self, book_id: int, stage_id: int) -> None:
        with self._lock:
            self._held.pop((book_id, stage_id), None)

    def has(self, book_id: int, stage_id: int) -> bool:
        with self._lock:
            return (book_id, stage_id) in self._held

    # ------------------------------------------------------------------ the thread
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="steward-statements", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)

    def wake(self) -> None:
        self._away = False                                       # P66: ask the gateway again
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                ran = self.run_once()
            except Exception as e:                       # noqa: BLE001 - the thread must outlive any one file
                log.warning("statement reader failed: %s", type(e).__name__)
                ran = False
            if not ran:
                self._wake.wait(IDLE_S)
                self._wake.clear()
                self._away = False                       # P66: after a wake or a minute idle, ask the gateway again

    # ------------------------------------------------------------------ books
    def _books(self):
        return [b for b in self.books.books() if b.id not in self.books.unavailable]

    @contextmanager
    def _write(self, book) -> Iterator[Session]:
        with Session(self.books.engine_for(book).execution_options(immediate=True)) as db:
            yield db

    @contextmanager
    def _read(self, book) -> Iterator[Session]:
        with Session(self.books.engine_for(book).execution_options(immediate=False)) as db:
            yield db

    def recover(self) -> None:
        """Startup (spec, The reader thread): a text file that was reading goes back to the queue; a file never read
        lost its bytes with the restart (Engineering choice 6); then the sweep."""
        now = self._now()
        for book in self._books():
            with self._write(book) as db:
                for s in db.scalars(select(StatementStage).where(or_(StatementStage.state.in_(KEEP),
                                                                     StatementStage.error.in_(KEEP_ERRORS)))):
                    if is_scanning(s):                   # P32: its bytes went with the restart; the pages read are kept
                        s.state, s.error = "error", "restarted"
                        stage.touch(s, now)
                    elif s.lines is None:
                        s.state, s.error = "error", "gone"
                        stage.touch(s, now)
                    elif s.state == "reading":
                        s.state = "queued"
                stage.sweep(db, now)
                db.commit()
        self.swept_at = now

    def sweep_all(self) -> None:
        """P5: hourly, on the steward-watch job (Engineering choice 25)."""
        now = self._now()
        if self.swept_at is not None and now - self.swept_at < SWEEP_EVERY:
            return
        for book in self._books():
            with self._write(book) as db:
                stage.sweep(db, now)
                db.commit()
        self.swept_at = now

    def remote_state(self) -> str:
        """For the listing: from the last health the advisor monitor has, never a network call. In gateway mode it's
        about opening PDFs: a gateway that lists statement features but not extract is old (P63)."""
        health = self.peek()
        if self.place == "local":
            return remote_state(self.client, health)
        state = remote_state(self.client, health, "extract")
        feats = statement_features(health)
        return "old" if state == "waiting" and feats is not None and "extract" not in feats else state

    def needs_model(self, scanning: bool) -> bool:
        """Install gate INS-12: a read file waiting for its layout (or a scan for its pages) waits on a local model the
        paired gateway says it hasn't got, not on the gateway itself. From the last health, never a network call."""
        feats = statement_features(self.peek()) if getattr(self.client, "paired", False) else None
        return feats is not None and ("scan" if scanning else "layout") not in feats

    def busy_line(self) -> str:
        """P65: past a cap while files wait for the gateway, say so; otherwise the import round's busy line."""
        return gateway_name.fill(HELD) if self.place == "gateway" and self.remote_state() != "answering" else BUSY

    # ------------------------------------------------------------------ jobs
    def _forget_orphans(self) -> None:
        with self._lock:
            keys = list(self._held)
        by_book: dict[int, list[int]] = {}
        for book_id, sid in keys:
            by_book.setdefault(book_id, []).append(sid)
        for book in self._books():
            ids = by_book.get(book.id)
            if not ids:
                continue
            with self._read(book) as db:
                keep = set(db.scalars(select(StatementStage.id).where(
                    StatementStage.id.in_(ids), or_(StatementStage.state.in_(KEEP),
                                                    (StatementStage.state == "error") & StatementStage.error.in_(KEEP_ERRORS)))))
            for sid in ids:
                if sid not in keep:
                    self.drop(book.id, sid)

    def _jobs(self) -> list[Job]:
        jobs = []
        for book in self._books():
            with self._read(book) as db:
                found = db.execute(select(StatementStage.id, StatementStage.lines.is_not(None), StatementStage.updated_at,
                                          StatementStage.part, StatementStage.content_sha256,
                                          StatementStage.proposal.startswith(SCAN_MARK), StatementStage.state)
                                   .where(StatementStage.state.in_(WORKING), StatementStage.removed_at.is_(None))).all()
            leads = {sha for _, _, _, part, sha, _, _ in found if part == 0}
            for sid, has_lines, updated, part, sha, scanning, state in found:
                if part and sha in leads:
                    continue                             # P44: the first account's job writes every account's line
                if not has_lines:
                    if self.has(book.id, sid):
                        jobs.append(Job(0, updated, book, sid, "extract", state))
                elif scanning:
                    jobs.append(Job(2, updated, book, sid, "scan"))
                else:
                    jobs.append(Job(1, updated, book, sid, "layout"))
        return sorted(jobs, key=lambda j: (j.order, j.updated, j.stage_id))

    def run_once(self) -> bool:
        """One job, the first in order that can run now. False when nothing could."""
        self._forget_orphans()
        for job in self._jobs():
            if job.kind == "extract":
                if self._extract_job(job.book, job.stage_id, job.state):
                    return True
            elif job.kind == "scan":
                if self._scan_job(job.book, job.stage_id):
                    return True
            elif self._layout_job(job.book, job.stage_id):
                return True
        return False

    def _answering(self) -> bool:
        return not self._away and remote_state(self.client, self.health()) == "answering"

    def _opens(self, feature: str) -> bool:
        """P54, P63: here, always; on the gateway, only while it answers with the feature and hasn't failed to answer
        since the last wake."""
        return self.place == "local" or (not self._away and
                                         remote_state(self.client, self.health(), feature) == "answering")

    def _set_waiting(self, book, sid: int, was: str = "queued") -> None:
        with self._write(book) as db:
            s = db.get(StatementStage, sid)
            if s is not None and s.state == was and s.removed_at is None:
                s.state = "waiting"
                db.commit()

    def _not_extracted(self, book, sid: int, away: bool) -> None:
        """P66: the gateway away (no answer, a timeout, or it can't open PDFs now): the file waits, untried, until the
        next wake. Any other failed answer is tried once more at the back of the queue, then says Try again. The bytes
        stay either way, until expiry or a restart (P64)."""
        if away:
            self._away = True
            self._set_waiting(book, sid, was="reading")
            return
        with self._write(book) as db:
            s = db.get(StatementStage, sid)
            if s is None or s.state != "reading":
                return
            s.tries += 1
            s.state, s.error = ("queued", None) if s.tries < 2 else ("error", "read_failed")
            stage.touch(s, self._now())
            db.commit()

    def _extract_job(self, book, sid: int, state: str = "queued") -> bool:
        with self._lock:
            held = self._held.get((book.id, sid))
        if held is None:
            return False
        if not self._opens("extract"):                   # P63: before any transaction
            if state != "waiting":                         # already waiting: no write lock on every pass
                self._set_waiting(book, sid)
            return False
        with self._write(book) as db:
            s = db.get(StatementStage, sid)
            if s is None or s.state not in WORKING or s.lines is not None:
                self.drop(book.id, sid)
                return True
            s.state = "reading"
            db.commit()
        out = self._extract(held.data)                  # the sandbox, here or on the gateway: no transaction open
        if out is None or out == AWAY:
            self._not_extracted(book, sid, away=out == AWAY)
            return out is None
        answering = self._answering() if out.pages else False
        keep = False
        with self._write(book) as db:
            s = db.get(StatementStage, sid)
            if s is None or s.state != "reading":
                self.drop(book.id, sid)
                return True
            now = self._now()
            stage.touch(s, now)
            s.tries = 0                                    # a layout's or a page's tries start afresh (P33)
            if out.error:
                s.state, s.error = "error", out.error
                db.commit()
                self.drop(book.id, sid)
                return True
            pages = out.pages
            scans = sum(1 for p in pages if p["scan"])
            s.pages, s.kind = len(pages), "scan" if scans == len(pages) else "mixed" if scans else "text"
            s.lines = json.dumps(pages)
            if s.kind != "text":                           # P10, Engineering choice 2: every page to the vision model
                s.proposal, s.state = _scan_start(), "queued"
                keep = True
            elif not any(p["lines"] for p in pages):
                s.state, s.error, s.lines = "error", "not_statement", None
            elif self._learned(db, s, pages, answering):
                pass                                       # P22: a learned layout goes to row review, never to a scan
            else:
                s.state = "queued"                         # a new layout: keep the bytes for P17 (choice 1)
                keep = True
            db.commit()
        if not keep:
            self.drop(book.id, sid)
        return True

    def _learned(self, db: Session, s: StatementStage, pages: list[dict], answering: bool) -> bool:
        """P22, P24: a remembered layout that matches reads on the NAS alone; when it doesn't add up it goes back to the
        model once (as the first proposal), or with the gateway away straight to row review."""
        cands = db.scalars(select(StatementLayout).where(StatementLayout.forgotten_at.is_(None))).all()
        hit = layouts.best(cands, pages)
        if hit is None:
            return False
        rules = json.loads(hit.rules)
        readings, gap = read_all(rules, pages, self._today())
        if gap == 0:
            self.store(db, s, rules, readings, "ready", layout_row=hit)
            return True
        self.store(db, s, rules, readings, "queued" if answering else "off", layout_row=hit)
        return True

    def _waits_for_check(self, db: Session, s: StatementStage, pages: list[dict]) -> bool:
        """Spec, Remembered layouts: a file of a new layout that's waiting for its check waits behind it."""
        for other in db.scalars(select(StatementStage).where(StatementStage.state.in_(("layout", "holdings")),
                                                             StatementStage.id != s.id,
                                                             StatementStage.removed_at.is_(None))):
            rules = json.loads(other.proposal) if other.proposal else None
            a = layouts.anchors(rules, json.loads(other.lines)) if rules and other.lines else None
            if a is not None and layouts.matches(a, rules, pages):
                return True
        return False

    def _layout_job(self, book, sid: int) -> bool:
        answering = self._answering()                    # may ask the gateway: before any transaction
        with self._write(book) as db:
            s = db.get(StatementStage, sid)
            if s is None or s.state not in WORKING or s.removed_at is not None or s.lines is None:
                return False
            if s.part:                                   # its first account's line is gone or done: review what it read
                s.state = "off"
                stage.touch(s, self._now())
                db.commit()
                return True
            pages = json.loads(s.lines)
            drifted = s.layout_id is not None and s.proposal is not None
            if not drifted and self._learned(db, s, pages, answering):
                db.commit()
                return True
            if drifted and not answering:
                s.state = "off"                          # P22: with the gateway away, straight to row review
                db.commit()
                return True
            if self._waits_for_check(db, s, pages):
                return False
            if not answering:
                if s.state != "waiting":
                    s.state = "waiting"
                    db.commit()
                return False
            first = json.loads(s.proposal) if drifted else None
            s.state = "reading"
            db.commit()
        got = propose(self.client.layout, pages, self._today(), first=first)     # the gateway: no transaction open
        model = getattr(self.client, "last_model", None) or "unknown"
        with self._write(book) as db:
            s = db.get(StatementStage, sid)
            settled = s is None or s.state != "reading"
            if not settled:
                self._outcome(db, s, pages, got, model, book.id)
                db.commit()
                settled = s.state != "queued"
        if settled:
            self.drop(book.id, sid)                      # Engineering choice 1: the bytes go once the layout is settled
        return True

    def _fallback(self, s: StatementStage, book_id: int) -> None:
        """P17: a layout the model can't give is read as a scan, freshly, never remembered; without the bytes (a
        restart came first) it takes PR 1's "gone" line."""
        if self.has(book_id, s.id):
            s.proposal, s.state, s.tries, s.layout_id = _scan_start(), "queued", 0, None
        else:
            s.state, s.error = "error", "gone"

    def _outcome(self, db: Session, s: StatementStage, pages: list[dict], got: Proposal, model: str,
                 book_id: int) -> None:
        now = self._now()
        stage.touch(s, now)
        drifted = s.layout_id is not None            # P22: a usable stored reading goes to row review, never to an error
        if got.layout is None:
            s.tries += 1
            if s.tries < 2:
                s.state = "queued"                       # P33: once more, at the back of the queue (touch moved it)
            elif drifted:
                s.state, s.error = "off", None
            else:
                self._fallback(s, book_id)
            return
        if got.retry_failed and not drifted:             # the retry gave nothing usable: P17, as for no layout at all
            self._fallback(s, book_id)
            return
        if not got.readings or got.readings[0].error:
            err = got.readings[0].error if got.readings else None
            s.state, s.error = ("off", None) if drifted else ("error", "no_period" if err == "no_period" else
                                                              "too_many_rows" if err == "too_many_rows" else
                                                              "too_many_holdings" if err == "too_many_holdings" else
                                                              "not_statement")
            return
        kept = s.layout_id if drifted and s.proposal is not None and got.layout == json.loads(s.proposal) else None
        s.layout_id = None
        self.store(db, s, got.layout, got.readings, "layout" if got.gap == 0 else "off", model=model)
        if kept is not None:
            s.layout_id = kept                           # the model had nothing better: still the remembered layout

    # ------------------------------------------------------------------ scans (P25-P26, P32-P33)
    def _want(self, db: Session, s: StatementStage) -> tuple[str, bool]:
        """P25: positions when the account picked is an investment account and the gateway reads them. The second says it
        is an investment account read for rows only because the gateway can't read holdings yet (the review's note)."""
        from steward.db.models import INVESTMENT_TYPES
        account = db.get(Account, s.account_id) if s.account_id is not None else None
        if account is None or account.type not in INVESTMENT_TYPES:
            return "rows", False
        feats = statement_features(self.health()) or frozenset()
        return ("holdings", False) if "holdings" in feats else ("rows", True)

    def _scan_job(self, book, sid: int) -> bool:
        with self._lock:
            held = self._held.get((book.id, sid))
        answering = remote_state(self.client, self.health(), "scan") == "answering" and self._opens("render")   # before any transaction
        with self._write(book) as db:
            s = db.get(StatementStage, sid)
            if s is None or s.state not in WORKING or s.removed_at is not None:
                return False
            if held is None:
                s.state, s.error = "error", "restarted"            # P32
                stage.touch(s, self._now())
                db.commit()
                return True
            if not answering:
                if s.state != "waiting":
                    s.state = "waiting"
                    db.commit()
                return False
            n, of, (want, old) = s.pages_done + 1, s.pages or 1, self._want(db, s)
            s.state = "reading"
            db.commit()
        pic = self._render(held.data, n)                           # the sandbox: no transaction open
        if pic is None or pic == AWAY:                             # P66: the gateway didn't render it
            if pic == AWAY:
                self._away = True
                self._set_waiting(book, sid, was="reading")
                return False
            self._take_page(book, sid, n, of, None, "unknown")     # P33's page rule: once more, then page_failed
            return True
        if pic.error:
            with self._write(book) as db:
                s = db.get(StatementStage, sid)
                if s is not None and s.state == "reading":
                    s.state, s.error = "error", pic.error
                    stage.touch(s, self._now())
                    db.commit()
            self.drop(book.id, sid)
            return True
        with self._lock:
            self._png = len(pic.png)
        try:
            answer = self.client.page(pic.png, n, of, pic.width, pic.height, want)     # the gateway: no transaction open
        finally:
            with self._lock:
                self._png = 0
            pic = None                                             # the picture goes with the answer (P26)
        model = getattr(self.client, "last_model", None) or "unknown"
        try:
            done = self._take_page(book, sid, n, of, answer, model, old)
        except Exception as e:                                     # noqa: BLE001 - never left reading until a restart
            log.warning("statement scan failed on page %d: %s", n, type(e).__name__)
            self._unreadable(book, sid)
            done = True
        if done:
            self.drop(book.id, sid)
        return True

    def _take_page(self, book, sid: int, n: int, of: int, answer: dict | None, model: str, old: bool = False) -> bool:
        """One page's answer onto the stage; True when the scan is settled and its bytes can go. old: the page was read
        for rows because the gateway can't read holdings yet, which the holdings review says."""
        with self._write(book) as db:
            s = db.get(StatementStage, sid)
            if s is None or s.state != "reading" or s.pages_done != n - 1:
                return False                                       # an answer for any other page is dropped
            stage.touch(s, self._now())
            if answer is None:                                     # P33: once more at the back of the queue
                s.tries += 1
                s.state, s.error = ("queued", None) if s.tries < 2 else ("error", "page_failed")
                db.commit()
                return False
            read = json.loads(s.proposal) if is_scanning(s) else {"scan": True, "pages": []}
            read["pages"].append({"n": n, **scan_read.mask_answer(answer)})
            if old:
                read["holdings_old"] = True
            s.proposal, s.pages_done, s.tries = json.dumps(read), n, 0
            if n == 1 and s.account_id is None:
                s.account_id, s.suggested_by = stage.suggest(db, None, answer.get("institution"),
                                                             answer.get("account_last4"), None)
            done = n >= of
            if done:
                self._finish_scan(db, s, read["pages"], model)
            else:
                s.state = "queued"
            db.commit()
        return done

    def _unreadable(self, book, sid: int) -> None:
        """A scan that broke while its answer was stored or assembled: the line says so (the file can be added again)."""
        with self._write(book) as db:
            s = db.get(StatementStage, sid)
            if s is not None and s.state == "reading":
                s.state, s.error = "error", "unreadable"
                stage.touch(s, self._now())
                db.commit()

    def _finish_scan(self, db: Session, s: StatementStage, answers: list[dict], model: str) -> None:
        """Assembles the statement (Engineering choice 6: the account says bank or owed) and checks it. Scans never wait
        for Looks right: nothing about them is remembered; ready when they add up, row review when not."""
        account = db.get(Account, s.account_id) if s.account_id is not None else None
        reading, facts = scan_read.assemble(answers, scan_read.kind_for(account.type if account else None), self._today())
        facts["model"] = model
        if reading.error:
            s.state, s.error = "error", reading.error
            return
        stage.put_assembled(s, reading, facts)
        if s.account_id is None:
            s.account_id, s.suggested_by = stage.suggest(db, facts["kind"], facts["institution"], facts["last4"], None)
        if s.account_id is None:
            s.gap_cents, s.state = None, "ready"        # no account, no sense to check by: not off, the line asks for one
        else:
            s.gap_cents = stage.regap(s)
            s.state = "ready" if s.gap_cents == 0 else "off"

    # ------------------------------------------------------------------ storing a reading
    def _facts(self, layout: dict, r: Reading, label: str | None, model: str | None) -> dict:
        return {"kind": layout["kind"], "institution": layout["institution"], "label": label, "model": model,
                "last4": r.last4,
                "period": [r.period[0].isoformat(), r.period[1].isoformat()] if r.period else None,
                "opening_cents": r.opening, "closing_cents": r.closing,
                "opening_label": layout["opening"]["label"], "closing_label": layout["closing"]["label"],
                "sections": [{"title": x["title"], "way": x["way"], "total_cents": r.totals.get(x["title"])}
                             for x in layout["table"]["sections"] if x["way"] != "skip"],
                "unreadable": [{"page": p, "text": t} for p, t in r.unreadable]}

    def store(self, db: Session, s: StatementStage, layout: dict, readings: list[Reading], state: str,
              layout_row: StatementLayout | None = None, model: str | None = None) -> None:
        """Writes a reading onto the stage (and, for a combined statement, one more stage per further account, P44):
        rows, facts, the gap, the state, and the account suggestion unless a person already chose one."""
        if layout["kind"] in ("investment", "retirement", "loan"):
            return self.store_holdings(db, s, layout, readings[0], state, layout_row, model)
        label = layout_row.label if layout_row is not None else None
        model = model or (layout_row.model if layout_row is not None else None)
        pairs = [(s, readings[0])]
        if len(readings) > 1:
            # A second reading of the same file (a remembered layout that didn't add up, then the model) rewrites the
            # lines it made the first time: one per account, never a copy, and the names keep a single suffix.
            others: dict[int, StatementStage] = {}
            for x in db.scalars(select(StatementStage).where(StatementStage.content_sha256 == s.content_sha256,
                                                              StatementStage.part > 0, StatementStage.id > s.id)
                                .order_by(StatementStage.id)):
                if x.part not in others or others[x.part].removed_at is not None:
                    others[x.part] = x                   # the live one when there is one
            base = SUFFIX.sub("", s.filename) if others else s.filename
            s.filename = f"{base} · ••{readings[0].last4}"[:200] if readings[0].last4 else base
            for k, r in enumerate(readings[1:], 1):
                name = (f"{base} · ••{r.last4}" if r.last4 else f"{base} · {k + 1}")[:200]
                extra = others.get(k)
                if extra is not None and extra.removed_at is not None:
                    continue                             # removed while it was read again: Undo brings back that one
                if extra is None:
                    extra = StatementStage(added_by=s.added_by, added_at=s.added_at, filename=name, bytes=s.bytes,
                                           pages=s.pages, content_sha256=s.content_sha256, kind=s.kind, state=state,
                                           tries=0, anyway=False, part=k, lines=s.lines, pages_done=0)
                    db.add(extra)
                extra.filename = name
                stage.touch(extra, self._now())
                pairs.append((extra, r))
        for p, r in pairs:
            p.proposal = json.dumps(layout)
            p.layout_id = layout_row.id if layout_row is not None else None
            p.statement = json.dumps(self._facts(layout, r, label, model))
            p.rows = json.dumps([{"date": x.date.isoformat(), "description": x.description, "amount_cents": x.amount_cents,
                                  "page": x.page, "section": x.section, "state": "read"} for x in r.rows])
            p.gap_cents = stage.regap(p)
            p.state = "ready" if state == "ready" and p.gap_cents == 0 else ("off" if state == "ready" else state)
            if p.account_id is None:
                p.account_id, p.suggested_by = stage.suggest(db, layout["kind"], layout["institution"], r.last4,
                                                             layout_row.account_id if layout_row is not None else None)
        db.flush()

    def store_holdings(self, db: Session, s: StatementStage, layout: dict, r, state: str,
                       layout_row: StatementLayout | None = None, model: str | None = None) -> None:
        """An investment statement's holdings (or a loan's principal) onto the stage. A learned layout that adds up is
        ready; a new one waits for Looks right (holdings, or a loan's layout check); a learned one that doesn't add up
        goes back to the model once (queued, P22); otherwise holdings review (Engineering choices 1 and 2)."""
        loan = layout["kind"] == "loan"
        s.proposal = json.dumps(layout)
        s.layout_id = layout_row.id if layout_row is not None else None
        s.statement = json.dumps({
            "kind": layout["kind"], "institution": layout["institution"],
            "label": layout_row.label if layout_row is not None else None,
            "model": model or (layout_row.model if layout_row is not None else None), "last4": r.last4,
            "period": [r.period[0].isoformat(), r.period[1].isoformat()] if r.period else None,
            "opening_cents": None, "closing_cents": r.ending, "total_cents": r.total,
            "opening_label": layout["opening"]["label"], "closing_label": layout["closing"]["label"],
            "sections": [], "unreadable": []})
        s.rows = json.dumps([])
        s.holdings = None if loan else json.dumps([{"symbol": h.symbol, "name": h.name, "shares_milli": h.shares_milli,
                                                    "value_cents": h.value_cents, "cash": h.cash, "page": h.page,
                                                    "state": "read"} for h in r.holdings])
        s.gap_cents = stage.regap(s)
        if s.gap_cents == 0:
            s.state = "ready" if state == "ready" else "layout" if loan else "holdings"
        elif state == "queued":
            s.state = "queued"
        elif s.gap_cents is None and loan:                 # no principal to show; a period not read says so
            s.state, s.error = "error", "no_period" if r.error == "no_period" else "not_statement"
        else:
            s.state = "off"
        if s.account_id is None:
            s.account_id, s.suggested_by = stage.suggest(db, layout["kind"], layout["institution"], r.last4,
                                                         layout_row.account_id if layout_row is not None else None)
        db.flush()
