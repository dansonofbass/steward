"""The catch-up (phase 12, Catch-up): when the gateway answers, untouched rows the model hasn't been asked about, from
all history and newest first, are asked in batches, per book; a row touched meanwhile is left alone; every asked row
remembers it (model_asked_at) so nothing is asked twice; a wave's progress is counted for Review and Home."""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import CategorySource, EventLog, MerchantRule, Transaction, WatchState
from steward.services import catchup as CU
from steward.services.categorizer_client import Guess
from tests.factories import make_account, make_txn, make_user

TODAY = date(2026, 10, 21)
NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)


class Model:
    def __init__(self, answer=lambda d: ("dining", "Bean Cafe") if "CAFE" in d else None, fail_after=None):
        self.answer, self.calls, self.examples, self.missed, self.fail_after = answer, [], [], True, fail_after
        self.features = frozenset()

    def categorize_batch(self, rows, examples=()):
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            self.missed = True
            return None
        self.calls.append(list(rows))
        self.examples.append(list(examples))
        return [self.answer(d) for d, _ in rows]


def seed(db):
    a = make_account(db)
    old = make_txn(db, a, TODAY - timedelta(days=400), -500, "OLD CAFE")          # all history: asked too, last
    fresh = make_txn(db, a, TODAY - timedelta(days=3), -500, "BEAN CAFE")
    zelle = make_txn(db, a, TODAY - timedelta(days=3), -4000, "ZELLE TO SAM", merchant="Zelle")
    reviewed = make_txn(db, a, TODAY - timedelta(days=3), -500, "HARBOR CAFE")
    reviewed.reviewed_at = datetime(2026, 10, 20, tzinfo=timezone.utc)
    snoozed = make_txn(db, a, TODAY - timedelta(days=3), -500, "TACO CAFE")
    snoozed.snoozed_until = datetime(2026, 11, 1, tzinfo=timezone.utc)
    ruled = make_txn(db, a, TODAY - timedelta(days=3), -500, "SUNNY CAFE", category="groceries",
                     category_source=CategorySource.rule)
    xfer = make_txn(db, a, TODAY - timedelta(days=3), -500, "CAFE XFER", is_transfer=True)
    asked = make_txn(db, a, TODAY - timedelta(days=2), -500, "ASKED CAFE")
    asked.model_asked_at = datetime(2026, 10, 20, tzinfo=timezone.utc)          # already answered about: never again
    mystery = make_txn(db, a, TODAY - timedelta(days=1), -500, "POS PURCHASE")
    db.commit()
    return {"old": old.id, "fresh": fresh.id, "zelle": zelle.id, "reviewed": reviewed.id, "snoozed": snoozed.id,
            "ruled": ruled.id, "xfer": xfer.id, "asked": asked.id, "mystery": mystery.id}


def asked_of(model):
    return [d for call in model.calls for d, _ in call]


def test_untouched_unasked_rows_are_asked_newest_first_across_all_history(db, engine):
    ids = seed(db)
    model = Model()
    result = CU.catch_up_book(engine, model, now=NOW)
    assert asked_of(model) == ["POS PURCHASE", "BEAN CAFE", "OLD CAFE"]
    assert (result.asked, result.categorized, result.guessed, result.stopped, result.more) == (3, 2, 0, False, False)
    db.rollback()
    fresh, old, mystery = (db.get(Transaction, ids[k]) for k in ("fresh", "old", "mystery"))
    assert (fresh.category, fresh.merchant, fresh.category_source, fresh.model_asked_at) == ("dining", "Bean Cafe", CategorySource.model, NOW)
    assert old.category == "dining" and old.model_asked_at == NOW
    assert mystery.category_source == CategorySource.none and mystery.model_asked_at == NOW
    for k in ("zelle", "reviewed", "snoozed", "ruled", "xfer"):
        assert db.get(Transaction, ids[k]).model_asked_at is None, k
    assert CU.catch_up_book(engine, model, now=NOW).asked == 0           # nothing left: nothing is asked twice


def test_an_unsure_answer_keeps_its_guess_and_a_person_s_sort_clears_it(db, engine):
    a = make_account(db)
    t = make_txn(db, a, TODAY - timedelta(days=1), -8000, "UNION SERVICE CENTER")
    db.commit()
    result = CU.catch_up_book(engine, Model(answer=lambda d: Guess("home", 45)), now=NOW)
    assert (result.asked, result.categorized, result.guessed) == (1, 0, 1)
    db.rollback()
    assert (t.guess_category, t.guess_pct, t.category, t.model_asked_at) == ("home", 45, "uncategorized", NOW)


