from sqlalchemy import select, text
from sqlalchemy.orm import Session

from steward.db.directory_models import Membership, Session as DbSession, User
from tests.factories import make_user


def test_sign_in_lives_in_the_directory(signed_in, books, engine):
    r = signed_in.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["user"]["username"] == "jr"
    with Session(books.directory) as ddb:
        assert ddb.scalar(select(User.username)) == "jr"
        assert ddb.scalar(select(DbSession.device_label).limit(1)) is not None
        assert ddb.scalar(select(Membership.role)) == "manager"
    with engine.connect() as c:   # migration 0008 dropped ours's sign-in tables
        assert c.execute(text("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='user'")).scalar() == 0


def test_setup_names_come_from_the_people_of_the_book(signed_in, db):
    make_user(db, "sam", "sam@x.com", "Sam")
    names = signed_in.get("/api/b/ours/profile").json()["names"]
    assert names == {"jr": "JR", "spouse": "Sam", "joint": "Joint"}
