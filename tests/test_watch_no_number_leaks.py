"""Summaries and titles are safe by construction (follow-up item 17): a transaction, account and item named with a
16-digit number joined by mixed separators leak no 5 digits in order into any flag of any check type, its title, the
flags API, either email or the book's events."""
import json
import re
from datetime import date

import pytest
from sqlalchemy import select

from steward.db.models import EventLog, Flag, FlagEvent, Institution, InventoryItem, MailOutbox, SimplefinLink, Transaction
from steward.inventory.present import safe_line
from steward.services.accounts import record_balance
from steward.watch import checks as C
from steward.watch.balances import check_low, check_new_accounts
from steward.watch.checks import History, Rules, Txn, check
from steward.watch.due import check_missed
from steward.watch.emails import summary_email, urgent_email
from steward.watch.outbox import fail_unprepared
from steward.watch.payees import Payee
from steward.watch.store import FEED_ACCOUNTS, add_flag, set_state
from steward.watch.views import email_facts
from tests.factories import login
from tests.watch_helpers import NOW, TODAY, account, d

DIGITS = "5083741629053871"
PAYEE = "Acme 5083-7416 2905/3871"
ACCOUNT = "Chk 5083.7416_2905 3871"
ITEM = "Savings 5083 – 7416|2905,3871"
BANK = "Bank 5083-7416 2905/3871"
BOOK = "/api/b/margaret-ellis"
ARGS = {"book_name": "Margaret Ellis", "slug": "margaret-ellis", "base_url": "https://nas", "name": "Margaret"}


def leaks(text: str) -> bool:
    flat = re.sub(r"\D", "", text)
    return any(DIGITS[i:i + 5] in flat for i in range(len(DIGITS) - 4))


@pytest.fixture
def at_now(monkeypatch):
    monkeypatch.setattr("steward.clock.now", lambda: NOW)


def T(id, days_ago, cents, raw, **kw) -> Txn:
    return Txn(id, 1, d(days_ago), cents, raw, **kw)


def _hits(monkeypatch) -> list[C.Hit]:
    """One hit of every transaction check, each payee named with the number."""
    real = C.payee
    monkeypatch.setattr(C, "payee", lambda raw, merchant=None: Payee(*(lambda p: (p.key, PAYEE, p.method))(real(raw, merchant))))
    start = Txn(1, 1, d(400), 100_000, "OPENING DEPOSIT", category="income")
    out: list[C.Hit] = []

    def run(txns, target, first=start):
        out.extend(check(History([first, *txns]), target, Rules()))

    gift = T(3, 2, -50_000, "CVS GIFT CARD FULLERTON CA", category="shopping")
    run([gift], gift)
    health = [T(10 + i, 40 + 30 * i, -a, "DENTAL", category="health") for i, a in enumerate((4000, 5000, 6000))]
    big = T(2, 5, -20_000, "DENTAL", category="health")
    run([*health, big], big)
    past = [T(2, 35, -10_000, "ATM WITHDRAWAL 1"), T(3, 65, -10_000, "ATM WITHDRAWAL 1"),
            T(4, 95, -10_000, "ATM WITHDRAWAL 1")]
    early, cash = T(5, 10, -6000, "ATM WITHDRAWAL 88"), T(6, 5, -8000, "ATM WITHDRAWAL 88")
    run([*past, early, cash], cash, Txn(1, 1, d(120), 100_000, "OPENING DEPOSIT", category="income"))
    first, second = T(2, 31, -1599, "SB", category="subscriptions"), T(3, 1, -1599, "SB", category="subscriptions")
    run([first, second], second)
    seen, a, b = T(2, 100, -5210, "R"), T(3, 6, -6418, "R"), T(4, 5, -6418, "R")
    run([seen, a, b], b)
    return out


