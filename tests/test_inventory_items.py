import json
from datetime import date

import pytest
from sqlalchemy import select

from steward.db.models import Account, AccountType, BalanceSnapshot, ChangeRecord, EventLog, InventoryItem
from steward.events import log_event
from steward.inventory.items import (
    ItemRefused, close_item, create_item, details_of, edit_item, reopen_item, reveal,
)

TODAY = date(2026, 10, 18)


def _policy(mdb, mctx, **over):
    body = {"kind": "insurance", "name": "Medicare supplement", "owner": "margaret", "institution": "Globe Mutual",
            "number": "GM-55120-0861", "status": "needs_checking", "check_reason": "From a premium notice",
            "details": {"type": "supplement", "amount_cents": 18620, "frequency": "monthly", "usual_day": 15}}
    body.update(over)
    return create_item(mdb, mctx, body, today=TODAY)


def _rows(mdb):
    return list(mdb.scalars(select(ChangeRecord).order_by(ChangeRecord.id)))


def test_a_policy_keeps_its_full_number_but_records_only_the_last_4(mdb, mctx):
    item = _policy(mdb, mctx)
    assert (item.full_number, item.last4, item.status, item.check_reason) == (
        "GM-55120-0861", "0861", "needs_checking", "From a premium notice")
    row = _rows(mdb)[-1]
    assert row.action == "item.add" and json.loads(row.after)["number"] == "••0861"
    assert all("55120" not in (r.before or "") + (r.after or "") for r in _rows(mdb))


def test_a_statement_account_makes_its_account_row_and_balance(mdb, mctx):
    item = create_item(mdb, mctx, {"kind": "account", "name": "12-month CD", "owner": "margaret",
                                   "institution": "Pacific Western Credit Union", "last4": "0072",
                                   "status": "confirmed", "data_source": "statement", "details": {"type": "cd"},
                                   "balance_cents": 4_000_000, "balance_on": "2026-09-30"}, today=TODAY)
    acct = mdb.get(Account, item.account_id)
    assert (acct.name, acct.type, acct.owner) == ("12-month CD", AccountType.savings, "margaret")
    snap = mdb.scalar(select(BalanceSnapshot).where(BalanceSnapshot.account_id == acct.id))
    assert (snap.as_of, snap.balance_cents) == (date(2026, 9, 30), 4_000_000)


@pytest.mark.parametrize("body,message", [
    ({"kind": "account", "data_source": "feed", "details": {"type": "checking"}}, "Bank feed accounts arrive on their own."),
    ({"kind": "boat"}, "Choose what kind of item this is."),
    ({"owner": "jr"}, "Choose one of this book's owners."),
    ({"name": " "}, "Enter a name of up to 120 characters."),
    ({"status": "maybe"}, "Choose Confirmed or Needs checking."),
    ({"kind": "income", "details": {"source": "pension", "frequency": "monthly"}}, "Enter an amount in dollars and cents."),
    ({"kind": "income", "details": {"source": "pension", "amount_cents": 100}}, "Choose how often."),
    ({"kind": "document", "details": {"type": "will"}}, "Say where the original is kept."),
    ({"kind": "account", "details": {"type": "credit_card"}, "balance_cents": 500}, "Enter what Margaret owes as a negative number."),
    ({"number": "x" * 41}, "Enter the number as it's printed, up to 40 characters."),
    ({"details": {"type": "supplement", "renewal_on": "03/01/2026"}}, "Enter a date like 2026-03-01."),
    ({"details": {"type": "supplement", "usual_day": 32}}, "Enter a day of the month from 1 to 31."),
])
def test_refusals(mdb, mctx, body, message):
    base = {"kind": "insurance", "name": "Policy", "owner": "margaret", "status": "confirmed",
            "details": {"type": "supplement"}}
    with pytest.raises(ItemRefused, match="^" + message.replace("(", r"\(").replace(")", r"\)") + "$"):
        create_item(mdb, mctx, {**base, **body}, today=TODAY)


def test_references_must_be_the_right_kind(mdb, mctx):
    poa = create_item(mdb, mctx, {"kind": "document", "name": "POA", "owner": "margaret", "status": "confirmed",
                                  "details": {"type": "power_of_attorney", "original_kept_in": "Fire safe"}},
                      today=TODAY)
    with pytest.raises(ItemRefused, match="^Choose an item from this book.$"):
        create_item(mdb, mctx, {"kind": "income", "name": "Pension", "owner": "margaret", "status": "confirmed",
                                "details": {"source": "pension", "amount_cents": 138500, "frequency": "monthly",
                                            "lands_in_id": poa.id}}, today=TODAY)


