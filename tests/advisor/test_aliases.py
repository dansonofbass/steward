from datetime import date

from sqlalchemy import func, select

from steward.advisor.aliases import Aliases, display, payee_label
from steward.db.models import AdvisorAlias, Child
from steward.demo_parent import seed_parent
from tests.factories import make_account, make_user

TODAY = date(2026, 10, 18)


def test_household_owners_and_people(db, books, ours):
    jr = make_user(db)
    sam = make_user(db, username="sam", email="sam@x.com", display_name="Sam")
    third = make_user(db, username="kai", email="kai@x.com", display_name="Kai")
    a = Aliases(db, ours, books.people(ours.id))
    assert [a.owner(k) for k in ("jr", "spouse", "joint", "business")] == ["Person 1", "Person 2", "Joint", "Business"]
    assert (a.user(jr.id), a.user(sam.id), a.user(third.id)) == ("Person 1", "Person 2", "Person 3")
    db.commit()
    assert Aliases(db, ours, books.people(ours.id)).user(third.id) == "Person 3"


def test_parent_owners_then_members(margaret, mdb, books):
    people = books.people(margaret.id)
    a = Aliases(mdb, margaret, people)
    assert [a.owner(k) for k in ("margaret", "robert-husband", "joint")] == ["Parent", "Person 2", "Joint"]
    assert sorted(a.user(p.id) for p in people) == ["Person 3", "Person 4"]


def test_children_are_numbered_oldest_first_whoever_asks_first(db, books, ours):
    young, old = Child(label="Youngest", birth_year=2021, cost_level="in_state_public", monthly_contribution_cents=0), \
        Child(label="Oldest", birth_year=2015, cost_level="in_state_public", monthly_contribution_cents=0)
    db.add_all([young, old])
    db.commit()
    a = Aliases(db, ours, ())
    assert a.child(young.id) == "Child 2" and a.child(old.id) == "Child 1"


def test_accounts_and_payees_in_order_and_stable(db, books, ours):
    x, y = make_account(db, "Checking"), make_account(db, "Savings", type="savings")
    a = Aliases(db, ours, ())
    assert (a.account(x.id), a.account(y.id), a.payee("ZELLE:J SMITH"), a.payee("CVS PHARMACY")) == (
        "Account 1", "Account 2", "Payee 1", "Payee 2")
    db.commit()
    again = Aliases(db, ours, ())
    assert again.account(y.id) == "Account 2" and again.existing("payee", "CVS PHARMACY") == "Payee 2"
    assert again.existing("payee", "SOMEONE NEW") is None


def test_a_dry_run_saves_nothing(db, books, ours):
    x = make_account(db, "Checking")
    assert Aliases(db, ours, (), save=False).account(x.id) == "Account 1"
    db.commit()
    assert db.scalar(select(func.count()).select_from(AdvisorAlias).where(AdvisorAlias.kind == "account")) == 0


def test_labels_put_real_names_back_on_screen(margaret, mdb, books):
    ids = seed_parent(mdb, TODAY)
    from steward.db.models import InventoryItem
    checking = mdb.get(InventoryItem, ids["Joint checking"])
    people = books.people(margaret.id)
    a = Aliases(mdb, margaret, people)
    acct = a.account(checking.account_id)
    a.payee("zelle:J SMITH")
    labels = a.labels()
    assert labels["Parent"] == "Margaret" and labels["Person 2"] == "Robert (husband)" and labels["Joint"] == "Joint"
    assert labels[acct] == "Joint checking ••4417"
    assert labels["Payee 1"] == "Zelle to J Smith"
    assert display(f"{acct} paid Payee 1 for Parent, not {acct}0.", labels) == \
        f"Joint checking ••4417 paid Zelle to J Smith for Margaret, not {acct}0."


def test_payee_labels():
    assert payee_label("CVS PHARMACY") == "CVS Pharmacy"
    assert payee_label("paypal:JOHNDOE") == "Paypal to Johndoe"


def test_aliases_are_protected_only_when_issued(db, books, ours):
    make_user(db)
    x = make_account(db, "Checking")
    a = Aliases(db, ours, books.people(ours.id), save=False)
    text = "Person 1 sent Account 1 to Payee 1, not Person 12."
    assert a.issued == frozenset() and a.protected(text) == []
    p1, acct = a.owner("jr"), a.account(x.id)
    assert a.issued == {p1, acct} == {"Person 1", "Account 1"}
    assert [text[s:e] for s, e in a.protected(text)] == ["Person 1", "Account 1"]
    # An alias nobody was given this turn, and a look-alike spelling of one that was, shield nothing.
    assert a.existing("owner", "spouse") == "Person 2" and "Person 2" not in a.issued
    assert a.protected("Person 2") == []
    assert a.protected("Рerson 1") == []
