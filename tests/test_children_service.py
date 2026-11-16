"""529 suggestions (P18), each 529's balance, deposits and return (P16-P17), and the purge of removed kids (P27)."""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from steward.db.models import BalanceSnapshot, Child
from steward.services import children
from tests.factories import make_account, make_txn

T = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)


def kid(db, label, account=None, removed=None):
    c = Child(label=label, birth_year=2015, cost_level="not_sure", account_id=account.id if account else None,
              monthly_contribution_cents=0, removed_at=removed)
    db.add(c)
    db.commit()
    return c


def test_suggestions_match_a_whole_first_name_once(db):
    """Review Focus 3."""
    ava, zoe, ben = kid(db, "Ava Rose"), kid(db, "Zoë"), kid(db, "Ben")
    make_account(db, "Zoe & Ava 529", type="plan529")                 # two kids in one name: no suggestion for either
    make_account(db, "Avery's 529", type="plan529")                    # not a whole-word Ava
    ben529 = make_account(db, "BEN's college fund", type="savings")    # case, an apostrophe, another type
    make_account(db, "Ben Design", type="business_checking")           # excluded type
    make_account(db, "Ben card", type="credit")                        # excluded type
    got = children.suggest(db)
    assert got == [{"child_id": ben.id, "account_id": ben529.id, "account_name": "BEN's college fund", "account_type": "savings"}]
    assert children.fold("Zoë") == "zoe" and children.first_name("Ava Rose") == "ava"
    assert {ava.id, zoe.id}.isdisjoint({g["child_id"] for g in got})


def test_a_kid_with_two_matching_accounts_gets_no_suggestion_and_a_linked_kid_none(db):
    p = make_account(db, "Cy 529", type="plan529")
    kid(db, "Cy", p)                                                  # already linked: the select isn't empty
    kid(db, "Dee")
    make_account(db, "Dee 529", type="plan529")
    make_account(db, "Dee savings", type="savings")
    assert children.suggest(db) == []


def test_plans_carry_balance_connected_deposits_and_return(db):
    chk = make_account(db, "Checking", type="checking", source="simplefin", institution_name="Bank")
    p = make_account(db, "Fidelity 529", type="plan529", source="simplefin", institution_name="Bank")
    db.add(BalanceSnapshot(account_id=p.id, as_of=date(2026, 10, 1), balance_cents=1_234_500))
    db.commit()
    for m in range(12):                                                # $250 a month for a year, paired as transfers
        out = make_txn(db, chk, date(2025, 10, 20) + timedelta(days=30 * m), -25_000, "TO 529", is_transfer=True)
        into = make_txn(db, p, out.posted_at, 25_000, "FROM CHECKING", is_transfer=True)
        out.transfer_peer_id, into.transfer_peer_id = into.id, out.id
    db.commit()
    (plan,) = children.plans_out(db, date(2026, 10, 13))
    assert (plan["account_id"], plan["balance_cents"], plan["connected"]) == (p.id, 1_234_500, True)
    assert plan["deposits_monthly_cents"] == 25_000 and 0.0 < plan["real_return"] < 0.1


def test_removed_kids_are_purged_once_the_undo_window_has_passed(db):
    kid(db, "Old", removed=T - timedelta(minutes=16))
    kid(db, "New", removed=T - timedelta(minutes=5))
    children.purge_removed(db, T)
    db.commit()
    assert [c.label for c in db.scalars(select(Child))] == ["New"]
