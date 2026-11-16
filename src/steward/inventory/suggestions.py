"""Stored suggestions (spec 3.3; decisions 7 and 9; ruling 18). refresh() turns the suggester's candidates into rows:
open ones are updated in place (their ids stay), answered ones are never touched, a payer answered Not hers is never
suggested again, and an open suggestion that is no longer found is deleted. The words each card shows are made here
from the stored facts, so an item renamed later reads right."""
from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import clock
from steward.books.people import mid_sentence
from steward.db.models import Account, InventoryItem, Suggestion, TaxForm, Transaction
from steward.inventory import kinds as K
from steward.inventory.changes import record
from steward.inventory.items import CLOSED_RULE, REF_RULE, details_of
from steward.inventory.present import article, ordinal, parent_name, possessive, short_ref, spelled, usd
from steward.inventory.suggester import candidates, item_key, overlaps, read_inputs

ANSWERED = "That suggestion was already answered."
NO_SUCH = "No such suggestion."
DISMISSED_SUB = "Won't be suggested again. Change this under Settings → Dismissed suggestions."
NOUNS = {"income": "deposits", "insurance": "payments", "interest": "interest credits",
         "dividend": "dividend credits", "transfer": "transfers"}
PER = {"monthly": "a month", "quarterly": "every 3 months", "half_yearly": "every 6 months", "yearly": "a year"}
EACH = {"monthly": "each month", "quarterly": "every 3 months", "half_yearly": "every 6 months", "yearly": "each year"}
APART = {"monthly": "about a month apart", "quarterly": "about three months apart", "half_yearly": "about six months apart",
         "yearly": "about a year apart"}


