"""The directory side of books (spec 2.4, 2.5, 2.7): the person's books, making a book, renaming it, and its
members. Routes about one book go through open_book like every book route, so non-members get 404 and viewers
get 403 on changes."""
from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.advisor.state import chat_on
from steward import deps
from steward.api.body import bad, json_object, one_of, text
from steward.auth import reset
from steward.auth.ratelimit import INVITE_ACCEPT, limit
from steward.books.owners import owner_options
from steward.books.registry import BookInfo, BookUnavailable, household_book_id
from steward.books.sample import SAMPLE_FAILED, SampleMissing, SampleTaken, make_sample, remove_sample, restore_sample
from steward.books.service import (
    BookRefused, InviteGone, MemberRefused, accept_invite, added_email, cancel_invite, create_book, invite,
    invite_email, may_hand_sign_in_link, pending_email, pending_rows, remove_member, set_role, welcome_kind,
)
from steward.db.directory_models import ROLES, Book, Membership, User
from steward.deps import (
    BookContext, book_db, current_user, directory_db, install_manager, now, open_book, real_book_only, viewer_ok,
)
from steward.mail import mail_ready
from steward.services import profile as profile_svc
from steward.services.profile import FINISHED, marks_out, section_states

router = APIRouter(prefix="/api/books")
invites_router = APIRouter(prefix="/api/invites")
book_router = APIRouter(prefix="/api/books/{slug}", dependencies=[Depends(open_book)])
MANAGERS_ONLY = "Only a manager of a book can add a book."
BOOK_NAME = "Enter a book name of up to 60 characters."
CHOOSE_ROLE = "Choose manager or viewer."


def book_out(request: Request, info: BookInfo, role: str, user_id: int, *, welcome: str | None = None,
             install: bool = False) -> dict:
    reg = request.app.state.books
    people = reg.people(info.id)
    reason = reg.unavailable.get(info.id)
    profile, chat = None, False
    if reason is None:
        try:
            with Session(reg.engine_for(info)) as s:
                chat = chat_on(s)
                if info.kind == "household" and role == "manager":
                    profile = marks_out(s, user_id, deps.now())
                    # Issue #30: Home opens Profile only for an unseen profile that isn't finished; once seen,
                    # nothing reads it, so it isn't worked out.
                    profile["finished"] = (None if profile["seen"]
                                           else all(x.status in FINISHED for x in section_states(s)))
        except BookUnavailable as e:
            reason = str(e)
    return {"slug": info.slug, "name": info.name, "kind": info.kind, "role": role, "available": reason is None,
            "reason": reason if role == "manager" else None,   # spec 8: the reason, for managers
            "owners": [{"key": o.key, "label": o.label} for o in owner_options(info.kind, info.owner_names, people)],
            "profile": profile, "chat": chat, "welcome": welcome, "sample": info.sample, "install": install}


def books_for(request: Request, ddb: Session, user_id: int) -> list[dict]:
    rows = ddb.execute(select(Book, Membership).join(Membership, Membership.book_id == Book.id)
                       .where(Membership.user_id == user_id, Book.archived_at.is_(None)).order_by(Book.id)).all()
    hh = household_book_id(ddb)
    infos = [(BookInfo.of(b), m.role, welcome_kind(b, m, hh, user_id), b.id == hh) for b, m in rows]
    ddb.commit()   # end the directory transaction before opening the books
    return [book_out(request, info, role, user_id, welcome=welcome, install=install)
            for info, role, welcome, install in infos]


def _member_out(u: User, role: str, *, email: bool = True) -> dict:
    out = {"user_id": u.id, "username": u.username, "display_name": u.display_name, "role": role}
    return out | {"email": u.email} if email else out


@router.get("")
def my_books(request: Request, me: User = Depends(current_user), ddb: Session = Depends(directory_db)):
    return {"books": books_for(request, ddb, me.id)}


