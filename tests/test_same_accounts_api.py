"""The same-account routes (spec, API): household only; viewers read and managers answer; the shapes the card and the
sheet read; Undo through the same POST /undo/{token}."""
from datetime import date, timedelta

from sqlalchemy import select

from steward.api.body import NOT_UNDERSTOOD
from steward.db.models import Account, AccountType, HeldFeed, SameAccountAnswer
from steward.deps import NOT_IN_THIS_BOOK, VIEWER_COPY
from tests.factories import login, make_account, make_person
from tests.same_account_fixtures import (AT_NEW, BALANCE, JOINT_DAYS, LATER, bank, booked, held_copy, in_book_pair,
                                         jr_account)

B = "/api/b/ours"
WIRE = (date(2026, 10, 27), -40_00, "WIRE FEE")
ANSWERED = {"error": "That question was already answered."}


def fresh(db):
    db.rollback()
    db.expire_all()


def test_the_list_has_both_kinds_newest_first_in_the_cards_terms(signed_in, db):
    keep = jr_account(db)
    h = held_copy(db, keep)
    k, o = in_book_pair(db, keys=("kim", "lee"), name="Kids 529")
    q = SameAccountAnswer(account_id=k.id, other_account_id=o.id, answer="open", match_count=61,
                          created_at=LATER - timedelta(days=1))
    db.add(q)
    db.commit()
    body = signed_in.get(f"{B}/same-accounts").json()
    assert [x["id"] for x in body["questions"]] == [f"held-{h.id}", f"pair-{q.id}"]
    assert body["questions"][0] == {
        "id": f"held-{h.id}", "kind": "held", "name": "Joint Taxable", "bank": "Betterment", "balance_cents": BALANCE,
        "candidate_id": keep.id, "candidate_name": "Joint Taxable", "candidate_bank": "Betterment",
        "candidate_balance_cents": BALANCE, "matches": 5, "same_balance": True, "since": LATER.isoformat()}
    pair = body["questions"][1]
    assert (pair["kind"], pair["name"], pair["candidate_id"], pair["candidate_name"], pair["matches"]) == (
        "in_book", "Kids 529", k.id, "Kids 529", 5)        # counted now, not the 61 stored when it was raised


def test_merging_a_held_feed_says_what_happened_and_undo_puts_it_back(signed_in, db):
    keep = jr_account(db)
    h = held_copy(db, keep, days=JOINT_DAYS + [WIRE])
    r = signed_in.post(f"{B}/same-accounts/held-{h.id}/merge")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["merged"] == {"kept": {"id": keep.id, "name": "Joint Taxable"}, "dropped": 5, "kept_new": 1}
    assert body["undo"]
    assert signed_in.get(f"{B}/same-accounts").json()["questions"] == []
    again = signed_in.post(f"{B}/same-accounts/held-{h.id}/merge")
    assert (again.status_code, again.json()) == (404, ANSWERED)
    u = signed_in.post(f"{B}/undo/{body['undo']}")
    assert (u.status_code, u.json()) == (200, {"undone": 1, "transaction": None})
    fresh(db)
    assert db.get(HeldFeed, h.id) is not None


def test_merging_a_pair_keeps_the_older_account(signed_in, db):
    keep, other = in_book_pair(db)
    other.type = keep.type                            # the question's two accounts are of one type
    q = SameAccountAnswer(account_id=keep.id, other_account_id=other.id, answer="open", match_count=5,
                          created_at=LATER)
    db.add(q)
    db.commit()
    oid = other.id
    r = signed_in.post(f"{B}/same-accounts/pair-{q.id}/merge")
    assert r.status_code == 200 and r.json()["merged"] == {"kept": {"id": keep.id, "name": "Joint Taxable"},
                                                           "dropped": 5, "kept_new": 0}
    fresh(db)
    assert db.get(Account, oid) is None


def test_merging_a_stale_pair_question_refuses_like_merge_into(signed_in, db):
    keep, other = in_book_pair(db)
    q = SameAccountAnswer(account_id=keep.id, other_account_id=other.id, answer="open", match_count=5,
                          created_at=LATER)
    db.add(q)
    db.commit()
    other.is_active = False                              # archived after the one-time check raised the question
    db.commit()
    kid, oid = keep.id, other.id
    r = signed_in.post(f"{B}/same-accounts/pair-{q.id}/merge")
    assert (r.status_code, r.json()) == (422, {"error": "Choose an account that's still open."})
    fresh(db)
    assert db.get(Account, kid) is not None and db.get(Account, oid) is not None


def test_the_card_merges_a_pair_whose_newer_account_has_no_type_yet(signed_in, db):
    """Engineering choice 12: the card's merges skip the type check; Merge into… still makes it."""
    keep, other = in_book_pair(db)
    other.type = keep.type
    q = SameAccountAnswer(account_id=keep.id, other_account_id=other.id, answer="open", match_count=5,
                          created_at=LATER)
    db.add(q)
    db.commit()
    other.type = AccountType.unknown                     # Type not set yet, after the one-time check raised it
    db.commit()
    kid, oid = keep.id, other.id
    r = signed_in.post(f"{B}/same-accounts/pair-{q.id}/merge")
    assert r.status_code == 200, r.text
    assert r.json()["merged"]["kept"] == {"id": kid, "name": "Joint Taxable"}
    fresh(db)
    assert db.get(Account, kid) is not None and db.get(Account, oid) is None


