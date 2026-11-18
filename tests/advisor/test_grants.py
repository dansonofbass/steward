"""Claude Code grants (spec 7, ruling 3): one person, one book, 30 days, stored as a hash, revocable by a manager or
the person, revoked when the person leaves the book or becomes a viewer."""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from steward.advisor import grants as G
from steward.books.service import remove_member, set_role
from steward.db.directory_models import AdvisorGrant
from tests.factories import make_person

NOW = datetime(2026, 10, 21, 17, tzinfo=timezone.utc)
TODAY = date(2026, 10, 21)


def test_a_grant_is_shown_once_and_kept_as_a_hash(ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    g, text = G.issue(ddb, book_id=ours.id, slug="ours", user_id=jr.id, by=jr.id, now=NOW)
    ddb.commit()
    assert G.GRANT_RE.match(text) and text.startswith("stg1.ours.")
    assert g.token_hash == G.token_hash(text) and text not in g.token_hash
    assert g.expires_at == NOW + timedelta(days=30)
    assert G.resolve(ddb, text, NOW + timedelta(days=29)).id == g.id
    assert G.resolve(ddb, text, NOW + timedelta(days=30)) is None          # ended
    assert G.resolve(ddb, text + "x", NOW) is None and G.resolve(ddb, None, NOW) is None
    assert G.resolve(ddb, "stg1.ours." + "A" * 43, NOW) is None             # well formed, never issued


def test_revoked_grants_resolve_to_nothing(ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    g, text = G.issue(ddb, book_id=ours.id, slug="ours", user_id=jr.id, by=jr.id, now=NOW)
    assert G.revoke(g, jr.id, NOW) is True and G.revoke(g, jr.id, NOW) is False
    ddb.commit()
    assert G.resolve(ddb, text, NOW) is None and G.state(g, NOW) == "revoked"


def test_touch_writes_at_most_once_a_minute(ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    g, _ = G.issue(ddb, book_id=ours.id, slug="ours", user_id=jr.id, by=jr.id, now=NOW)
    G.touch(g, NOW)
    G.touch(g, NOW + timedelta(seconds=30))
    assert g.last_used_at == NOW
    G.touch(g, NOW + timedelta(seconds=61))
    assert g.last_used_at == NOW + timedelta(seconds=61)


def test_rows_say_who_until_when_and_who_may_revoke(ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    sam = make_person(ddb, "sam", [(ours.id, "viewer")])
    a, _ = G.issue(ddb, book_id=ours.id, slug="ours", user_id=sam.id, by=jr.id, now=NOW - timedelta(days=2))
    b, _ = G.issue(ddb, book_id=ours.id, slug="ours", user_id=jr.id, by=jr.id, now=NOW - timedelta(days=1))
    G.revoke(b, jr.id, NOW)
    ddb.commit()
    as_sam = G.rows(ddb, ours.id, now=NOW, today=TODAY, me=sam.id, manager=False)
    assert [r["state"] for r in as_sam] == ["revoked", "active"]
    assert as_sam[1] == {"id": a.id, "person": "Sam", "issued_by": "Jr", "issued": "Oct 19", "state": "active",
                         "line": "Until Nov 18 · not used yet", "can_revoke": True}
    assert as_sam[0]["line"] == "Revoked by Jr, Oct 21" and as_sam[0]["can_revoke"] is False
    as_jr = G.rows(ddb, ours.id, now=NOW, today=TODAY, me=jr.id, manager=True)
    assert as_jr[1]["can_revoke"] is True


def test_leaving_the_book_revokes_the_persons_grants(ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    sam = make_person(ddb, "sam", [(ours.id, "viewer")])
    g, text = G.issue(ddb, book_id=ours.id, slug="ours", user_id=sam.id, by=jr.id, now=NOW)
    ddb.commit()
    remove_member(ddb, ours.id, sam.id, by=jr.id, now=NOW)
    ddb.commit()
    ddb.refresh(g)
    assert g.revoked_at is not None and g.revoked_by == jr.id and G.resolve(ddb, text, NOW) is None
    assert ddb.scalar(select(AdvisorGrant.id).where(AdvisorGrant.user_id == sam.id)) == g.id     # kept, for the list


def test_becoming_a_viewer_revokes_the_persons_grants_and_becoming_a_manager_does_not(ddb, ours):
    """A grant is for a manager (FOR_YOURSELF); a demoted one would otherwise keep reading the book through Claude
    Code with no Chat page left to see or revoke it from (viewer-scope review)."""
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    sam = make_person(ddb, "sam", [(ours.id, "manager")])
    g, text = G.issue(ddb, book_id=ours.id, slug="ours", user_id=sam.id, by=sam.id, now=NOW)
    mine, _ = G.issue(ddb, book_id=ours.id, slug="ours", user_id=jr.id, by=jr.id, now=NOW)
    ddb.commit()
    set_role(ddb, ours.id, sam.id, "viewer", by=jr.id, now=NOW)
    ddb.commit()
    ddb.refresh(g)
    ddb.refresh(mine)
    assert g.revoked_at is not None and g.revoked_by == jr.id and G.resolve(ddb, text, NOW) is None
    assert mine.revoked_at is None                                    # only the demoted person's
    set_role(ddb, ours.id, sam.id, "manager", by=jr.id, now=NOW)
    ddb.commit()
    ddb.refresh(g)
    assert g.revoked_at is not None                                   # a revoked grant stays revoked; they issue a new one


def test_a_password_reset_revokes_the_persons_grants_and_a_lockout_does_not(ddb, ours):
    """Final review M5: every path that signs a person out everywhere after a new password (reset link, a manager's
    reset, steward reset-password, a password change) goes through revoke_all_for_user. A lockout doesn't: anyone who
    knows a username can cause one."""
    import pytest

    from steward.auth import sessions, users
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    sam = make_person(ddb, "sam", [(ours.id, "viewer")])
    for_sam, sam_text = G.issue(ddb, book_id=ours.id, slug="ours", user_id=sam.id, by=jr.id, now=NOW)
    for_jr, jr_text = G.issue(ddb, book_id=ours.id, slug="ours", user_id=jr.id, by=jr.id, now=NOW)
    ddb.commit()
    sessions.revoke_all_for_user(ddb, sam.id, NOW)
    assert G.resolve(ddb, sam_text, NOW) is None and for_sam.revoked_by is None
    assert G.resolve(ddb, jr_text, NOW) is not None                       # nobody else's
    line = G.rows(ddb, ours.id, now=NOW, today=TODAY, me=jr.id, manager=True)
    assert next(r for r in line if r["id"] == for_sam.id)["line"] == "Revoked by Steward, Oct 21"
    for _ in range(users.ACCOUNT_LOCK_AFTER - 1):
        with pytest.raises(users.BadCredentials):
            users.check_password(ddb, jr, "not the password", NOW)
    assert G.resolve(ddb, jr_text, NOW) is not None                       # not locked yet
    with pytest.raises(users.BadCredentials):
        users.check_password(ddb, jr, "not the password", NOW)
    assert jr.locked_until is not None and G.resolve(ddb, jr_text, NOW) is not None