def test_the_households_examples_go_with_each_batch(db, engine):
    a = make_account(db)
    make_txn(db, a, TODAY - timedelta(days=1), -500, "POS PURCHASE")
    db.add(MerchantRule(pattern="HARBOR GRILL", merchant="Harbor Grill", category="dining", is_business=None,
                        source=CategorySource.correction))
    db.commit()
    model = Model()
    model.features = frozenset({"examples"})
    CU.catch_up_book(engine, model, now=NOW)
    assert model.examples == [[("HARBOR GRILL", "dining")]]


def test_no_examples_are_read_when_the_gateway_does_not_list_them(db, engine):
    a = make_account(db)
    make_txn(db, a, TODAY - timedelta(days=1), -500, "POS PURCHASE")
    db.add(MerchantRule(pattern="HARBOR GRILL", merchant="Harbor Grill", category="dining", is_business=None,
                        source=CategorySource.correction))
    db.commit()
    model = Model()                                     # features empty: HttpModelClient's until health says
    CU.catch_up_book(engine, model, now=NOW)
    assert model.examples == [[]]


def test_a_row_touched_while_the_model_was_thinking_is_left_alone(db, engine):
    ids = seed(db)

    def answer_and_touch(d):
        if d == "BEAN CAFE":
            with Session(engine) as other:              # the person reviews it in the meantime
                other.get(Transaction, ids["fresh"]).reviewed_at = datetime(2026, 10, 21, tzinfo=timezone.utc)
                other.commit()
            return ("dining", None)
        return None
    result = CU.catch_up_book(engine, Model(answer=answer_and_touch), now=NOW)
    db.rollback()
    assert result.categorized == 0
    fresh = db.get(Transaction, ids["fresh"])
    assert fresh.category_source == CategorySource.none and fresh.model_asked_at is None


def test_a_failed_batch_stops_the_run_sets_the_miss_and_is_asked_again_next_run(db, engine):
    a = make_account(db)
    for i in range(60):
        make_txn(db, a, TODAY - timedelta(days=1), -500, f"BEAN CAFE {i:03d}")
    model = Model(fail_after=1)
    model.missed = False
    result = CU.catch_up_book(engine, model, now=NOW)
    assert (result.asked, result.categorized, result.stopped) == (50, 50, True) and model.missed
    model.fail_after = None
    again = CU.catch_up_book(engine, model, now=NOW)
    assert (again.asked, again.categorized, again.stopped) == (10, 10, False)
    assert len(set(asked_of(model))) == 60


def test_the_per_run_limit_stops_and_the_next_run_goes_on_where_it_left_off(db, engine):
    a = make_account(db)
    for i in range(30):
        make_txn(db, a, TODAY - timedelta(days=1), -500, f"MYSTERY {chr(65 + i % 26)}{i}")
    model = Model()
    first = CU.catch_up_book(engine, model, now=NOW, per_run=20)
    assert first.asked == 20 and first.more
    second = CU.catch_up_book(engine, model, now=NOW, per_run=20)
    assert second.asked == 10 and not second.more
    assert len(asked_of(model)) == len(set(asked_of(model))) == 30


def test_a_row_only_a_household_rule_matches_is_asked_and_not_given_the_rule(db, engine):
    """Ruling F5 revised: spreading a person's rule onto old rows stays theirs to offer (decision 1)."""
    a = make_account(db)
    old = make_txn(db, a, TODAY - timedelta(days=1), -500, "HARBOR GRILL 22")  # came in before the rule existed
    make_txn(db, a, TODAY - timedelta(days=2), -500, "POS PURCHASE")
    db.add(MerchantRule(pattern="HARBOR GRILL", merchant="Harbor Grill", category="dining", is_business=None,
                        source=CategorySource.correction))
    db.commit()
    model = Model()
    result = CU.catch_up_book(engine, model, now=NOW)
    assert asked_of(model) == ["HARBOR GRILL 22", "POS PURCHASE"] and (result.asked, result.ruled) == (2, 0)
    db.rollback()
    assert (old.category, old.category_source, old.merchant, old.model_asked_at) == (
        "uncategorized", CategorySource.none, None, NOW)
    assert CU.catch_up_book(engine, model, now=NOW).asked == 0          # asked once: no loop


