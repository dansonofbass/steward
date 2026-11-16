"""Release spec 2026-11-05, section 6: a vault that runs as prod never keeps a demo sign-in. seed-demo already refuses
in prod; this catches a demo vault copied into prod, including one an older demo seeded (RETIRED_DEMO_LOGINS). One
Argon2 check at start per demo login, current or retired, whose username is in the directory. Only a matching
password refuses: a real account with a demo username starts as usual."""
from sqlalchemy.orm import Session

from steward.auth.passwords import verify_password
from steward.auth.users import find_user
from steward.demo import DEMO_LOGINS, RETIRED_DEMO_LOGINS

CHECKED = tuple((username, password) for username, _email, _name, password in DEMO_LOGINS) + RETIRED_DEMO_LOGINS

REFUSED = ("{username} still signs in with the demo password, and STEWARD_ENV is prod. Run `steward reset-password "
           "{username}`, or use a throwaway vault with STEWARD_ENV=test.")


def demo_login_left(ddb: Session) -> str | None:
    for username, password in CHECKED:
        u = find_user(ddb, username)
        if u is not None and verify_password(u.password_hash, password):
            return u.username
    return None
