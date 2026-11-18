"""Release spec 2026-11-05, section 6, claim S7: there's no open sign-up. `steward setup` prints a one-time link:
32 random bytes, kept only as a SHA-256, 30 minutes, once, compared in constant time; it makes the first person, a
manager of Ours whom nobody added (guided setup spec 1.3), and nothing once anyone exists."""
import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import select

from steward import clock
from steward.auth import setup_link as SL
from steward.auth import users
from steward.db.directory_models import Membership, MembershipChange, SetupLink, User

PW = "pw-first-person-1"


def claim(ddb, token, at=None, **kw):
    fields = {"username": "casey", "email": "casey@example.com", "display_name": "Casey", "password": PW} | kw
    return SL.claim(ddb, token, at or clock.now(), **fields)


def test_the_link_is_32_random_bytes_kept_only_as_its_sha256(ddb):
    token = SL.issue(ddb, clock.now())
    assert len(token) == 43                                   # token_urlsafe(32)
    [row] = ddb.scalars(select(SetupLink)).all()
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest() != token
    assert row.used_at is None and row.expires_at - row.created_at == timedelta(minutes=30)


def test_the_first_person_is_a_manager_of_ours_that_nobody_added(ddb, ours):
    u = claim(ddb, SL.issue(ddb, clock.now()))
    assert (u.username, u.email, u.display_name) == ("casey", "casey@example.com", "Casey")
    m = ddb.get(Membership, (u.id, ours.id))
    assert m.role == "manager" and m.created_by is None
    change = ddb.scalar(select(MembershipChange).where(MembershipChange.user_id == u.id))
    assert (change.action, change.by_user_id, change.note) == ("added", None, "steward setup")


def test_the_link_works_once(ddb):
    token = SL.issue(ddb, clock.now())
    claim(ddb, token)
    with pytest.raises(SL.AlreadySetUp):
        claim(ddb, token, username="second", email="second@example.com")
    assert ddb.scalar(select(SetupLink.used_at)) is not None


def test_the_link_lasts_30_minutes(ddb):
    t0 = clock.now()
    token = SL.issue(ddb, t0)
    SL.check(ddb, token, t0 + timedelta(minutes=29, seconds=59))
    with pytest.raises(SL.LinkGone):
        SL.check(ddb, token, t0 + timedelta(minutes=30))
    with pytest.raises(SL.LinkGone):
        claim(ddb, token, at=t0 + timedelta(minutes=31))
    assert ddb.scalar(select(User.id)) is None


def test_a_new_link_closes_the_old_one(ddb):
    old = SL.issue(ddb, clock.now())
    new = SL.issue(ddb, clock.now())
    with pytest.raises(SL.LinkGone):
        SL.check(ddb, old, clock.now())
    SL.check(ddb, new, clock.now())


def test_a_weak_password_keeps_the_link(ddb):
    token = SL.issue(ddb, clock.now())
    with pytest.raises(users.WeakPassword):
        claim(ddb, token, password="short")
    assert ddb.scalar(select(User.id)) is None
    claim(ddb, token)


def test_once_someone_exists_setup_refuses(ddb):
    token = SL.issue(ddb, clock.now())
    users.create_user(ddb, "alex", "alex@example.com", "Alex", PW)
    with pytest.raises(SL.AlreadySetUp):
        SL.issue(ddb, clock.now())
    with pytest.raises(SL.AlreadySetUp):
        SL.check(ddb, token, clock.now())
    with pytest.raises(SL.AlreadySetUp):
        claim(ddb, token)


@pytest.mark.parametrize("token", [None, "", 12, "x" * 129, "wrong-token"])
def test_a_wrong_or_odd_token_is_just_gone(ddb, token):
    SL.issue(ddb, clock.now())
    with pytest.raises(SL.LinkGone):
        SL.check(ddb, token, clock.now())


