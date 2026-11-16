"""Fix PR 16b: a link that chooses a password reaches only the account's owner, and recovery starts clean.

SEC-1: an invite handed a household manager a password link for an existing account that had never signed in, in a
book that manager does not manage. SEC-4: a passkey added by someone who learned the password outlived the reset.

The guard at the bottom keeps the class from coming back: every place that mints a password link, reads one out of an
invite, or sets a password is listed here, and a new one fails until it is listed with its rule."""
import ast
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from steward import clock
from steward.app import create_app
from steward.books.service import create_book
from steward.db.directory_models import Passkey, PasswordReset, PendingInvite, User
from steward.mail import FakeMailer
from tests.factories import login, make_person

SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.fixture
def mail_off(settings, books):
    app = create_app(settings, books, mailer=FakeMailer(configured=False))
    with TestClient(app, base_url="https://nas.tail1234.ts.net") as c:
        yield c, app


def _invite(c, email, slug="ours", name="Typed Name"):
    r = c.post(f"/api/books/{slug}/members", json={"email": email, "display_name": name, "role": "viewer"})
    assert r.status_code == 201, r.text
    return r.json()


def _links(ddb, user_id):
    ddb.rollback()
    return ddb.scalars(select(PasswordReset).where(PasswordReset.user_id == user_id)).all()


# SEC-1 ---------------------------------------------------------------------------------------------------------------

def test_an_existing_account_that_never_signed_in_gets_no_password_link_with_email_off(mail_off, books, ddb, ours):
    """The reviewer's scenario: the server's operator made an account for a sibling in a parent book the household's
    manager isn't in. Before the sibling signs in, that manager invites the address to the household book."""
    c, app = mail_off
    make_person(ddb, "jr", [(ours.id, "manager")])
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret"])
    sis = make_person(ddb, "sis", [(mom.id, "manager")])        # as `steward create-user ... --book mom`
    login(c, "jr")
    body = _invite(c, "sis@x.com")
    message = body["send_yourself"]
    assert "/invite?token=" in message and "/reset?token=" not in message
    assert _links(ddb, sis.id) == []
    assert ddb.scalar(select(PendingInvite).where(PendingInvite.user_id == sis.id)) is not None


