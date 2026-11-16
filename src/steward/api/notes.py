"""Transaction notes (phase 12 decision 18): who wrote it and when, several per transaction, newest last. Managers
write and delete their own; viewers read (open_book refuses their writes). The body never goes into the change record
and never to Claude."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import deps
from steward.api.body import json_object, text
from steward.db.models import NOTE_MAX, Transaction, TransactionNote
from steward.deps import BookContext, book_db, open_book, recorded
from steward.inventory.changes import about, record
from steward.services.undo import remember_removed_note

router = APIRouter(prefix="/transactions/{tid}/notes", dependencies=[Depends(open_book)])
NOTE_RULE = "A note is 1 to 1,000 characters."
NOT_YOUR_NOTE = "Only the person who wrote a note can remove it."


def note_out(n: TransactionNote) -> dict:
    return {"id": n.id, "author_id": n.author_id, "author_name": n.author_name, "body": n.body,
            "created_at": n.created_at.isoformat()}


def _txn_or_404(db: Session, tid: int) -> Transaction:
    t = db.get(Transaction, tid)
    if t is None:
        raise HTTPException(404, detail={"error": "No such transaction."})
    return t


@router.get("")
def list_notes(tid: int, db: Session = Depends(book_db)):
    _txn_or_404(db, tid)
    rows = db.scalars(select(TransactionNote).where(TransactionNote.transaction_id == tid)
                      .order_by(TransactionNote.created_at, TransactionNote.id))
    return {"notes": [note_out(n) for n in rows]}


@router.post("", status_code=201)
@recorded
def add_note(tid: int, body: dict = Depends(json_object), db: Session = Depends(book_db),
             ctx: BookContext = Depends(open_book)):
    t = _txn_or_404(db, tid)
    words = text(body.get("body"), NOTE_RULE, NOTE_MAX)
    author = next((p.display_name for p in ctx.people if p.id == ctx.user_id), "Someone")
    n = TransactionNote(transaction_id=t.id, author_id=ctx.user_id, author_name=author, body=words,
                        created_at=deps.now())
    db.add(n)
    db.flush()
    record(db, ctx, "txn.note_add", target_id=t.id, after={"about": about(t)})
    db.commit()
    return note_out(n)


@router.delete("/{note_id}")
@recorded
def remove_note(tid: int, note_id: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """The author removes their note and gets its Undo token (nothing vanishes unseen); POST /undo/{token} puts it back."""
    t = _txn_or_404(db, tid)
    n = db.get(TransactionNote, note_id)
    if n is None or n.transaction_id != t.id:
        raise HTTPException(404, detail={"error": "No such note."})
    if n.author_id != ctx.user_id:
        raise HTTPException(403, detail={"error": NOT_YOUR_NOTE})
    token = remember_removed_note(db, n, ctx.user_id, deps.now())
    db.delete(n)
    record(db, ctx, "txn.note_remove", target_id=t.id, after={"about": about(t)})
    db.commit()
    return {"undo": token}