def test_every_open_link_is_compared_in_constant_time(ddb, monkeypatch):
    t = clock.now()
    for h in ("a" * 64, "b" * 64):                            # two open links (issue() would close the first)
        ddb.add(SetupLink(token_hash=h, created_at=t, expires_at=t + timedelta(minutes=30)))
    ddb.commit()
    seen = []
    real = SL.hmac.compare_digest
    monkeypatch.setattr(SL.hmac, "compare_digest", lambda a, b: seen.append(a) or real(a, b))
    with pytest.raises(SL.LinkGone):
        SL.check(ddb, "not-either", t)
    assert sorted(seen) == [b"a" * 64, b"b" * 64]


import re as _re
import stat as _stat

from typer.testing import CliRunner

from steward.cli import app as cli_app

runner = CliRunner()
LINK = _re.compile(r"https://nas\.tail1234\.ts\.net/setup#([A-Za-z0-9_-]{43})\b")


def _hash_in_directory(settings, token) -> bool:
    from sqlalchemy.orm import Session
    from steward.books.registry import open_books
    books = open_books(settings)
    try:
        with Session(books.directory) as d:
            return d.scalar(select(SetupLink.id).where(SetupLink.token_hash == hashlib.sha256(token.encode()).hexdigest(),
                                                       SetupLink.used_at.is_(None))) is not None
    finally:
        books.dispose()


def test_setup_makes_the_key_the_database_and_a_link(settings):
    r = runner.invoke(cli_app, ["setup"])
    assert r.exit_code == 0, r.output
    assert _stat.S_IMODE(settings.key_path.stat().st_mode) == 0o600 and settings.directory_path.exists()
    m = LINK.search(r.output)
    assert m and "within 30 minutes" in r.output and "It works once." in r.output
    assert _hash_in_directory(settings, m[1])
    assert settings.key_path.read_text().strip() not in r.output


def test_setup_says_the_zone_is_not_set_yet_when_nothing_chose_one(settings, monkeypatch):
    """Issue #35: with no STEWARD_TIMEZONE, no saved zone and no TZ, the welcome screen picks the zone, so setup
    doesn't print the UTC fallback as if the install had chosen it."""
    monkeypatch.delenv("STEWARD_TIMEZONE")
    monkeypatch.delenv("TZ", raising=False)
    r = runner.invoke(cli_app, ["setup"])
    assert r.exit_code == 0, r.output
    assert SL.ZONE_NOT_SET in r.output.splitlines() and "Time zone: UTC" not in r.output
    assert SL.ZONE_NOT_SET == "Time zone: not set yet. You'll choose it on the welcome screen."


def test_setup_names_a_zone_that_was_set(settings):
    r = runner.invoke(cli_app, ["setup"])
    assert "Time zone: America/Los_Angeles" in r.output.splitlines() and SL.ZONE_NOT_SET not in r.output


def _web_const(name: str) -> str:
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "web/src/screens/setup/copy.ts").read_text()
    m = _re.search(rf"^export const {name} = '((?:[^'\\]|\\.)*)';$", text, _re.M)
    assert m, name
    return m[1].replace("\\'", "'")


def test_the_setup_command_is_given_as_the_install_guide_writes_it():
    """Issue #20: the documented install has no `steward` on the host. The command the expired link and the no-link
    page give is the install guide's, and the server's and the web app's words are the same."""
    from pathlib import Path
    guide = (Path(__file__).resolve().parents[1] / "docs/quickstart/install.md").read_text()
    assert SL.SETUP_COMMAND == "docker compose run --rm steward steward setup"
    assert f"   {SL.SETUP_COMMAND}\n" in guide
    assert SL.SETUP_COMMAND in SL.LINK_GONE
    assert _web_const("SETUP_COMMAND") == SL.SETUP_COMMAND
    assert _web_const("LINK_GONE") == SL.LINK_GONE
    assert SL.SETUP_COMMAND in _web_const("NO_LINK")
    from steward.api.first_run import NEEDS_SETUP
    for words in (SL.LINK_GONE, _web_const("NO_LINK"), NEEDS_SETUP):
        assert SL.SETUP_COMMAND in words, words
        assert "steward setup" not in words.replace(SL.SETUP_COMMAND, ""), words