class SuggestionRefused(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return clock.now()


def refresh(db: Session, today: date) -> None:
    rows = list(db.scalars(select(Suggestion)))
    existing = {(s.kind, s.payer_key): s for s in rows}
    dismissed = {s.payer_key for s in rows if s.status == "dismissed"}
    seen = set()
    for c in candidates(*read_inputs(db)):
        key = (c.kind, c.payer_key)
        if c.payer_key in dismissed:
            continue
        s = existing.get(key)
        details = json.dumps({"signal": c.signal, "guess": c.guess, "hint_word": c.hint_word,
                              "amount_cents": c.amount_cents, "frequency": c.frequency, "usual_day": c.usual_day,
                              "account_id": c.account_id, "related_item_id": c.related_item_id,
                              "match_text": c.match_text})
        evidence = json.dumps({"txn_ids": c.txn_ids, "count": c.count, "form_ids": c.form_ids})
        if s is None:
            s = Suggestion(kind=c.kind, payer_key=c.payer_key, payer_name=c.payer_name, status="open",
                           details=details, evidence=evidence, created_at=_now(), updated_at=_now())
            db.add(s)
        elif s.status == "open" and (s.details != details or s.evidence != evidence):
            s.details, s.evidence, s.payer_name, s.updated_at = details, evidence, c.payer_name, _now()
        seen.add(key)
    for key, s in existing.items():
        if s.status == "open" and key not in seen:
            db.delete(s)
    db.flush()


def open_rows(db: Session) -> list[Suggestion]:
    rows = list(db.scalars(select(Suggestion).where(Suggestion.status == "open")))
    order = {"income": 0, "insurance": 1, "account": 2}
    return sorted(rows, key=lambda s: (order[s.kind], s.payer_name))


def get_open(db: Session, sid: int) -> Suggestion:
    s = db.get(Suggestion, sid)
    if s is None:
        raise SuggestionRefused(NO_SUCH, 404)
    if s.status != "open":
        raise SuggestionRefused(ANSWERED, 409)
    return s


def _noun(d: dict, ev: dict) -> str:
    if d["signal"] == "form":
        n = len(ev["form_ids"])
        return "tax form" if n == 1 else "tax forms"
    return NOUNS[d["signal"]]


def _count(d: dict, ev: dict) -> int:
    return len(ev["form_ids"]) if d["signal"] == "form" else ev["count"]


def _phrase(s: Suggestion, d: dict) -> str:
    if s.kind == "income":
        word = K.type_word("income", d.get("guess")) or "income"
        return f"{article(word)} {word} deposit"
    if s.kind == "insurance":
        word = K.type_word("insurance", d.get("guess")) or "insurance"
        return f"{article(word)} {word} premium"
    return {"interest": f"interest from {s.payer_name}", "dividend": f"dividends from {s.payer_name}",
            "transfer": f"transfers with {s.payer_name}"}.get(d["signal"], f"a tax form from {s.payer_name}")


def summary(db: Session, name: str) -> dict | None:
    rows = open_rows(db)
    if not rows:
        return None
    sources = {"transactions" if json.loads(s.details)["signal"] != "form" else "tax forms" for s in rows}
    found = f"found in {possessive(name)} " + (" and ".join(sorted(sources, key=lambda w: w != "transactions")))
    return {"count": len(rows), "found_in": found, "phrases": [_phrase(s, json.loads(s.details)) for s in rows]}


def pending_income(db: Session) -> list[tuple[str, int]]:
    out = []
    for s in open_rows(db):
        d = json.loads(s.details)
        monthly = K.monthly_cents(d.get("amount_cents"), d.get("frequency"))
        if s.kind == "income" and monthly:
            out.append((s.payer_name, monthly))
    return out


def _form_line(f: TaxForm) -> str:
    b = json.loads(f.boxes or "{}")
    facts = {"1099-INT": ("box_1", "interest"), "1099-DIV": ("box_1a", "dividends"), "1099-R": ("box_1", "paid out"),
             "SSA-1099": ("box_5", "in benefits")}[f.form]
    parts = [f"{f.form} {f.tax_year}"] + ([f"••{f.last4}"] if f.last4 else [])
    if b.get(facts[0]) is not None:
        parts.append(f"{usd(b[facts[0]])} {facts[1]}")
    return " · ".join(parts)


def _account_label(db: Session, L, account_id: int | None) -> str:
    item = next((i for i in L.items if i.account_id == account_id), None) if account_id else None
    if item is not None:
        return short_ref(item.name, item.institution, item.last4)
    acct = db.get(Account, account_id) if account_id else None
    return acct.name if acct else "an account"


def suggestion_out(db: Session, s: Suggestion, L, owner: str) -> dict:
    from steward.inventory.overview import label_of
    d, ev = json.loads(s.details), json.loads(s.evidence)
    txns = sorted(db.scalars(select(Transaction).where(Transaction.id.in_(ev["txn_ids"][:6]))),
                  key=lambda t: (t.posted_at, t.id), reverse=True)
    forms = list(db.scalars(select(TaxForm).where(TaxForm.id.in_(ev["form_ids"])).order_by(TaxForm.id)))
    n, noun, payer = _count(d, ev), _noun(d, ev), s.payer_name
    name = parent_name(L.owners.values())
    acct = _account_label(db, L, d.get("account_id"))
    guess, freq = d.get("guess"), d.get("frequency")
    first_form = forms[0] if forms else None
    if s.kind == "income":
        eyebrow = "Suggested: income" + (f" · {K.type_word('income', guess)}" if guess else "")
        title = (f"{payer} pays {name} {usd(d['amount_cents'])} {PER[freq]}" if d.get("amount_cents") and freq
                 else f"Income from {payer}")
        if d["signal"] == "form":
            why = f"From {possessive(name)} {first_form.tax_year} {first_form.form}."
        else:
            why = f"{n} deposits into {acct} from the same payer, {APART.get(freq, 'regularly')}."
        related = L.by_id.get(d.get("related_item_id"))
        if related is not None:
            why += (f" You have {article(label_of(L, related))} {label_of(L, related)} listed as "
                    f"{K.STATUS_LABELS[related.status]}; this may be its payout.")
    elif s.kind == "insurance":
        label = K.type_label("insurance", guess)
        eyebrow = "Suggested: insurance" + (f" · {label}" if label else "")
        title = f"A {usd(d['amount_cents'])} premium to {payer} {EACH[freq]}"
        day = f", around the {ordinal(d['usual_day'])}" if d.get("usual_day") else ""
        why = f"{n} payments from {acct}{day}."
        if d.get("hint_word") and label:
            why += f" \"{d['hint_word']}\" is how {payer} names {label} plans."
    else:
        eyebrow = "Suggested: account · Needs checking"
        if d["signal"] in ("interest", "dividend"):
            what = "interest" if d["signal"] == "interest" else "dividend"
            title = f"{'Interest' if what == 'interest' else 'Dividends'} from {payer}"
            firm, kind_of = ("a bank", "a savings account or CD") if what == "interest" else ("a firm", "a brokerage account")
            if n == 1:
                why = f"One {what} credit naming {firm} with no item. {name} may have {kind_of} there."
            else:
                ts = sorted(db.scalars(select(Transaction.posted_at).where(Transaction.id.in_(ev["txn_ids"]))))
                months = round((ts[-1] - ts[0]).days / 30.4 / max(1, len(ts) - 1)) if len(ts) > 1 else 0
                apart = {1: "a month apart", 12: "a year apart"}.get(months, f"{spelled(months).lower()} months apart")
                why = f"{spelled(n)} {what} credits, {apart}, naming {firm} with no item. {name} may have {kind_of} there."
        elif d["signal"] == "transfer":
            title = f"Transfers with {payer}"
            why = f"{n} transfers to or from {payer}, which has no item. {name} may have an account there."
        else:
            title = f"{payer} on {possessive(name)} {first_form.form}"
            why = (f"{possessive(name)} {first_form.tax_year} {first_form.form} names {payer}"
                   + (f", account ••{first_form.last4}." if first_form.last4 else "."))
    payer_key = item_key(payer)
    likely = [i.id for i in L.items if i.kind in ("account", "income", "insurance")
              and overlaps(item_key(i.institution), payer_key)]
    return {
        "id": s.id, "kind": s.kind, "payer": payer, "eyebrow": eyebrow, "title": title, "why": why,
        "evidence": [{"raw": t.raw_description, "amount_cents": t.amount_cents, "posted_at": t.posted_at.isoformat(),
                      "account": _account_label(db, L, t.account_id)} for t in txns],
        "forms": [_form_line(f) for f in forms], "phrase": _phrase(s, d), "noun": noun, "count": n,
        "prefill": _prefill(s, d, forms, L, owner, n, noun, name),
        "filled_line": (f"Filled in from {possessive(name)} {first_form.tax_year} {first_form.form} from {payer}. Check each field, then Add item."
                        if d["signal"] == "form" else f"Filled in from {n} {payer} {noun}. Check each field, then Add item."),
        "likely_ids": likely,
    }


def _prefill(s: Suggestion, d: dict, forms: list[TaxForm], L, owner: str, n: int, noun: str, name: str) -> dict:
    via = next((i for i in L.items if d.get("account_id") and i.account_id == d.get("account_id")), None)
    source = via.data_source if via is not None and via.data_source in ("feed", "statement") else "manual"
    reason = (f"Suggested from {possessive(name)} {forms[0].tax_year} {forms[0].form}." if d["signal"] == "form"
              else f"Suggested from {n} {noun} in {possessive(name)} transactions.")
    base = {"kind": s.kind, "institution": s.payer_name, "owner": forms[0].recipient if forms else owner,
            "status": "needs_checking", "check_reason": reason}
    guess = d.get("guess")
    if s.kind == "income":
        word = K.type_word("income", guess) or "income"
        details = {"source": guess or "other", "amount_cents": d.get("amount_cents"),
                   "frequency": d.get("frequency") or "monthly", "usual_day": d.get("usual_day"),
                   "lands_in_id": via.id if via is not None else None, "match_text": d.get("match_text")}
        return {**base, "name": s.payer_name if guess == "social_security" else f"{s.payer_name} {word}",
                "data_source": source, "details": {k: v for k, v in details.items() if v is not None}}
    if s.kind == "insurance":
        details = {"type": guess, "amount_cents": d.get("amount_cents"), "frequency": d.get("frequency"),
                   "usual_day": d.get("usual_day"), "paid_from_id": via.id if via is not None else None,
                   "match_text": d.get("match_text")}
        return {**base, "name": K.type_label("insurance", guess) or s.payer_name, "data_source": source,
                "details": {k: v for k, v in details.items() if v is not None}}
    last4 = next((f.last4 for f in forms if f.last4), None)
    out = {**base, "name": K.type_label("account", guess) or "Account", "data_source": "manual",
           "details": {"type": guess} if guess else {}}
    if last4:
        out["last4"] = last4
    return out


def mark_added(db: Session, ctx, s: Suggestion, item: InventoryItem) -> None:
    s.status, s.item_id, s.answered_at, s.answered_by = "added", item.id, _now(), ctx.user_id
    db.flush()


def dismiss(db: Session, ctx, s: Suggestion) -> dict:
    s.status, s.answered_at, s.answered_by = "dismissed", _now(), ctx.user_id
    record(db, ctx, "suggestion.dismiss", target_id=s.id, after={"payer": s.payer_name})
    db.flush()
    return {"id": s.id, "icon": "x", "line": f"Not {possessive(parent_name(o.label for o in ctx.owners))}: {s.payer_name}", "sub": DISMISSED_SUB}


def link(db: Session, ctx, s: Suggestion, item_id: object, confirm: object) -> dict:
    item = db.get(InventoryItem, item_id) if isinstance(item_id, int) and not isinstance(item_id, bool) else None
    if item is None or item.kind not in ("account", "income", "insurance"):
        raise SuggestionRefused(REF_RULE)
    if item.status == "closed":
        raise SuggestionRefused(CLOSED_RULE, 409)
    d, ev = json.loads(s.details), json.loads(s.evidence)
    item_details = details_of(item)
    s.undo = json.dumps({"item_id": item.id, "status": item.status, "check_reason": item.check_reason,
                         "match_text": item_details.get("match_text")})
    if not item_details.get("match_text") and d.get("match_text"):
        item_details["match_text"] = d["match_text"]
        item.details = json.dumps(item_details)
    confirmed = confirm is True and item.status == "needs_checking"
    if confirmed:
        item.status, item.check_reason = "confirmed", None
    s.status, s.item_id, s.answered_at, s.answered_by = "linked", item.id, _now(), ctx.user_id
    n, noun = _count(d, ev), _noun(d, ev)
    record(db, ctx, "suggestion.link", target_id=s.id, item_id=item.id,
           after={"payer": s.payer_name, "count": n, "noun": noun, "confirmed": confirmed})
    db.flush()
    return {"id": s.id, "icon": "check", "line": f"Linked to {item.name}" + (", now Confirmed" if confirmed else ""),
            "sub": f"{s.payer_name} · {n} {noun}"}


def undo(db: Session, ctx, s: Suggestion) -> None:
    if s.status not in ("dismissed", "linked"):
        raise SuggestionRefused("Only a dismissed or linked suggestion can be undone.", 409)
    if s.status == "linked" and s.undo:
        u = json.loads(s.undo)
        item = db.get(InventoryItem, u["item_id"])
        if item is not None and item.status != "closed":
            d = details_of(item)
            if u.get("match_text"):
                d["match_text"] = u["match_text"]
            else:
                d.pop("match_text", None)
            item.details, item.status, item.check_reason = json.dumps(d), u["status"], u["check_reason"]
    s.status, s.item_id, s.undo, s.answered_at, s.answered_by = "open", None, None, None, None
    record(db, ctx, "suggestion.undo", target_id=s.id, after={"payer": s.payer_name})
    db.flush()


def dismissed_rows(db: Session, names: dict[int, str]) -> list[dict]:
    rows = db.scalars(select(Suggestion).where(Suggestion.status == "dismissed").order_by(Suggestion.answered_at.desc()))
    return [{"id": s.id, "payer": s.payer_name, "kind_label": K.KIND_LABELS[s.kind],
             "answered_on": s.answered_at.date().isoformat() if s.answered_at else None,
             "answered_by": mid_sentence(names.get(s.answered_by))} for s in rows]
