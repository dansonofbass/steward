"""A throwaway Steward with the demo books, for the evals that use the real API (spec 11.4, 12; ruling 14). The demo
household and the fictional parent "Margaret Ellis" are built in a temporary folder, Steward's own turn code asks
through a gateway in this process (the real detectors, the real key), and everything is deleted afterwards. The demo
data ends on 2026-10-12, so the evals ask as of 2026-10-19. Spending goes into the real ledger, so the monthly cap
holds, as channel "eval" with no book and no person: it is in the month's total but in no book's usage, and the
nightly cross-check skips it. Nothing here touches the NAS or any real book."""
from __future__ import annotations

import dataclasses
import secrets
import shutil
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from steward_gateway.app import create_gateway_app
from steward_gateway.config import GatewayConfig
from steward_gateway.ledger import Ledger
from steward_gateway.secrets import write_private
from steward_gateway.serving import serve_in_thread

EVAL_TODAY = date(2026, 10, 19)
EVAL_NOW = datetime(2026, 10, 19, 17, tzinfo=timezone.utc)


class EvalLedger:
    """The real ledger with every reservation and sent row recorded as channel eval, with no book or person."""

    def __init__(self, real: Ledger):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def reserve(self, *, now, book_id, user_id, turn_id, channel, model, estimate_nd):
        return self._real.reserve(now=now, book_id=None, user_id=None, turn_id=turn_id, channel="eval", model=model,
                                  estimate_nd=estimate_nd)

    def record_sent(self, now, items, book_id, channel):
        self._real.record_sent(now, items, None, "eval")

    def settle_stale(self) -> int:
        return 0        # open reservations belong to the running gateway service, which settles its own


@dataclass
class Outcome:
    answer: str
    stop: str
    first_token_ms: float | None
    total_ms: float
    tool_rounds: int
    cost_cents: int


class Rig:
    def __init__(self, books, gateway, user_id: int, parent_slug: str):
        self.books, self.gateway, self.user_id, self.parent_slug = books, gateway, user_id, parent_slug

    def slug_for(self, book: str) -> str:
        return "ours" if book == "household" else self.parent_slug

    def _info(self, slug: str):
        return self.books.book(slug)

    def call(self, slug: str, name: str, input: dict) -> dict:
        """A tool through the NAS's own executor: the figures a correct answer must contain (spec 11.4)."""
        from steward.advisor.tools import run_call
        info = self._info(slug)
        r = run_call({"id": "toolu_eval", "name": name, "input": input},
                     bind=self.books.engine_for(info).execution_options(immediate=True), book=info,
                     user_id=self.user_id, people=self.books.people(info.id), today=EVAL_TODAY,
                     plan_cache=self.books.plan_cache(info.id), directory=self.books.directory)
        return r["content"] if r["error"] is None else {"error": r["error"]}

    def ask(self, slug: str, question: str) -> Outcome:
        """One question in a new conversation, exactly as Ask sends it, timed from the start of the turn."""
        from steward.advisor.turn import AskEnv, run_turn, start_turn
        info = self._info(slug)
        env = AskEnv(bind=self.books.engine_for(info).execution_options(immediate=True),
                     directory=self.books.directory, book=info, user_id=self.user_id,
                     people=lambda: self.books.people(info.id), plan_cache=self.books.plan_cache(info.id),
                     gateway=self.gateway, now=lambda: datetime.now(timezone.utc), today=lambda: EVAL_TODAY)
        t0 = time.perf_counter()
        prep = start_turn(env, question)
        first, labels, final = None, 0, None
        for event in run_turn(env, prep):
            if event["type"] == "labels" and first is None:
                labels += 1                       # once at the start, then once after each round of tools
            elif event["type"] == "text" and first is None:
                first = (time.perf_counter() - t0) * 1000
            elif event["type"] == "done":
                final = event
        total = (time.perf_counter() - t0) * 1000
        final = final or {"answer": "", "stop": "dropped", "cost_cents": 0}
        return Outcome(final.get("answer") or "", final.get("stop") or "dropped", first, total, max(0, labels - 1),
                       int(final.get("cost_cents") or 0))


@contextmanager
def demo_rig(base: GatewayConfig, *, client, detectors, ledger: Ledger) -> Iterator[Rig]:
    from sqlalchemy.orm import Session

    from steward.advisor.gateway import GatewayClient
    from steward.advisor.state import set_chat_on
    from steward.auth.users import find_user
    from steward.books.registry import open_books
    from steward.books.service import add_membership, create_book
    from steward.db.keys import ensure_key
    from steward.demo import DEMO_LOGINS, seed, seed_people
    from steward.demo_care import seed_care
    from steward.demo_parent import seed_parent
    from steward.settings import Settings

    tmp = Path(tempfile.mkdtemp(prefix="steward-eval-"))
    books = None
    try:
        cfg = dataclasses.replace(base, config_dir=tmp / "gw-config", state_dir=tmp / "gw-state", host="127.0.0.1",
                                  nas_url=None)
        token = secrets.token_hex(32)
        write_private(cfg.token_path, token)
        (tmp / "nas").mkdir()
        settings = Settings(_env_file=None, data_dir=tmp / "nas", base_url="https://eval.invalid", env="test")
        ensure_key(settings.key_path)
        books = open_books(settings)
        ours = books.book("ours")
        with Session(books.engine_for(ours)) as db:
            seed(db, years=2, seed=7)
            db.commit()
        with Session(books.directory) as ddb:
            seed_people(ddb, ours.id)
            mom = create_book(books, ddb, name="Margaret Ellis", kind="parent",
                              owner_labels=["Margaret", "Robert (husband)", "Joint"])
            jr_id = find_user(ddb, DEMO_LOGINS[0][0]).id      # the demo's Person 1 (owner key jr)
            add_membership(ddb, jr_id, mom.id, "manager", by=None)
            ddb.commit()
        with Session(books.engine_for(mom)) as db:
            seed_parent(db, EVAL_TODAY, by=jr_id)
            seed_care(db, EVAL_TODAY)
            db.commit()
        for book in (ours, mom):
            with Session(books.engine_for(book)) as db:
                set_chat_on(db, True, jr_id, EVAL_NOW)
                db.commit()
        app = create_gateway_app(cfg, client=client, detectors=detectors, ledger=EvalLedger(ledger))
        with serve_in_thread(app) as url:
            gateway = GatewayClient(url, token)
            try:
                yield Rig(books, gateway, jr_id, mom.slug)
            finally:
                gateway.close()
    finally:
        if books is not None:
            books.dispose()
        shutil.rmtree(tmp, ignore_errors=True)