def test_contacts_are_always_confirmed(mdb, mctx):
    c = create_item(mdb, mctx, {"kind": "contact", "name": "Linda Park", "owner": "margaret",
                                "status": "needs_checking", "institution": "Park & Reyes Law",
                                "details": {"role": "attorney", "email": "lpark@example.com"}}, today=TODAY)
    assert c.status == "confirmed"


def test_an_edit_records_only_what_changed_and_why(mdb, mctx):
    item = _policy(mdb, mctx)
    edit_item(mdb, mctx, item, {"status": "confirmed", "details": {"renewal_on": "2027-03-01"},
                                "note": "Policy letter arrived Oct 18"}, today=TODAY)
    row = _rows(mdb)[-1]
    assert row.action == "item.edit" and row.note == "Policy letter arrived Oct 18"
    assert json.loads(row.before) == {"status": "needs_checking", "check_reason": "From a premium notice",
                                      "renewal_on": None}
    assert json.loads(row.after) == {"status": "confirmed", "check_reason": None, "renewal_on": "2027-03-01"}
    n = len(_rows(mdb))
    edit_item(mdb, mctx, item, {"name": "Medicare supplement"}, today=TODAY)
    assert len(_rows(mdb)) == n   # nothing changed, nothing recorded


def test_a_new_number_is_recorded_masked(mdb, mctx):
    item = _policy(mdb, mctx)
    edit_item(mdb, mctx, item, {"number": "GM-55120-9999"}, today=TODAY)
    row = _rows(mdb)[-1]
    assert (json.loads(row.before), json.loads(row.after)) == ({"number": "••0861"},
                                                               {"number": "••9999"})


def test_close_and_reopen(mdb, mctx):
    item = create_item(mdb, mctx, {"kind": "account", "name": "Savings", "owner": "margaret", "institution": "Chase",
                                   "status": "confirmed", "data_source": "statement",
                                   "details": {"type": "savings"}}, today=TODAY)
    close_item(mdb, mctx, item, {"closed_on": "2025-02-14", "why": "Moved to Wells Fargo savings"})
    assert (item.status, item.closed_on, mdb.get(Account, item.account_id).is_active) == ("closed", date(2025, 2, 14), False)
    with pytest.raises(ItemRefused, match="Reopen it to change it") as e:
        edit_item(mdb, mctx, item, {"name": "x"}, today=TODAY)
    assert e.value.status == 409
    reopen_item(mdb, mctx, item)
    assert (item.status, item.closed_on, mdb.get(Account, item.account_id).is_active) == ("confirmed", None, True)
    assert [r.action for r in _rows(mdb)][-2:] == ["item.close", "item.reopen"]


def test_reveal_returns_the_number_and_records_it(mdb, mctx):
    item = _policy(mdb, mctx)
    assert reveal(mdb, mctx, item) == "GM-55120-0861"
    assert _rows(mdb)[-1].action == "item.reveal"
    bare = _policy(mdb, mctx, number=None)
    with pytest.raises(ItemRefused, match="^No full number is saved for this item.$") as e:
        reveal(mdb, mctx, bare)
    assert e.value.status == 404


def test_typing_a_feed_accounts_type_clears_its_new_account_notice(mdb, mctx):
    from steward.db.models import Institution, Source
    inst = Institution(name="Wells Fargo", source=Source.simplefin, simplefin_org_id="wf")
    acct = Account(institution=inst, name="CHECKING 4417", type=AccountType.unknown, owner="joint",
                   source=Source.simplefin, external_id="sfin:1")
    mdb.add(acct)
    mdb.flush()
    log_event(mdb, "info", "system", "New account 'CHECKING 4417' from Wells Fargo is in the inventory. "
                                     "Set its type and owner there.", actionable=True)
    item = InventoryItem(kind="account", name="CHECKING 4417", owner="joint", status="confirmed", data_source="feed",
                         account_id=acct.id, details=json.dumps({"type": None}))
    mdb.add(item)
    mdb.flush()
    edit_item(mdb, mctx, item, {"name": "Joint checking", "details": {"type": "checking"}}, today=TODAY)
    assert (acct.type, acct.name) == (AccountType.checking, "Joint checking")
    assert mdb.scalar(select(EventLog.resolved_at)) is not None
    with pytest.raises(ItemRefused, match="comes from the bank feed"):
        edit_item(mdb, mctx, item, {"balance_cents": 5}, today=TODAY)
