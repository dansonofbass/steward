"""Ruling I1 (final review): rows on a business-type account, or one owned by Business, are business unless a person
said otherwise, and every row on a cash account lands in exactly one of the personal or business share."""
from datetime import date, datetime, timezone

from steward.business.report import business_report
from steward.business.settings import update_settings
from steward.business.tagging import set_business
from steward.db.models import Owner
from steward.deps import now
from steward.services.cashflow import cashflow
from steward.services.importers.base import ParsedRow
from steward.services.ingest import ingest_rows
from steward.services.vault_flows import derive_flows
from tests.factories import login, make_account, make_txn

TODAY = date(2026, 10, 13)
AT = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)


def tags(rows):
    return [(t.business_pct, t.business_source, t.is_business) for t in rows]


def test_rows_on_a_business_type_account_in_jrs_name_are_business_at_import(db):
    bchk = make_account(db, "Business checking", type="business_checking", owner=Owner.jr)
    owned = make_account(db, "Shop checking", type="checking", owner=Owner.business)
    mine = make_account(db, "Checking", type="checking", owner=Owner.jr)
    rows = [ParsedRow(date(2026, 3, 3), 300_000, "ACH CLIENT INV 1", "c1"),
            ParsedRow(date(2026, 3, 4), -2_900, "NOTEFLOW PRO", "c2")]
    assert tags(ingest_rows(db, bchk, rows, batch=None, now=now(), model=None)) == [(100, "account", True)] * 2
    assert tags(ingest_rows(db, owned, rows, batch=None, now=now(), model=None)) == [(100, "account", True)] * 2
    assert tags(ingest_rows(db, mine, rows, batch=None, now=now(), model=None)) == [(0, "none", False)] * 2


def test_the_business_report_sees_a_business_type_account_in_jrs_name(db):
    bchk = make_account(db, "Business checking", type="business_checking", owner=Owner.jr)
    ingest_rows(db, bchk, [ParsedRow(date(2026, 3, 3), 300_000, "ACH CLIENT INV 1", "c1")], batch=None, now=now(),
                model=None)
    db.commit()
    update_settings(db, {"type": "sole_prop"}, year=2026, this_year=2026, periods=2, user_id=1, at=AT)
    assert business_report(db, 2026, TODAY).income_cents == 300_000


def test_every_row_counts_once_personal_share_of_a_split_on_a_business_card_is_personal(db):
    card = make_account(db, "Rewards Card", type="credit")
    bcard = make_account(db, "Business card", type="business_credit", owner=Owner.business)
    bchk = make_account(db, "Business checking", type="business_checking", owner=Owner.jr)
    make_txn(db, card, date(2026, 1, 1), -1_000, "CORNER CAFE", category="dining")             # starts the window
    make_txn(db, card, date(2026, 3, 2), -9_000, "GREENLEAF MARKET", category="groceries")
    phone = make_txn(db, bcard, date(2026, 3, 3), -10_000, "MOBILE ONE WIRELESS", category="utilities")
    set_business(phone, 70, source="manual")
    lunch = make_txn(db, bchk, date(2026, 3, 4), -5_000, "HARBOR GRILL", category="dining")
    set_business(lunch, 0, source="manual")                                                     # a person said Personal
    make_txn(db, bchk, date(2026, 3, 5), -2_900, "NOTEFLOW PRO", category="subscriptions")      # business by account
    db.commit()
    personal = 1_000 + 9_000 + 3_000 + 5_000
    f = derive_flows(db, TODAY)
    assert f.money_out_cents == personal
    march = next(m for m in cashflow(db, TODAY, 12) if m["month"] == "2026-03")
    assert march["out_cents"] == 9_000 + 3_000 + 5_000
    update_settings(db, {"type": "sole_prop", "car_method": "actual"}, year=2026, this_year=2026, periods=2,
                    user_id=1, at=AT)
    r = business_report(db, 2026, TODAY)
    assert r.expenses_cents == 7_000 + 2_900                      # 70% of the phone and the subscription
    assert r.expenses_cents + (march["out_cents"]) == 10_000 + 5_000 + 2_900 + 9_000


def test_changing_an_accounts_type_or_owner_re_tags_its_rows_but_never_a_persons_choice(signed_in, db):
    acct = make_account(db, "Checking", type="checking", owner=Owner.jr)
    plain = make_txn(db, acct, date(2026, 3, 3), -2_900, "NOTEFLOW PRO")
    chosen = make_txn(db, acct, date(2026, 3, 4), -5_000, "HARBOR GRILL")
    set_business(chosen, 0, source="manual")
    moved = make_txn(db, acct, date(2026, 3, 5), -50_000, "TRANSFER", category="transfer", is_transfer=True)
    db.commit()
    assert signed_in.patch(f"/api/b/ours/accounts/{acct.id}", json={"type": "business_checking"}).status_code == 200
    db.commit()                                               # see what the request wrote
    for t in (plain, chosen, moved):
        db.refresh(t)
    assert tags([plain, chosen, moved]) == [(100, "account", True), (0, "manual", False), (0, "none", False)]
    assert signed_in.patch(f"/api/b/ours/accounts/{acct.id}", json={"type": "checking"}).status_code == 200
    db.commit()
    db.refresh(plain)
    assert tags([plain]) == [(0, "none", False)]
    assert signed_in.patch(f"/api/b/ours/accounts/{acct.id}", json={"owner": "business"}).status_code == 200
    db.commit()
    db.refresh(plain)
    assert tags([plain]) == [(100, "account", True)]


def test_a_parent_books_business_owner_is_never_tagged_business(margaret, mdb, mctx):
    """Spec 5, household books only: a parent book's account owned by "Business" is an ordinary account."""
    from steward.business.tagging import is_business_account, retag_account
    from steward.services.imports import commit_batch
    acct = make_account(mdb, "Shop checking", type="checking", owner="business")
    assert is_business_account(acct) is True and is_business_account(acct, household=False) is False
    rows = [ParsedRow(date(2026, 3, 3), -2_900, "NOTEFLOW PRO", "p1")]
    assert tags(ingest_rows(mdb, acct, rows, batch=None, now=now(), model=None, household=False)) == [(0, "none", False)]
    batch = commit_batch(mdb, acct.id, "x.csv", "generic", [ParsedRow(date(2026, 3, 4), -1_000, "CORNER CAFE", "p2")],
                         mctx.user_id, [False], now(), household=False)
    assert batch.row_count == 1
    assert retag_account(mdb, acct, household=False) == 0


def test_a_parent_books_account_cannot_be_patched_into_business(margaret, mdb, client):
    acct = make_account(mdb, "Shop checking", type="checking", owner="business")
    t = make_txn(mdb, acct, date(2026, 3, 3), -2_900, "NOTEFLOW PRO", is_business=False)
    mdb.commit()
    login(client, "jr")
    r = client.patch(f"/api/b/{margaret.slug}/accounts/{acct.id}", json={"type": "business_checking"})
    assert r.status_code == 404
    mdb.refresh(t)
    assert tags([t]) == [(0, "none", False)]