def test_theyre_different_answers_with_an_undo(signed_in, db):
    keep = jr_account(db)
    h = held_copy(db, keep)
    r = signed_in.post(f"{B}/same-accounts/held-{h.id}/different")
    assert r.status_code == 200 and set(r.json()) == {"undo"}
    fresh(db)
    assert db.scalar(select(Account).where(Account.external_id == "sfin:sam-joint")) is not None
    assert signed_in.post(f"{B}/undo/{r.json()['undo']}").status_code == 200
    fresh(db)
    assert db.get(HeldFeed, h.id) is not None
    assert db.scalar(select(Account).where(Account.external_id == "sfin:sam-joint")) is None


def test_merge_into_previews_then_merges_into_the_chosen_account(signed_in, db):
    keep, other = in_book_pair(db, other_days=JOINT_DAYS + [WIRE])
    other.type = AccountType.brokerage_taxable
    db.commit()
    kid = keep.id
    r = signed_in.get(f"{B}/accounts/{kid}/merge-preview?into={other.id}")    # the newer one is chosen: it stays
    assert r.json() == {"merged": {"kept": {"id": other.id, "name": "Joint Taxable"}, "dropped": 5, "kept_new": 0}}
    r = signed_in.post(f"{B}/accounts/{kid}/merge-into", json={"into": other.id})
    assert r.status_code == 200 and r.json()["merged"]["kept"]["id"] == other.id and r.json()["undo"]
    fresh(db)
    assert db.get(Account, kid) is None


def test_merge_into_merges_an_account_whose_type_isnt_set_yet_and_the_kept_type_stands(signed_in, db):
    keep, other = in_book_pair(db, other_days=JOINT_DAYS + [WIRE])     # the newer one is still "Type not set yet"
    kid, oid = keep.id, other.id
    r = signed_in.get(f"{B}/accounts/{oid}/merge-preview?into={kid}")
    assert r.json() == {"merged": {"kept": {"id": kid, "name": "Joint Taxable"}, "dropped": 5, "kept_new": 1}}
    r = signed_in.post(f"{B}/accounts/{oid}/merge-into", json={"into": kid})
    assert r.status_code == 200 and r.json()["merged"]["kept"]["id"] == kid
    fresh(db)
    assert db.get(Account, oid) is None and db.get(Account, kid).type == AccountType.brokerage_taxable


def test_merge_into_says_what_it_cannot_do(signed_in, db):
    keep, other = in_book_pair(db)                    # the newer one is still "Type not set yet"
    house = make_account(db, "House", type="property")
    ira = booked(db, "kim", bank(db, "kim"), AT_NEW, name="Roth IRA", type_=AccountType.roth_ira)
    for path, status, error in (
            (f"/accounts/{other.id}/merge-preview?into={other.id}", 422, "Choose another account to merge into."),
            (f"/accounts/{keep.id}/merge-preview?into={other.id}", 422, "Choose an account of the same type."),
            (f"/accounts/{ira.id}/merge-preview?into={keep.id}", 422, "Choose an account of the same type."),
            (f"/accounts/{house.id}/merge-preview?into={keep.id}", 422,
             "Only two accounts that come from a bank can be merged here."),
            (f"/accounts/{other.id}/merge-preview?into=999", 404, "No such account."),
            (f"/accounts/{other.id}/merge-preview?into=abc", 422, NOT_UNDERSTOOD),
            (f"/accounts/{other.id}/merge-preview", 422, NOT_UNDERSTOOD)):
        r = signed_in.get(B + path)
        assert (r.status_code, r.json()) == (status, {"error": error}), path
    for body in ({"into": "1"}, {"into": True}, {}):
        r = signed_in.post(f"{B}/accounts/{other.id}/merge-into", json=body)
        assert (r.status_code, r.json()) == (422, {"error": NOT_UNDERSTOOD}), body
    for bad in ("held-999", "pair-1", "nope", "held-²", "held-1-2"):
        for action in ("merge", "different"):
            r = signed_in.post(f"{B}/same-accounts/{bad}/{action}")
            assert (r.status_code, r.json()) == (404, ANSWERED), (bad, action)


def test_a_viewer_sees_the_questions_but_cannot_answer(client, db, ddb, ours):
    keep = jr_account(db)
    h = held_copy(db, keep)
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "vee")
    assert client.get(f"{B}/same-accounts").status_code == 200
    for path, body in ((f"/same-accounts/held-{h.id}/merge", None), (f"/same-accounts/held-{h.id}/different", None),
                       (f"/accounts/{keep.id}/merge-into", {"into": keep.id})):
        r = client.post(B + path, json=body)
        assert (r.status_code, r.json()) == (403, {"error": VIEWER_COPY}), path


def test_parent_books_have_no_same_account_routes(client, margaret):
    login(client, "jr")
    for method, path in (("GET", "/same-accounts"), ("POST", "/same-accounts/held-1/merge"),
                         ("POST", "/same-accounts/held-1/different"), ("GET", "/accounts/1/merge-preview?into=2"),
                         ("POST", "/accounts/1/merge-into")):
        r = client.request(method, f"/api/b/margaret-ellis{path}", json={"into": 2})
        assert (r.status_code, r.json()) == (404, {"error": NOT_IN_THIS_BOOK}), path


def test_the_routes_need_sign_in(client):
    assert client.get(f"{B}/same-accounts").status_code == 401
