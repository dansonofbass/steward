from datetime import datetime, timedelta, timezone
import pytest

from steward.auth.passwords import hash_password, verify_password
from steward.auth.users import (
    BadCredentials, Locked, UserExists, check_login, create_user, find_user, set_password,
)

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


def test_hash_roundtrip():
    h = hash_password("correct horse")
    assert h.startswith("$argon2id$") and verify_password(h, "correct horse")
    assert not verify_password(h, "wrong")


def test_create_and_find_case_insensitive(ddb):
    u = create_user(ddb, "JR", "JR.Hale@Example.com", "JR", "pw-one-two-3")
    assert u.username == "jr" and u.email == "jr.hale@example.com"
    assert find_user(ddb, "jr").id == u.id
    assert find_user(ddb, "Jr.Hale@EXAMPLE.com").id == u.id
    with pytest.raises(UserExists):
        create_user(ddb, "jr", "other@x.com", "x", "pw-one-two-3")


def test_check_login_and_lockout(ddb):
    create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")
    assert check_login(ddb, "JR", "pw-one-two-3", NOW).username == "jr"
    for i in range(5):
        with pytest.raises(BadCredentials):
            check_login(ddb, "jr", "nope", NOW + timedelta(seconds=i))
    with pytest.raises(Locked) as e:
        check_login(ddb, "jr", "pw-one-two-3", NOW + timedelta(seconds=6))
    assert e.value.until == NOW + timedelta(seconds=4, minutes=15)
    # lock expires, success resets the counter
    u = check_login(ddb, "jr", "pw-one-two-3", NOW + timedelta(minutes=16))
    assert u.failed_logins == 0 and u.locked_until is None


def test_unknown_user_is_bad_credentials(ddb):
    with pytest.raises(BadCredentials):
        check_login(ddb, "ghost", "x", NOW)


def test_set_password(ddb):
    u = create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")
    set_password(ddb, u, "new-pass-word-9")
    assert check_login(ddb, "jr", "new-pass-word-9", NOW)


def test_unknown_user_computes_no_hash(ddb, monkeypatch):
    def boom(_):
        raise AssertionError("hash computed")
    monkeypatch.setattr("steward.auth.users.hash_password", boom)
    with pytest.raises(BadCredentials):
        check_login(ddb, "ghost", "x", NOW)
