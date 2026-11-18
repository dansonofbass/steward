"""The first run (release spec 2026-11-05, section 6; claim S7). `steward setup` prints a one-time link,
<base_url>/setup#<token>. The page sends the token here in a JSON body, never in an address, so no log line can carry
it. POST /api/setup/check says whether the link still works; POST /api/setup makes the first person, a manager of
Ours, and signs them in. Both refuse once anyone exists (there is no open sign-up) and are limited per device like
the other doors that need no password."""
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from steward.api.auth import NAME, _user_out
from steward.api.body import bad, json_object, text
from steward.auth import cookies, devices, sessions, setup_link, users
from steward.auth.ratelimit import SETUP, limit
from steward.deps import directory_db, now

router = APIRouter(prefix="/api/setup")
USERNAME_RULE = "Use up to 40 letters, numbers, dots, dashes or underscores, starting with a letter or number."
EMAIL_RULE = "Enter an email address."
PASSWORD_RULE = "Enter a password."
USERNAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,39}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
LIMITED = [Depends(limit("setup", SETUP))]


def _refused(e: Exception) -> HTTPException:
    if isinstance(e, (setup_link.AlreadySetUp, users.UserExists)):
        return HTTPException(409, detail={"error": setup_link.ALREADY})
    return HTTPException(400, detail={"error": setup_link.LINK_GONE})


@router.post("/check", dependencies=LIMITED)
def check(body: dict = Depends(json_object), db: Session = Depends(directory_db)):
    try:
        setup_link.check(db, body.get("token"), now())
    except (setup_link.AlreadySetUp, setup_link.LinkGone) as e:
        raise _refused(e) from None
    return {"ok": True}


@router.post("", dependencies=LIMITED)
def make_first(request: Request, response: Response, body: dict = Depends(json_object),
               db: Session = Depends(directory_db)):
    name = text(body.get("display_name"), NAME, 80)
    username = text(body.get("username"), USERNAME_RULE, 40).lower()
    if not USERNAME_RE.fullmatch(username):
        raise bad(USERNAME_RULE)
    email = text(body.get("email"), EMAIL_RULE, 200).lower()
    if not EMAIL_RE.fullmatch(email):
        raise bad(EMAIL_RULE)
    password = body.get("password")
    if not isinstance(password, str) or not password:
        raise bad(PASSWORD_RULE)
    t = now()
    try:
        u = setup_link.claim(db, body.get("token"), t, username=username, email=email, display_name=name,
                             password=password)
    except (setup_link.AlreadySetUp, setup_link.LinkGone, users.UserExists) as e:
        raise _refused(e) from None
    except users.WeakPassword as e:
        raise HTTPException(400, detail={"error": str(e)}) from None
    label = body.get("device_label") if isinstance(body.get("device_label"), str) else ""
    label = (label or request.headers.get("user-agent", ""))[:120]
    days = request.app.state.settings.session_days
    token, _ = sessions.create_session(db, u, label, t, days)
    cookies.set_session(request, response, token, days * 86400)
    devices.signed_in(request, response, u)     # issue #7: the owner's first device is one the account knows
    return {"user": _user_out(u)}