def test_an_old_card_payment_a_built_in_now_matches_becomes_a_transfer_and_pairs(db, engine):
    """Ruling F5 revised: rows imported before phase 12's card-payment wordings."""
    checking = make_account(db)
    card = make_account(db, name="Sapphire", type="credit")
    pay = make_txn(db, checking, TODAY - timedelta(days=10), -120_000, "CHASE CREDIT CRD AUTOPAY PPD ID: 4760039224")
    pay.guess_category, pay.guess_pct = "shopping", 30
    paid = make_txn(db, card, TODAY - timedelta(days=7), 120_000, "PAYMENT RECEIVED")
    db.commit()
    assert CU.pending_count(db, NOW) == 2
    db.rollback()
    model = Model()
    result = CU.catch_up_book(engine, model, now=NOW)
    assert asked_of(model) == ["PAYMENT RECEIVED"] and result.ruled == 1
    db.rollback()
    assert (pay.category, pay.category_source, pay.is_transfer, pay.transfer_peer_id) == (
        "transfer", CategorySource.rule, True, paid.id)
    assert (pay.guess_category, pay.guess_pct, pay.model_asked_at) == (None, None, NOW)
    assert (paid.category, paid.is_transfer, paid.transfer_peer_id) == ("transfer", True, pay.id)
    assert CU.progress(db, NOW)["pending"] == 0


def test_an_old_zelle_row_gets_its_app_as_merchant_and_leaves_pending(db, engine):
    a = make_account(db)
    z = make_txn(db, a, TODAY - timedelta(days=30), -4_000, "ZELLE TO SAM 8817")      # no merchant: older ingest
    db.commit()
    assert CU.pending_count(db, NOW) == 1
    db.rollback()
    model = Model()
    assert CU.catch_up_book(engine, model, now=NOW).ruled == 1
    assert model.calls == []
    db.rollback()
    assert (z.merchant, z.category, z.category_source, z.is_transfer) == (
        "Zelle", "uncategorized", CategorySource.none, False)
    assert CU.pending_count(db, NOW) == 0


def test_an_old_row_in_an_investment_account_is_sorted_as_there_and_never_asked(db, engine):
    """As sort_investment_rows: a store rule (AMZN is Amazon) never fires on a trade, and the model never sees one."""
    acct = make_account(db, "Brokerage", type="brokerage_taxable")
    buy = make_txn(db, acct, TODAY - timedelta(days=5), -50_000, "BUY AMZN 2 SHS")
    div = make_txn(db, acct, TODAY - timedelta(days=6), 1_200, "DIVIDEND RECEIVED VTI")
    db.commit()
    model = Model()
    assert CU.catch_up_book(engine, model, now=NOW).ruled == 2 and model.calls == []
    db.rollback()
    assert (buy.category, buy.merchant, buy.category_source) == ("investment", None, CategorySource.rule)
    assert (div.category, div.category_source) == ("interest", CategorySource.rule)


def test_a_rule_answer_is_not_written_over_a_row_touched_since_the_read(db, engine, monkeypatch):
    a = make_account(db)
    t = make_txn(db, a, TODAY - timedelta(days=3), -9_000, "CITI AUTOPAY PAYMENT 0912")
    db.commit()
    real = CU._apply_rules

    def touch_first(engine_, ruled, now):
        with Session(engine_) as other:                 # the person sorts it between the read and the write
            row = other.get(Transaction, t.id)
            row.category, row.category_source = "shopping", CategorySource.correction
            other.commit()
        return real(engine_, ruled, now)
    monkeypatch.setattr(CU, "_apply_rules", touch_first)
    assert CU.catch_up_book(engine, Model(), now=NOW).ruled == 0
    db.rollback()
    assert (t.category, t.is_transfer, t.model_asked_at) == ("shopping", False, None)


