import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from steward.api.auth import require_current_password
from steward.auth import passkeys as pk, sessions
from steward.auth.ratelimit import PASSKEY_OPTIONS, limit
from steward.db.directory_models import Passkey, User
from steward.deps import current_user, directory_db, now
from steward.logs import outside_text

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth/passkeys")

EXPIRED = {"error": "That sign-in attempt expired. Try again."}
UNCHECKED = {"error": "That passkey couldn't be checked. Try again."}
UNKNOWN = {"error": "That passkey isn't registered any more. Sign in with your password and add it again."}
NOT_YOURS = {"error": "That passkey isn't on your account."}


class RegisterVerifyIn(BaseModel):
    challenge_id: str
    credential: dict
    label: str = ""


class LoginVerifyIn(BaseModel):
    challenge_id: str
    credential: dict
    device_label: str = ""


def _rp(request: Request) -> pk.RelyingParty:
    return pk.relying_party(request.app.state.settings.base_url)


def _store(request: Request) -> pk.ChallengeStore:
    return request.app.state.challenges


def _out(p: Passkey) -> dict:
    return {"id": p.id, "label": p.label, "created_at": p.created_at.isoformat()}


class RegisterOptionsIn(BaseModel):
    current_password: str


@router.post("/register/options")
def register_options(body: RegisterOptionsIn, request: Request, me: User = Depends(current_user),
                     db: Session = Depends(directory_db)):
    require_current_password(db, me, body.current_password, now())
    existing = db.scalars(select(Passkey).where(Passkey.user_id == me.id)).all()
    options_json, challenge = pk.registration_options(_rp(request), me, existing)
    return {"options": json.loads(options_json), "challenge_id": _store(request).put(challenge, "register", me.id)}


@router.post("/register/verify", status_code=201)
def register_verify(body: RegisterVerifyIn, request: Request, me: User = Depends(current_user),
                    db: Session = Depends(directory_db)):
    found = _store(request).pop(body.challenge_id, "register")
    if found is None or found[1] != me.id:
        raise HTTPException(400, detail=EXPIRED)
    try:
        cred_id, public_key, sign_count = pk.verify_registration(_rp(request), body.credential, found[0])
    except pk.VerifyFailed as e:
        log.warning("passkey registration failed for user %s: %s", me.id, outside_text(e))
        raise HTTPException(400, detail=UNCHECKED) from None
    if db.scalar(select(Passkey).where(Passkey.credential_id == cred_id)) is not None:
        raise HTTPException(409, detail={"error": "This passkey is already registered."})
    p = Passkey(user_id=me.id, credential_id=cred_id, public_key=public_key, sign_count=sign_count,
                label=pk.clean_label(body.label) or "Passkey", created_at=now())
    db.add(p)
    try:
        db.commit()
    except IntegrityError:  # a simultaneous registration of the same credential won the race
        db.rollback()
        raise HTTPException(409, detail={"error": "This passkey is already registered."}) from None
    return {"passkey": _out(p)}


@router.get("")
def list_passkeys(me: User = Depends(current_user), db: Session = Depends(directory_db)):
    rows = db.scalars(select(Passkey).where(Passkey.user_id == me.id).order_by(Passkey.created_at, Passkey.id))
    return {"passkeys": [_out(p) for p in rows]}


@router.delete("/{pid}", status_code=204)
def delete_passkey(pid: int, me: User = Depends(current_user), db: Session = Depends(directory_db)):
    p = db.get(Passkey, pid)
    if p is None or p.user_id != me.id:
        raise HTTPException(404, detail=NOT_YOURS)
    db.delete(p)
    db.commit()
    return Response(status_code=204)


@router.post("/login/options", dependencies=[Depends(limit("passkey-options", PASSKEY_OPTIONS))])
def login_options(request: Request):
    options_json, challenge = pk.authentication_options(_rp(request))
    return {"options": json.loads(options_json), "challenge_id": _store(request).put(challenge, "login", None)}


@router.post("/login/verify")
def login_verify(body: LoginVerifyIn, request: Request, response: Response, db: Session = Depends(directory_db)):
    found = _store(request).pop(body.challenge_id, "login")
    if found is None:
        raise HTTPException(400, detail=EXPIRED)
    try:
        cred_id = pk.credential_id_of(body.credential)
    except pk.VerifyFailed:
        raise HTTPException(400, detail=UNCHECKED) from None
    p = db.scalar(select(Passkey).where(Passkey.credential_id == cred_id))
    if p is None:
        raise HTTPException(401, detail=UNKNOWN)
    try:
        p.sign_count = pk.verify_authentication(_rp(request), body.credential, found[0], p)
    except pk.VerifyFailed as e:
        db.rollback()
        log.warning("passkey sign-in failed for passkey %s: %s", p.id, outside_text(e))
        raise HTTPException(400, detail=UNCHECKED) from None
    user = db.get(User, p.user_id)
    t = now()
    label = (body.device_label.strip() or request.headers.get("user-agent", ""))[:120]
    token, _ = sessions.create_session(db, user, label, t, request.app.state.settings.session_days)  # commits
    days = request.app.state.settings.session_days
    response.set_cookie(sessions.COOKIE, token, max_age=days * 86400, httponly=True, secure=True,
                        samesite="lax", path="/")
    return {"user": {"id": user.id, "username": user.username, "display_name": user.display_name}}
