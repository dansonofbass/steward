from datetime import date

import pytest
from sqlalchemy import select

from steward.db.models import ImportBatch, Suggestion, Transaction
from steward.demo_parent import seed_parent
from steward.inventory.suggestions import refresh
from tests.factories import login

BOOK = "/api/b/margaret-ellis/inventory"
TODAY = date(2026, 10, 18)


def _seeded(mdb, mctx):
    ids = seed_parent(mdb, TODAY, by=mctx.user_id)
    refresh(mdb, TODAY)
    mdb.commit()
    return ids


def _by_payer(client):
    return {s["payer"]: s for s in client.get(f"{BOOK}/suggestions").json()["suggestions"]}


def test_margarets_three_suggestions_read_like_the_mockup(margaret, mdb, mctx, client):
    ids = _seeded(mdb, mctx)
    login(client, "jr")
    got = _by_payer(client)
    assert list(got) == ["Westmark Life", "Globe Mutual", "Harbor Savings Bank"]
    w = got["Westmark Life"]
    assert (w["eyebrow"], w["title"]) == ("Suggested: income · annuity", "Westmark Life pays Margaret $410.00 a month")
    assert w["why"] == ("4 deposits into Wells Fargo ••4417 from the same payer, about a month apart. You have "
                        "a Westmark Life annuity listed as Needs checking; this may be its payout.")
    assert [e["posted_at"] for e in w["evidence"]] == ["2026-10-15", "2026-09-15", "2026-08-14", "2026-07-15"]
    assert w["evidence"][0] == {"raw": "WESTMARK LIFE ANN PMT 5521", "amount_cents": 41000, "posted_at": "2026-10-15",
                                "account": "Wells Fargo ••4417"}
    assert w["likely_ids"] == [ids["Deferred annuity"]] and w["phrase"] == "an annuity deposit"
    g = got["Globe Mutual"]
    assert (g["eyebrow"], g["title"]) == ("Suggested: insurance · Medicare supplement",
                                          "A $186.20 premium to Globe Mutual each month")
    assert g["why"] == ("4 payments from Wells Fargo ••4417, around the 15th. \"MEDSUPP\" is how Globe Mutual "
                        "names Medicare supplement plans.")
    assert g["filled_line"] == "Filled in from 4 Globe Mutual payments. Check each field, then Add item."
    assert g["prefill"]["details"] == {"type": "supplement", "amount_cents": 18620, "frequency": "monthly",
                                       "usual_day": 15, "paid_from_id": ids["Joint checking"],
                                       "match_text": "GLOBE MUTUAL MEDSUPP PREM"}
    h = got["Harbor Savings Bank"]
    assert (h["eyebrow"], h["title"]) == ("Suggested: account · Needs checking", "Interest from Harbor Savings Bank")
    assert h["why"] == ("Two interest credits, three months apart, naming a bank with no item. Margaret may have a savings "
                        "account or CD there.")
    listing = client.get(BOOK).json()["suggestions"]
    assert listing == {"count": 3, "found_in": "found in Margaret's transactions",
                       "phrases": ["an annuity deposit", "a Medicare supplement premium", "interest from Harbor Savings Bank"]}
    home = client.get(f"{BOOK}/overview").json()
    assert home["suggestions"] == {"count": 3, "found_in": "found in Margaret's transactions"}
    assert home["incoming"]["foot"] == "Not counted yet: Westmark Life deposits of $410.00 a month, waiting in Is this one of Margaret's?"


@pytest.mark.parametrize("today", [date(2026, 11, 1), date(2026, 11, 14), date(2026, 11, 16), date(2027, 2, 28)])
def test_the_suggestions_count_four_payments_whatever_day_the_seed_runs(margaret, mdb, mctx, client, today):
    """The e2e seed runs on the server's day; before the 15th the month's payment hasn't landed yet."""
    seed_parent(mdb, today, by=mctx.user_id)
    refresh(mdb, today)
    mdb.commit()
    login(client, "jr")
    got = _by_payer(client)
    assert got["Globe Mutual"]["filled_line"] == "Filled in from 4 Globe Mutual payments. Check each field, then Add item."
    assert got["Westmark Life"]["why"].startswith("4 deposits into Wells Fargo ••4417")


def test_viewers_never_see_suggestions(margaret, mdb, mctx, client):
    _seeded(mdb, mctx)
    login(client, "vee")
    assert client.get(f"{BOOK}/suggestions").json() == {"error": "This book doesn't have that."}
    assert client.get(BOOK).json()["suggestions"] is None
    home = client.get(f"{BOOK}/overview").json()
    assert home["suggestions"] is None and home["incoming"]["foot"] is None


def test_already_listed_links_confirms_and_can_be_undone(margaret, mdb, mctx, client):
    ids = _seeded(mdb, mctx)
    login(client, "jr")
    sid = _by_payer(client)["Westmark Life"]["id"]
    r = client.post(f"{BOOK}/suggestions/{sid}/link", json={"item_id": ids["Deferred annuity"], "confirm": True})
    assert r.json()["answer"] == {"id": sid, "icon": "check", "line": "Linked to Deferred annuity, now Confirmed",
                                  "sub": "Westmark Life · 4 deposits"}
    item = client.get(f"{BOOK}/items/{ids['Deferred annuity']}").json()
    assert item["status"] == "confirmed" and item["matched"]["heading"] == "Matched transactions"
    assert item["history"][0]["text"] == "linked a suggestion here"
    assert "Westmark Life" not in _by_payer(client)
    assert client.post(f"{BOOK}/suggestions/{sid}/undo").status_code == 200
    item = client.get(f"{BOOK}/items/{ids['Deferred annuity']}").json()
    assert item["status"] == "needs_checking" and item["matched"] is None
    assert "Westmark Life" in _by_payer(client)