def test_an_expired_snooze_is_pending_and_asked_and_a_live_one_is_neither(db, engine):
    a = make_account(db)
    back = make_txn(db, a, TODAY - timedelta(days=9), -500, "BACK CAFE")
    back.snoozed_until = NOW - timedelta(days=1)
    still = make_txn(db, a, TODAY - timedelta(days=9), -500, "STILL CAFE")
    still.snoozed_until = NOW + timedelta(days=1)
    db.commit()
    assert CU.pending_count(db, NOW) == 1
    db.rollback()
    model = Model()
    assert CU.catch_up_book(engine, model, now=NOW).categorized == 1
    assert asked_of(model) == ["BACK CAFE"]
    db.rollback()
    assert (back.category, back.model_asked_at) == ("dining", NOW)
    assert (still.category, still.model_asked_at) == ("uncategorized", None)


def test_maybe_catch_up_runs_only_when_ready_and_missed_or_pending_and_notes_the_features(books, db, ours):
    model = Model()
    model.missed = False
    assert CU.maybe_catch_up({"categorizer": True, "categorizer_features": ["guess"]}, model, books, NOW) is None
    assert model.features == frozenset({"guess"}) and model.calls == []      # nothing missed or pending: no run
    seed(db)
    model.missed = True
    assert CU.maybe_catch_up(None, model, books, NOW) is None
    assert CU.maybe_catch_up({"categorizer": False}, model, books, NOW) is None
    assert model.calls == []
    assert CU.maybe_catch_up({"categorizer": True}, model, books, NOW) == 2
    assert model.missed is False and model.features == frozenset()
    with Session(books.engine_for(ours)) as s:
        msgs = s.scalars(select(EventLog.message).where(EventLog.kind == "categorizer")).all()
    assert msgs == ["Categorized 2 transactions that came in while the gateway was off."]


def test_a_tick_asks_pending_rows_without_a_miss(books, db, ours):
    """Rows turn pending without a miss: an undone import or removed row unpairs, a snooze runs out."""
    a = make_account(db)
    make_txn(db, a, TODAY - timedelta(days=1), -500, "BEAN CAFE")
    db.commit()
    model = Model()
    model.missed = False
    assert CU.maybe_catch_up({"categorizer": True}, model, books, NOW) == 1
    assert asked_of(model) == ["BEAN CAFE"] and model.missed is False
    assert CU.maybe_catch_up({"categorizer": True}, model, books, NOW) is None     # nothing pending now
    assert len(model.calls) == 1


def test_the_null_model_never_runs_the_catch_up(books, db, ours):
    from steward.services.categorizer_client import NullModelClient
    a = make_account(db)
    make_txn(db, a, TODAY - timedelta(days=1), -500, "BEAN CAFE")
    db.commit()
    assert CU.maybe_catch_up({"categorizer": True}, NullModelClient(), books, NOW) is None


def test_a_book_mid_sync_is_skipped_and_tried_again(books, db, ours):
    seed(db)
    model = Model()
    with books.sync_lock(ours.id):
        assert CU.maybe_catch_up({"categorizer": True}, model, books, NOW) == 0
    assert model.missed is True and model.calls == []


def test_the_catch_up_keeps_the_business_hint_for_money_out(db, engine):
    a = make_account(db)
    out = make_txn(db, a, TODAY - timedelta(days=3), -2_900, "NOTEFLOW CAFE")
    back = make_txn(db, a, TODAY - timedelta(days=3), 2_900, "NOTEFLOW CAFE REFUND")
    db.commit()
    CU.catch_up_book(engine, Model(answer=lambda d: ("subscriptions", None, 91)), now=NOW)
    db.rollback()
    assert db.get(Transaction, out.id).business_hint == 91
    assert db.get(Transaction, back.id).business_hint is None


def test_a_tick_asks_a_few_batches_and_the_rest_waits_for_the_next(books, db, ours):
    a = make_account(db)
    for i in range(400):
        make_txn(db, a, TODAY - timedelta(days=1), -500, f"BEAN CAFE {i:03d}")
    db.commit()
    model = Model()
    assert CU.maybe_catch_up({"categorizer": True}, model, books, NOW) == 150
    assert len(model.calls) == CU.TICK_BATCHES and model.missed is True
    totals = [150]
    while model.missed:
        totals.append(CU.maybe_catch_up({"categorizer": True}, model, books, NOW))
    assert totals == [150, 150, 100] and len(model.calls) == 8