def test_no_flag_text_leaks_five_digits_of_a_number(at_now, margaret, mdb, client, ddb, monkeypatch):
    chk = account(mdb, ACCOUNT, feed=True, institution=BANK)
    ids = []
    for h in _hits(monkeypatch):
        facts = {**h.facts, "posted_at": "2026-10-17", "raw": f"{PAYEE} CARD {DIGITS}", "account": ACCOUNT}
        f = add_flag(mdb, check=h.check, severity=h.severity, summary=h.summary, title=h.title, facts=facts, now=NOW,
                     after="sync", account_id=chk.id)
        ids.append(f.id)

    save = account(mdb, ITEM, "savings", feed=True, institution=BANK)
    record_balance(mdb, save.id, d(1), 2_248_010)
    item = mdb.scalar(select(InventoryItem).where(InventoryItem.account_id == save.id))
    item.details = json.dumps({**json.loads(item.details), "floor_cents": 2_500_000})
    mdb.commit()
    ids += check_low(mdb, TODAY, NOW, after="sync")
    set_state(mdb, FEED_ACCOUNTS, json.dumps([chk.id]), NOW)
    ids += check_new_accounts(mdb, NOW, after="sync")

    due_chk = account(mdb, "Joint checking", feed=True)
    due_item = mdb.scalar(select(InventoryItem).where(InventoryItem.account_id == due_chk.id))
    mdb.add_all([
        InventoryItem(kind="insurance", name=ITEM, owner="margaret", institution=BANK, status="needs_checking",
                      data_source="manual",
                      details=json.dumps({"type": "long_term_care", "amount_cents": 21_200, "frequency": "monthly",
                                          "usual_day": 10, "paid_from_id": due_item.id, "match_text": "EVERGREEN"})),
        InventoryItem(kind="income", name=ITEM, owner="margaret", institution="SSA", status="confirmed",
                      data_source="feed", details=json.dumps({"source": "social_security", "amount_cents": 214_000,
                                                              "frequency": "monthly", "usual_day": 3,
                                                              "lands_in_id": due_item.id, "match_text": "SSA"}))])
    mdb.get(Institution, due_chk.institution_id).last_sync_at = NOW
    record_balance(mdb, due_chk.id, NOW.date(), 100_000)
    mdb.add(SimplefinLink(access_url="http://demo:demo@testserver/simplefin", claimed_at=NOW, last_sync_at=NOW))
    mdb.add(Transaction(account_id=due_chk.id, posted_at=d(300), amount_cents=1000, raw_description="OPEN"))
    mdb.commit()
    ids += check_missed(mdb, date(2026, 10, 17), NOW)
    flags = [mdb.get(Flag, i) for i in ids]
    assert {f.check for f in flags} >= {"scam", "large", "payee", "unusual", "cash", "monthly", "duplicate", "low",
                                        "account", "deposit", "premium"}

    # a row stored before the builders were safe holds the whole number; it is made safe when shown
    old = add_flag(mdb, check="large", severity="normal", summary=f"$1,640.00 to {PAYEE} on Oct 17",
                   title=f"$1,640.00 to {PAYEE}", now=NOW, after="sync",
                   facts={"amount_cents": 164_000, "payee": "other", "account": "x", "posted_at": "2026-10-17"})
    mdb.commit()
    flags.append(old)
    assert safe_line(old.summary) == "$1,640.00 to Acme •/3871 on Oct 17"

    blobs = []
    for f in flags:
        e = urgent_email(f, email_facts(mdb, f), large_cents=50_000, **ARGS)
        blobs += [e.subject, e.text, e.html]
        row = MailOutbox(kind="urgent", flag_id=f.id, flag_ids=json.dumps([f.id]), status="pending", created_at=NOW,
                         next_try_at=NOW, to_user_ids="[]")
        mdb.add(row)
        mdb.flush()
        fail_unprepared(mdb, row, NOW)
    s = summary_email(flags, today=TODAY, still=None, **ARGS)
    blobs += [s.subject, s.text, s.html]
    mdb.commit()
    blobs += [e.message for e in mdb.scalars(select(EventLog))]
    blobs += [fe.detail or "" for fe in mdb.scalars(select(FlagEvent))]
    for text in blobs:
        for piece in re.split(r"[\n<>]", text):      # each line or tag text: ids and link numbers sit on their own
            assert not leaks(piece), piece
    for f in flags[:-1]:
        assert not leaks(f.summary) and not leaks(f.title), f.check      # built safe

    def strings(v):
        if isinstance(v, str):
            yield v
        elif isinstance(v, dict):
            for x in v.values():
                yield from strings(x)
        elif isinstance(v, list):
            for x in v:
                yield from strings(x)

    login(client, "jr")
    answers = [client.get(f"{BOOK}/flags?show={show}") for show in ("open", "done")]
    answers += [client.get(f"{BOOK}/flags/{f.id}") for f in flags]
    for r in answers:
        assert r.status_code == 200
        for text in strings(r.json()):           # field by field: ids and counts sit next to names in the raw JSON
            assert not leaks(text), text