def test_setup_says_to_run_the_same_command_again(settings):
    r = runner.invoke(cli_app, ["setup"])
    assert "Run the same command again for a new link." in r.output and "Run steward setup" not in r.output


def test_setup_again_closes_the_first_link(settings):
    first = LINK.search(runner.invoke(cli_app, ["setup"]).output)[1]
    second = LINK.search(runner.invoke(cli_app, ["setup"]).output)[1]
    assert first != second
    assert not _hash_in_directory(settings, first) and _hash_in_directory(settings, second)


def test_setup_refuses_once_someone_exists(settings):
    assert runner.invoke(cli_app, ["init-key"]).exit_code == 0
    assert runner.invoke(cli_app, ["migrate"]).exit_code == 0
    assert runner.invoke(cli_app, ["create-user", "alex", "alex@example.com", "Alex", "--password", PW]).exit_code == 0
    r = runner.invoke(cli_app, ["setup"])
    assert r.exit_code == 1
    assert r.output.strip() == SL.ALREADY_CLI
    assert "/setup#" not in r.output


def test_setup_with_a_key_file_it_cannot_write_says_what_to_do(settings, monkeypatch, tmp_path_factory):
    blocker = tmp_path_factory.mktemp("ro") / "not-a-folder"
    blocker.write_text("")
    monkeypatch.setenv("STEWARD_KEY_FILE", str(blocker / "steward_key"))
    r = runner.invoke(cli_app, ["setup"])
    assert r.exit_code == 1 and "Run `steward keygen`" in r.output and "/setup#" not in r.output


def first(client, token, **kw):
    body = {"token": token, "username": "Casey", "display_name": "Casey", "email": "Casey@Example.com",
            "password": PW} | kw
    return client.post("/api/setup", json=body)


def test_the_link_makes_the_first_person_and_signs_them_in(client, ddb, ours):
    token = SL.issue(ddb, clock.now())
    assert client.post("/api/setup/check", json={"token": token}).json() == {"ok": True}
    r = first(client, token)
    assert r.status_code == 200 and r.json()["user"]["username"] == "casey"
    me = client.get("/api/auth/me").json()
    assert me["user"]["email"] == "casey@example.com" and [b["slug"] for b in me["books"]] == ["ours"]
    assert [b["role"] for b in me["books"]] == ["manager"]


def test_after_the_first_person_there_is_no_sign_up(client, ddb, ours):
    token = SL.issue(ddb, clock.now())
    assert first(client, token).status_code == 200
    client.cookies.clear()
    for r in (first(client, token, username="second", email="second@example.com"),
              client.post("/api/setup/check", json={"token": token})):
        assert (r.status_code, r.json()) == (409, {"error": SL.ALREADY})


def test_a_gone_link_is_said_plainly(client, ddb, ours):
    SL.issue(ddb, clock.now())
    for r in (client.post("/api/setup/check", json={"token": "wrong"}), first(client, "wrong")):
        assert (r.status_code, r.json()) == (400, {"error": SL.LINK_GONE})


@pytest.mark.parametrize("field,value,status,error", [
    ("password", "short", 400, "Use at least 12 characters."),
    ("username", "has space", 422, "Use up to 40 letters, numbers, dots, dashes or underscores, starting with a letter or number."),
    ("username", "-dash", 422, "Use up to 40 letters, numbers, dots, dashes or underscores, starting with a letter or number."),
    ("email", "not-an-email", 422, "Enter an email address."),
    ("display_name", "", 422, "Enter a name of up to 80 characters."),
])
def test_a_bad_field_keeps_the_link(client, ddb, ours, field, value, status, error):
    token = SL.issue(ddb, clock.now())
    r = first(client, token, **{field: value})
    assert (r.status_code, r.json()) == (status, {"error": error})
    assert first(client, token).status_code == 200


def test_the_setup_routes_are_limited_per_device(client, ddb, ours):
    SL.issue(ddb, clock.now())
    for _ in range(10):
        assert client.post("/api/setup/check", json={"token": "wrong"}).status_code == 400
    r = first(client, "wrong")
    assert r.status_code == 429 and r.json()["error"].startswith("Too many tries.")