@router.post("", status_code=201)
def add_book(request: Request, body: dict = Depends(json_object), me: User = Depends(current_user),
             ddb: Session = Depends(directory_db)):
    manages = ddb.scalar(select(Membership.book_id).join(Book, Book.id == Membership.book_id)
                         .where(Membership.user_id == me.id, Membership.role == "manager", Book.archived_at.is_(None))
                         .limit(1))
    if manages is None:
        raise bad(MANAGERS_ONLY, 403)
    try:   # never allow_household: a household book made here would make its maker an install manager
        info = create_book(request.app.state.books, ddb, name=body.get("name"), kind=body.get("kind"),
                           owner_labels=body.get("owner_names"), by=me.id, now=now())
    except BookRefused as e:
        raise bad(str(e)) from None
    return {"book": book_out(request, info, "manager", me.id)}


@router.post("/sample")
def add_sample(request: Request, me: User = Depends(install_manager), ddb: Session = Depends(directory_db)):
    """Look around with a sample household (guided setup spec 8): one per person, 201 when made now, else the one that
    exists. A route of its own on the books router, which is included before book_router, so it is never a slug."""
    try:
        info, made = make_sample(request.app.state.books, ddb, me.id, deps.today(), now())
    except RuntimeError:
        raise bad(SAMPLE_FAILED, 503) from None
    return JSONResponse({"book": book_out(request, info, "manager", me.id)}, status_code=201 if made else 200)


@router.delete("/sample")
def remove_the_sample(request: Request, me: User = Depends(current_user), ddb: Session = Depends(directory_db)):
    try:
        info = remove_sample(request.app.state.books, ddb, me.id, now())
    except SampleMissing as e:
        raise bad(str(e), 404) from None
    household = household_book_id(ddb)
    slug = ddb.scalar(select(Book.slug).join(Membership, Membership.book_id == Book.id)
                      .where(Book.id == household, Membership.user_id == me.id)) if household is not None else None
    ddb.commit()
    return {"removed": info.slug, "household": slug}


@router.post("/sample/restore")
def restore_the_sample(request: Request, me: User = Depends(current_user), ddb: Session = Depends(directory_db)):
    try:
        info = restore_sample(request.app.state.books, ddb, me.id, now())
    except SampleMissing as e:
        raise bad(str(e), 404) from None
    except SampleTaken as e:
        raise bad(str(e), 409) from None
    return {"book": book_out(request, info, "manager", me.id)}


@book_router.patch("")
def rename(request: Request, body: dict = Depends(json_object), ctx: BookContext = Depends(open_book),
           ddb: Session = Depends(directory_db)):
    name = text(body.get("name"), BOOK_NAME, 60)
    ddb.get(Book, ctx.book.id).name = name
    ddb.commit()
    book = ddb.get(Book, ctx.book.id)
    info = BookInfo.of(book)
    m = ddb.get(Membership, (ctx.user_id, ctx.book.id))
    hh = household_book_id(ddb)
    return {"book": book_out(request, info, ctx.role, ctx.user_id, welcome=welcome_kind(book, m, hh, ctx.user_id),
                             install=book.id == hh)}


@book_router.post("/welcome")
@viewer_ok
def mark_welcome(ctx: BookContext = Depends(open_book), me: User = Depends(current_user),
                 ddb: Session = Depends(directory_db), db: Session = Depends(book_db)):
    """Finish or skip: mark this person's welcome in this book, once. For a household manager the first visit counts
    as seen too, so Go to Home lands on Home (plan D6)."""
    m = ddb.get(Membership, (ctx.user_id, ctx.book.id))
    m.welcome_seen_at = m.welcome_seen_at or now()
    ddb.commit()
    if ctx.book.kind == "household" and ctx.is_manager:
        profile_svc.mark(db, me.id, now(), seen=True)
        db.commit()
    return {"welcome": None}


@book_router.get("/members")
def members(ctx: BookContext = Depends(open_book), ddb: Session = Depends(directory_db)):
    rows = ddb.execute(select(User, Membership.role).join(Membership, Membership.user_id == User.id)
                       .where(Membership.book_id == ctx.book.id).order_by(User.id)).all()
    if ctx.role != "manager":   # a viewer sees who is in the book; emails and invites are for its managers
        return {"members": [_member_out(u, role, email=False) for u, role in rows]}
    # managers also see who has not joined yet, as "Invited" rows only
    return {"members": [_member_out(u, role) for u, role in rows] + pending_rows(ddb, ctx.book.id)}