def test_with_email_on_an_existing_account_gets_the_plain_invite(client, app, books, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    other = create_book(books, ddb, name="Other", kind="parent", owner_labels=["Pat"])
    quiet = make_person(ddb, "quiet", [(other.id, "viewer")])
    login(client, "jr")
    _invite(client, "quiet@x.com")
    to, _subject, body = app.state.mailer.sent[-1]
    assert to == "quiet@x.com" and "/invite?token=" in body and "/reset?token=" not in body
    assert _links(ddb, quiet.id) == []


def test_a_new_address_still_gets_its_link_and_a_repeat_from_the_same_book_too(mail_off, ddb, ours):
    c, app = mail_off
    make_person(ddb, "jr", [(ours.id, "manager")])
    make_person(ddb, "sam", [(ours.id, "manager")])
    login(c, "jr")
    assert "/reset?token=" in _invite(c, "new@example.com")["send_yourself"]
    login(c, "sam")                                   # another manager of the same book sends it again
    assert "/reset?token=" in _invite(c, "new@example.com")["send_yourself"]


def test_an_invited_account_with_an_open_invite_elsewhere_gets_no_link_from_another_manager(mail_off, books, ddb, ours):
    """An invite's own account, but another manager's invite is waiting in a book the household manager doesn't
    manage: handing that manager a password link would let them take the account before its owner does."""
    c, app = mail_off
    make_person(ddb, "jr", [(ours.id, "manager")])
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret"])
    make_person(ddb, "momsmgr", [(mom.id, "manager")])
    login(c, "momsmgr")
    assert _invite(c, "new@example.com", slug="mom").get("mail_off") is True
    login(c, "jr")
    message = _invite(c, "new@example.com")["send_yourself"]
    assert "/invite?token=" in message and "/reset?token=" not in message
    person = ddb.scalar(select(User).where(User.email == "new@example.com"))
    assert len(_links(ddb, person.id)) == 1           # only the one momsmgr's invite made, which went nowhere


def test_the_route_never_hands_out_a_link_the_rule_refuses(mail_off, monkeypatch, books, ddb, ours):
    """The second wall: even if invite() returned a link for a real account, send_yourself leaves it out."""
    from steward.api import books as books_api
    from steward.books import service
    c, app = mail_off
    make_person(ddb, "jr", [(ours.id, "manager")])
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret"])
    make_person(ddb, "sis", [(mom.id, "manager")])
    real = books_api.invite

    def leaky(ddb_, book_id, email, name, role, *, by, now=None):
        res = real(ddb_, book_id, email, name, role, by=by, now=now)
        res.sign_in = service._sign_in_link(ddb_, res.user.id, clock.now())
        return res

    monkeypatch.setattr(books_api, "invite", leaky)
    login(c, "jr")
    assert "/reset?token=" not in _invite(c, "sis@x.com")["send_yourself"]


# SEC-4 ---------------------------------------------------------------------------------------------------------------

def _passkey(ddb, user_id, cid=b"theirs"):
    ddb.add(Passkey(user_id=user_id, credential_id=cid, public_key=b"pub", sign_count=0, label="p",
                    created_at=clock.now()))
    ddb.commit()


def test_an_emailed_reset_link_removes_the_accounts_passkeys(client, app, ddb, ours):
    """Someone who learned the password added a passkey; the owner recovers through Forgot your password."""
    me = make_person(ddb, "jr", [(ours.id, "manager")])
    other = make_person(ddb, "sam", [(ours.id, "manager")])
    _passkey(ddb, me.id, b"added-by-someone-else")
    _passkey(ddb, other.id, b"sams")
    client.post("/api/auth/forgot", json={"username": "jr"})
    token = re.search(r"token=(\S+)", app.state.mailer.sent[-1][2]).group(1)
    assert client.post("/api/auth/reset", json={"token": token, "password": "brand-new-pass-1"}).status_code == 200
    ddb.rollback()
    assert [p.credential_id for p in ddb.scalars(select(Passkey))] == [b"sams"]


def test_steward_reset_password_removes_passkeys_and_says_so(settings):
    from steward.auth import users
    from steward.books.registry import open_books
    from steward.cli import app as cli
    runner = CliRunner()
    runner.invoke(cli, ["init-key"])
    runner.invoke(cli, ["migrate"])
    runner.invoke(cli, ["create-user", "jr", "jr@x.com", "JR", "--password", "pw-one-two-3"])
    books = open_books(settings)
    try:
        with Session(books.directory) as db:
            _passkey(db, users.find_user(db, "jr").id)
        r = runner.invoke(cli, ["reset-password", "jr", "--password", "new-pass-word-9"])
        assert r.exit_code == 0, r.output
        assert "Password updated. Signed out everywhere, and 1 passkey removed." in r.output
        with Session(books.directory) as db:
            assert db.scalars(select(Passkey)).all() == []
    finally:
        books.dispose()


# The guard -----------------------------------------------------------------------------------------------------------

# Every function that makes a password link (a PasswordReset row, or the invite's helper), with where the link goes.
MINTS = {
    ("steward/auth/reset.py", "request_reset"): "emailed to the account's own address only (test_reset.py)",
    ("steward/books/service.py", "_sign_in_link"): "the invite's link; only invite() calls it, behind the rule",
}
# Who may call the invite's link maker, and who may read the link back out of an InviteResult. Each must ask
# may_hand_sign_in_link in the same function, so the rule is checked where the link is made and where it leaves.
SIGN_IN_LINK_CALLERS = {("steward/books/service.py", "invite")}
SIGN_IN_READERS = {("steward/api/books.py", "add_member")}
RULE = "may_hand_sign_in_link"

# Every function that sets a password. Recovery must start clean (start_clean: other links closed, passkeys deleted,
# signed out everywhere, grants ended); the others say why not.
RECOVERY = {
    ("steward/auth/reset.py", "consume"),          # the emailed link, and an invite's first password
    ("steward/api/auth.py", "reset_other"),        # a manager who manages every book of theirs
    ("steward/cli.py", "reset_password"),          # the operator's last resort
}
NOT_RECOVERY = {
    ("steward/api/auth.py", "change_password"): "signed in with the current password; the passkeys are listed on the "
                                                "same screen and the done line says they still sign in",
}
# Every function that hashes a password itself, outside set_password.
HASHES = {
    ("steward/auth/users.py", "set_password"): "the one setter the lists above call",
    ("steward/auth/users.py", "create_user"): "a new account, with nothing to clear",
    ("steward/auth/users.py", "<module>"): "the dummy hash that keeps an unknown username's timing even",
    ("steward/books/service.py", "invite"): "an invite's own account, with a password nobody knows",
}


def _sites(pred) -> dict[tuple[str, str], ast.AST]:
    """{(file, innermost function): that function} for every node in src/ that pred accepts."""
    out = {}

    def visit(node, rel, fn):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn = node
        if pred(node):
            out[(rel, fn.name if fn is not None else "<module>")] = fn
        for child in ast.iter_child_nodes(node):
            visit(child, rel, fn)

    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        visit(ast.parse(path.read_text(), filename=rel), rel, None)
    return out


def _name(call: ast.Call) -> str:
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def _called(fn) -> set[str]:
    return {_name(n) for n in ast.walk(fn) if isinstance(n, ast.Call)}


def _calls(name):
    return lambda n: isinstance(n, ast.Call) and _name(n) == name


def test_every_password_link_is_made_in_a_listed_place():
    sites = set(_sites(_calls("PasswordReset")))
    assert sites == set(MINTS), f"a password link is made somewhere unlisted, or a listed place is gone: {sites ^ set(MINTS)}"


def test_the_invites_link_is_made_and_handed_out_only_behind_the_rule():
    callers = _sites(_calls("_sign_in_link"))
    readers = _sites(lambda n: isinstance(n, ast.Attribute) and n.attr == "sign_in" and isinstance(n.ctx, ast.Load))
    assert set(callers) == SIGN_IN_LINK_CALLERS, set(callers) ^ SIGN_IN_LINK_CALLERS
    assert set(readers) == SIGN_IN_READERS, set(readers) ^ SIGN_IN_READERS
    for key, fn in {**callers, **readers}.items():
        assert RULE in _called(fn), f"{key} makes or hands out a password link without asking {RULE}"


def test_every_password_set_is_listed_and_recovery_starts_clean():
    sites = _sites(_calls("set_password"))
    listed = RECOVERY | set(NOT_RECOVERY)
    assert set(sites) == listed, f"a password is set somewhere unlisted, or a listed place is gone: {set(sites) ^ listed}"
    for key in RECOVERY:
        assert "start_clean" in _called(sites[key]), f"{key} sets a password through recovery without start_clean"
    hashed = set(_sites(_calls("hash_password")))
    assert hashed == set(HASHES), f"a password is hashed somewhere unlisted, or a listed place is gone: {hashed ^ set(HASHES)}"