def test_not_hers_stays_dismissed_for_that_payer(margaret, mdb, mctx, client):
    _seeded(mdb, mctx)
    login(client, "jr")
    sid = _by_payer(client)["Harbor Savings Bank"]["id"]
    assert client.post(f"{BOOK}/suggestions/{sid}/dismiss").json()["answer"] == {
        "id": sid, "icon": "x", "line": "Not Margaret's: Harbor Savings Bank",
        "sub": "Won't be suggested again. Change this under Settings → Dismissed suggestions."}
    refresh(mdb, TODAY)
    mdb.commit()
    assert "Harbor Savings Bank" not in _by_payer(client)
    dismissed = client.get(f"{BOOK}/suggestions/dismissed").json()["dismissed"]
    assert [(d["payer"], d["kind_label"], d["answered_by"]) for d in dismissed] == [("Harbor Savings Bank", "Account", "Jr")]
    row = client.get("/api/b/margaret-ellis/changes?kind=suggestions").json()["changes"][0]
    assert (row["text"], row["lines"]) == ("answered Not Margaret's to a suggestion", ["Payer: Harbor Savings Bank"])


def test_not_hers_hides_the_payers_other_open_suggestions_at_once(margaret, mdb, mctx, client):
    _seeded(mdb, mctx)
    harbor = next(s for s in mdb.scalars(select(Suggestion)) if s.payer_name == "Harbor Savings Bank")
    sibling = Suggestion(kind="income", payer_key=harbor.payer_key, payer_name=harbor.payer_name, status="open",
                         details=harbor.details, evidence=harbor.evidence, created_at=harbor.created_at,
                         updated_at=harbor.updated_at)
    mdb.add(sibling)
    mdb.commit()
    login(client, "jr")
    open_payers = [s["payer"] for s in client.get(f"{BOOK}/suggestions").json()["suggestions"]]
    assert open_payers.count("Harbor Savings Bank") == 2
    client.post(f"{BOOK}/suggestions/{harbor.id}/dismiss")
    assert "Harbor Savings Bank" not in _by_payer(client)       # no refresh in between


def test_adding_from_a_suggestion_answers_it(margaret, mdb, mctx, client):
    _seeded(mdb, mctx)
    login(client, "jr")
    g = _by_payer(client)["Globe Mutual"]
    r = client.post(f"{BOOK}/items", json={**g["prefill"], "name": "Medicare supplement", "suggestion_id": g["id"]})
    assert r.status_code == 201
    assert "Globe Mutual" not in _by_payer(client)
    added = client.get("/api/b/margaret-ellis/changes?kind=items").json()["changes"][0]
    assert added["lines"][-1] == "From a suggestion: Globe Mutual"
    again = client.post(f"{BOOK}/items", json={**g["prefill"], "name": "x", "suggestion_id": g["id"]})
    assert (again.status_code, again.json()) == (409, {"error": "That suggestion was already answered."})


def test_adding_a_matching_item_by_hand_drops_the_suggestion(margaret, mdb, mctx, client):
    _seeded(mdb, mctx)
    login(client, "jr")
    client.post(f"{BOOK}/items", json={"kind": "account", "name": "Savings", "owner": "margaret",
                                       "institution": "Harbor Savings Bank", "status": "needs_checking",
                                       "details": {"type": "savings"}})
    assert "Harbor Savings Bank" not in _by_payer(client)


def test_undoing_the_import_behind_a_suggestion_drops_it(frozen, margaret, mdb, client):
    from steward.db.models import Account, AccountType, Source
    from steward.services.accounts import manual_institution
    acct = Account(institution_id=manual_institution(mdb).id, name="Checking", type=AccountType.checking,
                   owner="margaret", source=Source.manual)
    mdb.add(acct)
    mdb.flush()
    batch = ImportBatch(account_id=acct.id, filename="old.csv", format="generic", row_count=4, imported_by=1)
    mdb.add(batch)
    mdb.flush()
    for m in (6, 7, 8, 9):
        mdb.add(Transaction(account_id=acct.id, posted_at=date(2026, m, 15), amount_cents=41000,
                            raw_description="WESTMARK LIFE ANN PMT 5521", import_batch_id=batch.id))
    refresh(mdb, date(2026, 10, 13))
    mdb.commit()
    login(client, "jr")
    assert "Westmark Life" in _by_payer(client)
    assert client.post(f"/api/b/margaret-ellis/import/batches/{batch.id}/rollback").status_code == 200
    r = client.get(f"{BOOK}/suggestions")
    assert r.status_code == 200 and r.json()["suggestions"] == []
    mdb.rollback()
    assert mdb.scalar(select(Suggestion.id)) is None