def test_rows_the_model_had_no_answer_for_are_not_asked_again_even_after_a_restart(books, db, ours):
    a = make_account(db)
    make_txn(db, a, TODAY - timedelta(days=1), -500, "POS PURCHASE")
    db.commit()
    model = Model()
    assert CU.maybe_catch_up({"categorizer": True}, model, books, NOW) == 0
    assert len(model.calls) == 1
    model = Model()                                     # a restart: the mark is on the row, not in memory
    CU.maybe_catch_up({"categorizer": True}, model, books, NOW)
    assert model.calls == []
    make_txn(db, a, TODAY - timedelta(days=1), -500, "NEW CAFE")
    db.commit()
    model.missed = True
    assert CU.maybe_catch_up({"categorizer": True}, model, books, NOW) == 1
    assert [d for d, _ in model.calls[-1]] == ["NEW CAFE"]


def test_the_wave_counts_pending_and_done_and_restarts_when_pending_was_zero(db, engine):
    a = make_account(db)
    assert CU.progress(db, NOW) == {"pending": 0, "done": 0}
    db.rollback()
    for i in range(3):
        make_txn(db, a, TODAY - timedelta(days=1), -500, f"MYSTERY {i}")
    make_txn(db, a, TODAY - timedelta(days=1), -4000, "ZELLE TO SAM", merchant="Zelle")   # p2p: never pending
    db.commit()
    assert CU.progress(db, NOW) == {"pending": 3, "done": 0}                 # no wave stamped yet: nothing asked
    db.rollback()
    model = Model(answer=lambda d: None)
    CU.catch_up_book(engine, model, now=NOW, per_run=2)
    assert CU.progress(db, NOW) == {"pending": 1, "done": 2}
    db.rollback()
    assert db.get(WatchState, CU.WAVE).value == NOW.isoformat()
    db.rollback()
    CU.catch_up_book(engine, model, now=NOW + timedelta(minutes=1))
    assert CU.progress(db, NOW) == {"pending": 0, "done": 0}                 # the wave is over: nothing shows
    db.rollback()
    later = NOW + timedelta(hours=1)
    CU.begin_wave(db, later)                                            # new rows arrive with none pending
    make_txn(db, a, TODAY, -500, "MYSTERY 9")
    db.commit()
    assert CU.progress(db, NOW) == {"pending": 1, "done": 0}                 # the old asks don't count in the new wave
    db.rollback()
    assert db.get(WatchState, CU.WAVE).value == later.isoformat()


def test_progress_survives_a_row_deleted_mid_wave(client, db, books, ours):
    """Review Focus 4."""
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})
    a = make_account(db)
    rows = [make_txn(db, a, TODAY - timedelta(days=1), -500, f"MYSTERY {i}") for i in range(4)]
    db.commit()
    model = Model(answer=lambda d: None)
    CU.catch_up_book(books.engine_for(ours), model, now=NOW, per_run=2)
    assert CU.progress(db, NOW) == {"pending": 2, "done": 2}
    db.rollback()
    asked_id = next(t.id for t in rows if db.get(Transaction, t.id).model_asked_at is not None)
    db.rollback()
    assert client.delete(f"/api/b/ours/transactions/{asked_id}").status_code == 204
    db.rollback()
    assert CU.progress(db, NOW) == {"pending": 2, "done": 1}
    db.rollback()
    CU.catch_up_book(books.engine_for(ours), model, now=NOW + timedelta(minutes=1))
    assert len(set(asked_of(model))) == 4 and CU.progress(db, NOW) == {"pending": 0, "done": 0}


def test_ingest_starts_a_wave_when_rows_arrive_with_none_pending(db, engine):
    from steward.services.importers.base import ParsedRow
    from steward.services.ingest import ingest_rows
    a = make_account(db)
    at = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    ingest_rows(db, a, [ParsedRow(TODAY, -500, "POS PURCHASE", None)], batch=None, now=at, model=None)
    db.commit()
    assert db.get(WatchState, CU.WAVE).value == at.isoformat() and CU.progress(db, NOW) == {"pending": 1, "done": 0}
    db.rollback()
    ingest_rows(db, a, [ParsedRow(TODAY, -500, "POS PURCHASE 2", None)], batch=None, now=at + timedelta(hours=1), model=None)
    db.commit()
    assert db.get(WatchState, CU.WAVE).value == at.isoformat()          # pending wasn't 0: the wave goes on
