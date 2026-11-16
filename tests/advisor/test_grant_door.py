"""The grant's door into a book (spec 7, rulings 3, 18): the same BookContext open_book gives, from a grant. Unknown,
revoked or ended grants get 401; another book's address, a person who left, or an archived book get 404; a viewer's
grant may only call routes marked viewer_ok; a session cookie opens nothing here."""
from steward import clock
from datetime import timedelta

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from steward import gateway_name
from steward.advisor import grants as G
from steward.app import create_app
from steward.books.service import create_book, remove_member
from steward.db.directory_models import AdvisorGrant, Book
from steward.deps import GATEWAY_ONLY, GRANT_REFUSED, NO_SUCH_BOOK, BookContext, grant_book_db, open_book_by_grant, viewer_ok
from tests.factories import login, make_person


@pytest.fixture
def door(settings, books, ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    vee = make_person(ddb, "vee", [(ours.id, "viewer")])
    mom = create_book(books, ddb, name="Margaret Ellis", kind="parent", owner_labels=["Margaret", "Joint"])
    assert mom.slug == "margaret-ellis"
    now = clock.now()
    _, jr_grant = G.issue(ddb, book_id=ours.id, slug="ours", user_id=jr.id, by=jr.id, now=now)
    _, vee_grant = G.issue(ddb, book_id=ours.id, slug="ours", user_id=vee.id, by=jr.id, now=now)
    ddb.commit()
    pair(settings)
    probe = APIRouter(prefix="/probe", dependencies=[Depends(open_book_by_grant)])

    @probe.get("")
    def look(ctx: BookContext = Depends(open_book_by_grant), db: Session = Depends(grant_book_db)):
        return {"user_id": ctx.user_id, "role": ctx.role, "book": ctx.book.slug}

    @probe.post("/read")
    @viewer_ok
    def read(ctx: BookContext = Depends(open_book_by_grant)):
        return {"ok": True}

    @probe.post("/write")
    def write(ctx: BookContext = Depends(open_book_by_grant)):
        return {"ok": True}
    app = create_app(settings, books)
    app.include_router(probe, prefix="/api/b/{slug}")
    with TestClient(app, base_url="https://nas.tail1234.ts.net") as c:
        yield c, {"jr": (jr, jr_grant), "vee": (vee, vee_grant)}, mom


PAIRED = "p" * 64


def pair(settings, token=PAIRED):
    settings.advisor_token_path.parent.mkdir(parents=True, exist_ok=True)
    settings.advisor_token_path.write_text(token)


def bearer(text, gateway=PAIRED):
    return {"Authorization": f"Bearer {text}", **({"X-Steward-Gateway": gateway} if gateway is not None else {})}


def test_a_grant_alone_opens_nothing_without_the_gateways_pairing_token(door, ddb, settings):
    c, g, _ = door
    jr, text = g["jr"]
    for gateway in (None, "", "q" * 64, PAIRED + "x"):
        r = c.get("/api/b/ours/probe", headers=bearer(text, gateway))
        assert (r.status_code, r.json()) == (401, {"error": gateway_name.fill(GATEWAY_ONLY)}), gateway
    assert ddb.query(AdvisorGrant).filter_by(user_id=jr.id).one().last_used_at is None      # not even touched
    settings.advisor_token_path.unlink()                                                    # not paired: nothing opens
    r = c.get("/api/b/ours/probe", headers=bearer(text))
    assert (r.status_code, r.json()) == (401, {"error": gateway_name.fill(GATEWAY_ONLY)})


def test_a_good_grant_opens_its_book_as_its_person(door, ddb):
    c, g, _ = door
    jr, text = g["jr"]
    r = c.get("/api/b/ours/probe", headers=bearer(text))
    assert r.json() == {"user_id": jr.id, "role": "manager", "book": "ours"}
    assert ddb.query(AdvisorGrant).filter_by(user_id=jr.id).one().last_used_at is not None


def test_no_unknown_revoked_or_ended_grant_gets_401(door, ddb):
    c, g, _ = door
    jr, text = g["jr"]
    gw = {"X-Steward-Gateway": PAIRED}
    for headers in (gw, bearer("stg1.ours." + "A" * 43), bearer("nonsense"), {"Authorization": text, **gw}):
        r = c.get("/api/b/ours/probe", headers=headers)
        assert (r.status_code, r.json()) == (401, {"error": GRANT_REFUSED}), headers
    row = ddb.query(AdvisorGrant).filter_by(user_id=jr.id).one()
    row.expires_at = clock.now() - timedelta(seconds=1)
    ddb.commit()
    assert c.get("/api/b/ours/probe", headers=bearer(text)).status_code == 401


def test_another_books_address_a_person_who_left_and_an_archived_book_get_404(door, ddb, ours):
    c, g, mom = door
    jr, jr_text = g["jr"]
    vee, vee_text = g["vee"]
    r = c.get("/api/b/margaret-ellis/probe", headers=bearer(jr_text))
    assert (r.status_code, r.json()) == (404, {"error": NO_SUCH_BOOK})
    ddb.query(AdvisorGrant).filter_by(user_id=vee.id).one().revoked_at = None     # as if the revoke had been missed
    from steward.db.directory_models import Membership
    ddb.delete(ddb.get(Membership, (vee.id, ours.id)))
    ddb.commit()
    assert c.get("/api/b/ours/probe", headers=bearer(vee_text)).status_code == 404
    ddb.get(Book, ours.id).archived_at = clock.now()
    ddb.commit()
    assert c.get("/api/b/ours/probe", headers=bearer(jr_text)).status_code == 404


def test_a_viewers_grant_reads_but_cannot_write(door):
    c, g, _ = door
    _, text = g["vee"]
    assert c.post("/api/b/ours/probe/read", headers=bearer(text)).json() == {"ok": True}
    assert c.post("/api/b/ours/probe/write", headers=bearer(text)).status_code == 403


def test_a_session_cookie_opens_nothing_here(door):
    c, _, _ = door
    login(c, "jr")
    r = c.get("/api/b/ours/probe")
    assert (r.status_code, r.json()) == (401, {"error": gateway_name.fill(GATEWAY_ONLY)})
    r = c.get("/api/b/ours/probe", headers={"X-Steward-Gateway": PAIRED})
    assert (r.status_code, r.json()) == (401, {"error": GRANT_REFUSED})