@book_router.post("/members", status_code=201, dependencies=[Depends(real_book_only)])
def add_member(request: Request, background: BackgroundTasks, body: dict = Depends(json_object),
               ctx: BookContext = Depends(open_book), me: User = Depends(current_user),
               ddb: Session = Depends(directory_db)):
    role = one_of(body.get("role", "viewer"), ROLES, CHOOSE_ROLE)
    try:
        res = invite(ddb, ctx.book.id, body.get("email"), body.get("display_name"), role, by=me.id, now=now())
    except MemberRefused as e:
        raise bad(str(e), e.status) from None
    ddb.commit()
    base = request.app.state.settings.base_url
    typed = body["email"].strip()
    if res.kind == "added":
        subject, message = added_email(base, me.display_name, ctx.book.name, ctx.book.slug, role)
        out = {"member": _member_out(res.user, role), "invited": False}
    else:
        # A new account and an existing one answer alike: the typed email and nothing about who they are. The password
        # link is asked about again here, where it leaves in an email or in send_yourself (SEC-1).
        sign_in = res.sign_in if res.sign_in and may_hand_sign_in_link(ddb, me.id, res.user, now()) else None
        subject, message = (invite_email(base, me.display_name, ctx.book.name, res.user, role, sign_in, res.token)
                            if sign_in
                            else pending_email(base, me.display_name, ctx.book.name, role, res.token))
        out = {"member": {"email": typed, "role": role, "status": "Invited"}, "invited": True}
    # Someone already in a book the inviter manages is added at once: no link to hand over and nothing to report as
    # unsent (the courtesy notice is a no-op in safe_send while mail isn't ready).
    if res.kind != "added" and not mail_ready(request.app.state.mailer):   # D9: nothing queued, text never logged
        household = household_book_id(ddb)
        installs = household is not None and ddb.scalar(select(Membership.user_id).where(
            Membership.user_id == me.id, Membership.book_id == household, Membership.role == "manager")) is not None
        ddb.commit()
        return out | ({"send_yourself": message} if installs else {"mail_off": True})
    background.add_task(reset.safe_send, request.app.state.mailer, res.email, subject, message)
    return out


@book_router.delete("/invites/{invite_id}", status_code=204)
def cancel(invite_id: str, ctx: BookContext = Depends(open_book), me: User = Depends(current_user),
           ddb: Session = Depends(directory_db)):
    try:
        cancel_invite(ddb, ctx.book.id, invite_id, by=me.id, now=now())
    except MemberRefused as e:
        raise bad(str(e), e.status) from None
    ddb.commit()
    return Response(status_code=204)


@invites_router.post("/accept", dependencies=[Depends(limit("invite", INVITE_ACCEPT))])
def accept(body: dict = Depends(json_object), me: User = Depends(current_user), ddb: Session = Depends(directory_db)):
    try:
        book = accept_invite(ddb, me.id, body.get("token"), now=now())
    except InviteGone as e:
        raise bad(str(e), 404) from None
    ddb.commit()
    return {"book": {"slug": book.slug, "name": book.name}}


@book_router.patch("/members/{user_id}")
def change_role(user_id: int, body: dict = Depends(json_object), ctx: BookContext = Depends(open_book),
                me: User = Depends(current_user), ddb: Session = Depends(directory_db)):
    role = one_of(body.get("role"), ROLES, CHOOSE_ROLE)
    try:
        m = set_role(ddb, ctx.book.id, user_id, role, by=me.id, now=now())
    except MemberRefused as e:
        raise bad(str(e), e.status) from None
    ddb.commit()
    return {"member": _member_out(ddb.get(User, user_id), m.role)}


@book_router.delete("/members/{user_id}", status_code=204)
def remove(user_id: int, ctx: BookContext = Depends(open_book), me: User = Depends(current_user),
           ddb: Session = Depends(directory_db)):
    try:
        remove_member(ddb, ctx.book.id, user_id, by=me.id, now=now())
    except MemberRefused as e:
        raise bad(str(e), e.status) from None
    ddb.commit()
    return Response(status_code=204)
