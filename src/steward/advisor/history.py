"""A person's conversations as the Ask page shows them (spec 5.2, 5.3; plan B ruling 1): the list, grouped by day,
with question counts and whether store names were sent; and one conversation turn by turn with what was typed and
sent, the steps, the answer, what Claude saw, the approval line and the time and cost. Conversations from before
plan B (messages but no chat_turn rows) replay from their messages."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.advisor.aliases import display
from steward.advisor.saw import TITLES, summary
from steward.advisor.turn import APPROVED_LINE, DECLINED_LINE, DONE, LONG_LINE, LONG_TOKENS, meta_line, rows_word
from steward.db.models import AdvisorOutgoing, ChatConversation, ChatMessage, ChatTurn
from steward import clock as steward_clock
from steward_boundary.about import about_text
from steward.inventory.present import clock, day_label
from steward_boundary.aliases import ALIAS_TOKEN_RE

LIST_LIMIT = 200
VIEWER_DONE_LINE = "Store and payee names need a manager's OK, so Claude answered from totals."


def _local(t: datetime) -> datetime:
    return t.astimezone(steward_clock.household_tz())


def group_of(d: date, today: date) -> str:
    return "today" if d == today else "week" if 0 < (today - d).days < 7 else "earlier"


def when_short(t: datetime, today: date) -> str:
    local = _local(t)
    return clock(local) if local.date() == today else f"{local:%a}, {day_label(local.date(), today)}"


def when_long(t: datetime, today: date) -> str:
    local = _local(t)
    if local.date() == today:
        return f"Today {clock(local)}"
    return f"{local:%a}, {day_label(local.date(), today)}, {clock(local)}"


def _requests(db: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    sub = (select(AdvisorOutgoing.conversation_id, AdvisorOutgoing.turn_id, AdvisorOutgoing.seq)
           .where(AdvisorOutgoing.conversation_id.in_(ids)).distinct().subquery())
    return dict(db.execute(select(sub.c.conversation_id, func.count()).group_by(sub.c.conversation_id)).all())


def conversation_rows(db: Session, user_id: int, labels: dict[str, str], today: date) -> list[dict]:
    convs = db.execute(select(ChatConversation.id, ChatConversation.title, ChatConversation.updated_at)
                       .where(ChatConversation.user_id == user_id, ChatConversation.deleted_at.is_(None))
                       .order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc())
                       .limit(LIST_LIMIT)).all()
    ids = [c.id for c in convs]
    questions: dict[int, int] = {}
    stores: set[int] = set()
    legacy: dict[int, int] = {}
    if ids:
        questions = dict(db.execute(select(ChatTurn.conversation_id, func.count()).where(
            ChatTurn.conversation_id.in_(ids)).group_by(ChatTurn.conversation_id)).all())
        stores = set(db.scalars(select(ChatTurn.conversation_id).where(
            ChatTurn.conversation_id.in_(ids), ChatTurn.store_rows > 0).distinct()))
        old = [i for i in ids if i not in questions]
        if old:
            legacy = dict(db.execute(select(ChatMessage.conversation_id, func.count(func.distinct(ChatMessage.turn_id)))
                                     .where(ChatMessage.conversation_id.in_(old)).group_by(ChatMessage.conversation_id)).all())
    requests = _requests(db, ids)
    return [{"id": cid, "title": display(title, labels), "group": group_of(_local(updated).date(), today),
             "when": when_short(updated, today), "questions": questions.get(cid) or legacy.get(cid, 0),
             "store_names": cid in stores, "requests": requests.get(cid, 0)} for cid, title, updated in convs]


def _texts(m: ChatMessage) -> list[str]:
    content = json.loads(m.content).get("content")
    return [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"] \
        if isinstance(content, list) else []


def conversation_detail(db: Session, conv: ChatConversation, labels: dict[str, str], names: dict[int, str],
                        book_kind: str, today: date) -> dict:
    turns = list(db.scalars(select(ChatTurn).where(ChatTurn.conversation_id == conv.id).order_by(ChatTurn.id)))
    answers: dict[str, list[str]] = defaultdict(list)
    asked_old: dict[str, str] = {}
    order: list[str] = []
    for m in db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conv.id).order_by(ChatMessage.id)):
        texts = _texts(m)
        if m.turn_id not in order:
            order.append(m.turn_id)
        if m.role == "assistant" and texts:
            answers[m.turn_id].append("\n\n".join(texts))
        elif m.role == "user" and texts and m.turn_id not in asked_old:
            asked_old[m.turn_id] = "\n\n".join(texts)
    saw: dict[str, list[dict]] = defaultdict(list)
    recorded: set[str] = set()
    for r in db.scalars(select(AdvisorOutgoing).where(AdvisorOutgoing.conversation_id == conv.id)
                        .order_by(AdvisorOutgoing.id)):
        recorded.add(r.turn_id)
        if r.part not in ("tool_result", "merchant_rows"):
            continue
        p = json.loads(r.payload)
        saw[r.turn_id].append({"key": f"{r.turn_id}.{r.seq}", "name": p["name"], "title": TITLES.get(p["name"], p["name"]),
                               "summary": summary(p["name"], p["content"], p["is_error"], names.get(r.approved_by)),
                               "is_error": p["is_error"], "payload": p["content"]})
    known = {t.turn_id for t in turns}
    out = [{"turn_id": tid, "asked": display(asked_old[tid], labels), "sent": asked_old[tid], "chips": [],
            "as_written": True, "who": names.get(conv.user_id, ""), "when": "", "steps": [],
            "answer": "\n\n".join(answers.get(tid, [])), "stop": None, "line": None, "meta": None,
            "saw": saw.get(tid, []), "approval": None, "looked_into": False, "unfinished": False,
            "about": None}
           for tid in order if tid not in known and tid in asked_old]
    for t in turns:
        steps = json.loads(t.steps)
        seen = saw.get(t.turn_id, [])
        approval = None
        if t.approval == "approved":
            key = next((s["key"] for s in seen if s["name"] == "merchant_detail" and not s["is_error"]), None)
            approval = {"state": "approved", "log_key": key, "line": APPROVED_LINE.format(
                name=names.get(t.approved_by, "A manager"), rows=rows_word(t.store_rows))}
        elif t.approval == "declined":
            approval = {"state": "declined", "line": DECLINED_LINE, "log_key": None}
        elif t.approval == "viewer":
            approval = {"state": "viewer", "line": VIEWER_DONE_LINE, "log_key": None}
        chips = json.loads(t.chips)
        wire = json.loads(t.about) if t.about else None
        out.append({"turn_id": t.turn_id, "asked": t.asked, "sent": t.sent, "chips": chips,
                    "as_written": t.sent is not None and not chips, "who": names.get(t.user_id, ""),
                    "when": when_long(t.started_at, today),
                    "steps": [{"tool": s, "done": DONE.get(s, s)} for s in steps],
                    "answer": "\n\n".join(answers.get(t.turn_id, [])), "stop": t.stop, "line": t.line,
                    "meta": meta_line(t.ms, t.cost_cents, 1 if t.turn_id in recorded else 0) if t.ended_at else None,
                    "saw": seen, "approval": approval, "looked_into": book_kind == "parent" and "flags" in steps,
                    "unfinished": t.ended_at is None,
                    "about": {"chip": wire, "sent": about_text(wire)} if wire else None})
    words = " ".join([conv.title] + [x["answer"] for x in out] + [x["sent"] or "" for x in out]
                     + [x["about"]["sent"] for x in out if x["about"]])
    return {"id": conv.id, "title": display(conv.title, labels), "ended": conv.ended_at is not None,
            "requests": _requests(db, [conv.id]).get(conv.id, 0),
            "long_line": LONG_LINE if conv.last_input_tokens >= LONG_TOKENS else None,
            "labels": {a: labels[a] for a in sorted(set(ALIAS_TOKEN_RE.findall(words))) if a in labels},
            "turns": out}
