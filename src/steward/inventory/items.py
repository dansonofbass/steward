"""Inventory items (spec 3.1, 3.2; design pass decisions 2-5). Every write goes through here, so the change record,
the account link and the full-number rule live in one place. Callers commit."""
from __future__ import annotations

from steward import clock
import json
import re
from datetime import date, datetime

from sqlalchemy.orm import Session

from steward.db.models import DATA_SOURCES, INVENTORY_KINDS, Account, AccountType, InventoryItem, Source
from steward.events import resolve_events_matching
from steward.inventory import kinds as K
from steward.inventory.changes import changed, record
from steward.inventory.present import last4_of, mask, parent_name
from steward.services.accounts import latest_balance, manual_institution, record_balance

NO_SUCH_ITEM = "No such item."
KIND_RULE = "Choose what kind of item this is."
NAME_RULE = "Enter a name of up to 120 characters."
OWNER_RULE = "Choose one of this book's owners."
STATUS_RULE = "Choose Confirmed or Needs checking."
SOURCE_RULE = "Choose Statements or Typed in."
FEED_RULE = "Bank feed accounts arrive on their own."
TYPE_RULES = {"account": "Choose the type of account.", "income": "Choose where the money comes from.",
              "insurance": "Choose the type of policy.", "document": "Choose the type of document.",
              "contact": "Choose their role."}
AMOUNT_RULE = "Enter an amount in dollars and cents."
FREQUENCY_RULE = "Choose how often."
DAY_RULE = "Enter a day of the month from 1 to 31."
DATE_RULE = "Enter a date like 2026-03-01."
ORIGINAL_RULE = "Say where the original is kept."
REF_RULE = "Choose an item from this book."
NUMBER_RULE = "Enter the number as it's printed, up to 40 characters."
LAST4_RULE = "Enter up to 4 digits or letters."
TEXT_RULE = "Keep {field} under {n} characters."
EMAIL_RULE = "Enter an email address."
DEBT_RULE = "Enter what {name} owes as a negative number."
DETAILS_RULE = "That request wasn't understood."
CLOSED_RULE = "This item is closed. Reopen it to change it."
NOT_CLOSED = "This item isn't closed."
CLOSED_ON_RULE = "Enter the date it closed, like 2026-03-01."
NO_NUMBER = "No full number is saved for this item."
BALANCE_FEED = "This account's balance comes from the bank feed."
FLOOR_RULE = "Only checking, savings and CD accounts have a low-balance floor."
LTC_FIELDS = ("benefit_cents", "benefit_per", "waiting_days", "pool_cents", "benefit_years", "rider_bp")
BENEFIT_PER_RULE = "Choose whether the benefit is paid by the day or the month."
WAITING_RULE = "Enter the waiting period in days, from 0 to 730."
YEARS_RULE = "Enter the benefit years as a whole number from 1 to 30."
RIDER_RULE = "Enter inflation protection from 0% to 10% a year."


class ItemRefused(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return clock.now()


def details_of(item: InventoryItem) -> dict:
    return json.loads(item.details or "{}")


def snapshot(item: InventoryItem) -> dict:
    """The item's fields, flat, as the change record compares them. The number is masked (design pass 5)."""
    return {"name": item.name, "owner": item.owner, "institution": item.institution, "number": mask(item.last4),
            "status": item.status, "check_reason": item.check_reason, "data_source": item.data_source,
            "login_kept_in": item.login_kept_in, "notes": item.notes, **details_of(item)}


# -- field checks -----------------------------------------------------------------------------------------------
def _text(value: object, field: str, n: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value.strip()) > n:
        raise ItemRefused(TEXT_RULE.format(field=field, n=n))
    return value.strip() or None


def _name(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120:
        raise ItemRefused(NAME_RULE)
    return value.strip()


def _owner(ctx, value: object) -> str:
    if value not in {o.key for o in ctx.owners}:
        raise ItemRefused(OWNER_RULE)
    return value


def _one(value: object, options, rule: str) -> str:
    if not isinstance(value, str) or value not in options:
        raise ItemRefused(rule)
    return value


def _cents(value: object, *, negative: bool = False) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or abs(value) > 10**12 or (value < 0 and not negative):
        raise ItemRefused(AMOUNT_RULE)
    return value


def _day(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 31:
        raise ItemRefused(DAY_RULE)
    return value


def _whole(value: object, lo: int, hi: int, rule: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ItemRefused(rule)
    return value


def _iso(value: object, rule: str = DATE_RULE) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ItemRefused(rule)
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ItemRefused(rule) from None


def _ref(db: Session, value: object, kinds: tuple[str, ...], self_id: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value == self_id:
        raise ItemRefused(REF_RULE)
    other = db.get(InventoryItem, value)
    if other is None or other.kind not in kinds:
        raise ItemRefused(REF_RULE)
    return value


def _check_debt(ctx, type_: str | None, cents: int) -> None:
    if type_ in K.DEBT_TYPES and cents > 0:
        raise ItemRefused(DEBT_RULE.format(name=parent_name(o.label for o in ctx.owners)))


def clean_details(db: Session, kind: str, raw: object, current: dict, self_id: int | None) -> dict:
    """The kind's own fields, merged over `current`. Keys a kind doesn't have are ignored."""
    if not isinstance(raw, dict):
        raise ItemRefused(DETAILS_RULE)
    out = dict(current)
    tf = K.TYPE_FIELD[kind]
    if tf in raw:
        out[tf] = None if raw[tf] is None else _one(raw[tf], [t[0] for t in K.TYPES_BY_KIND[kind]], TYPE_RULES[kind])
    if kind in ("income", "insurance"):
        if "amount_cents" in raw:
            out["amount_cents"] = _cents(raw["amount_cents"])
        if "frequency" in raw:
            allowed = K.INCOME_FREQUENCIES if kind == "income" else tuple(K.FREQUENCIES)
            out["frequency"] = None if raw["frequency"] is None else _one(raw["frequency"], allowed, FREQUENCY_RULE)
        if "usual_day" in raw:
            out["usual_day"] = _day(raw["usual_day"])
        if "match_text" in raw:
            out["match_text"] = _text(raw["match_text"], "the matched text", 120)
    if kind == "income" and "lands_in_id" in raw:
        out["lands_in_id"] = _ref(db, raw["lands_in_id"], ("account",), self_id)
    if kind == "insurance":
        if "paid_from_id" in raw:
            out["paid_from_id"] = _ref(db, raw["paid_from_id"], ("account", "income"), self_id)
        if "renewal_on" in raw:
            out["renewal_on"] = _iso(raw["renewal_on"])
        # D8: a long-term care policy's terms (parent care plan ruling 17). Another type drops them, as a floor drops.
        for f in ("benefit_cents", "pool_cents"):
            if f in raw:
                out[f] = _cents(raw[f])
        if "benefit_per" in raw:
            out["benefit_per"] = None if raw["benefit_per"] is None else _one(raw["benefit_per"], ("day", "month"),
                                                                              BENEFIT_PER_RULE)
        for f, lo, hi, rule in (("waiting_days", 0, 730, WAITING_RULE), ("benefit_years", 1, 30, YEARS_RULE),
                                ("rider_bp", 0, 1000, RIDER_RULE)):
            if f in raw:
                out[f] = _whole(raw[f], lo, hi, rule)
        if out.get("type") != "long_term_care":
            for f in LTC_FIELDS:
                out.pop(f, None)
        elif out.get("benefit_cents") is not None and not out.get("benefit_per"):
            raise ItemRefused(BENEFIT_PER_RULE)
        for f in LTC_FIELDS:        # ruling P2: a blank term is no term, never a stored null
            if f in out and out[f] is None:
                del out[f]
    if kind == "document":
        if "original_kept_in" in raw:
            out["original_kept_in"] = _text(raw["original_kept_in"], "where the original is kept", 200)
        if "signed_on" in raw:
            out["signed_on"] = _iso(raw["signed_on"])
        if "prepared_by_id" in raw:
            out["prepared_by_id"] = _ref(db, raw["prepared_by_id"], ("contact",), self_id)
    if kind == "contact":
        if "phone" in raw:
            out["phone"] = _text(raw["phone"], "the phone number", 40)
        if "email" in raw:
            email = _text(raw["email"], "the email address", 200)
            if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                raise ItemRefused(EMAIL_RULE)
            out["email"] = email
        if "looks_after_ids" in raw:
            ids = raw["looks_after_ids"]
            if not isinstance(ids, list):
                raise ItemRefused(REF_RULE)
            out["looks_after_ids"] = sorted({_ref(db, i, ("account", "income", "insurance", "document"), self_id)
                                             for i in ids})
    if kind == "account":
        if "floor_cents" in raw:
            floor = _cents(raw["floor_cents"])
            if floor is not None and out.get("type") not in K.FLOOR_TYPES:
                raise ItemRefused(FLOOR_RULE)
            out["floor_cents"] = floor
        if out.get("type") not in K.FLOOR_TYPES or out.get("floor_cents") is None:
            out.pop("floor_cents", None)       # a type with no floor drops the old one
    if not out.get(tf):
        raise ItemRefused(TYPE_RULES[kind])
    if kind == "income" and out.get("amount_cents") is None:
        raise ItemRefused(AMOUNT_RULE)
    if kind == "income" and not out.get("frequency"):
        raise ItemRefused(FREQUENCY_RULE)
    if kind == "document" and not out.get("original_kept_in"):
        raise ItemRefused(ORIGINAL_RULE)
    return {k: v for k, v in out.items() if v is not None}


def _apply_number(item: InventoryItem, body: dict) -> None:
    """A typed number replaces the full number and its last 4; `null` clears both. Without a full number, last4 may be
    typed alone (ruling 11)."""
    if "number" in body:
        raw = body["number"]
        if raw is None:
            item.full_number, item.last4 = None, None
            return
        if not isinstance(raw, str) or len(raw.strip()) > 40:
            raise ItemRefused(NUMBER_RULE)
        if raw.strip():
            if last4_of(raw) is None:
                raise ItemRefused(NUMBER_RULE)
            item.full_number, item.last4 = raw.strip(), last4_of(raw)
    elif "last4" in body:
        raw = body["last4"]
        if raw in (None, ""):
            item.last4, item.full_number = None, None
            return
        if not isinstance(raw, str) or not re.fullmatch(r"[0-9A-Za-z]{1,4}", raw.strip()):
            raise ItemRefused(LAST4_RULE)
        if raw.strip().upper() != item.last4:
            item.last4, item.full_number = raw.strip().upper(), None


def _balance(db: Session, item: InventoryItem) -> int | None:
    lb = latest_balance(db, item.account_id) if item.account_id else None
    return lb[1] if lb else None


def _sync_account(db: Session, item: InventoryItem) -> None:
    """The linked account row follows its item: name, owner and the nearest account type (ruling 6)."""
    if item.account_id is None:
        return
    acct = db.get(Account, item.account_id)
    t = details_of(item).get("type")
    if t:
        if acct.type == AccountType.unknown:
            resolve_events_matching(db, "system", f"New account '{acct.name}' from ", _now())
        acct.type = K.ACCOUNT_TYPE_TO_ACCOUNT[t]
    acct.name, acct.owner = item.name, item.owner


# -- writes -----------------------------------------------------------------------------------------------------
def create_item(db: Session, ctx, body: dict, *, today: date, from_suggestion: str | None = None) -> InventoryItem:
    kind = body.get("kind")
    if kind not in INVENTORY_KINDS:
        raise ItemRefused(KIND_RULE)
    name = _name(body.get("name"))
    owner = _owner(ctx, body.get("owner"))
    status = "confirmed" if kind == "contact" else _one(body.get("status"), ("confirmed", "needs_checking"), STATUS_RULE)
    source = body.get("data_source")
    if kind == "account":
        if source == "feed":
            raise ItemRefused(FEED_RULE)
        source = _one(source if source is not None else "manual", ("statement", "manual"), SOURCE_RULE)
    elif kind in ("income", "insurance"):
        source = _one(source if source is not None else "manual", DATA_SOURCES, SOURCE_RULE)
    else:
        source = None
    t = _now()
    item = InventoryItem(kind=kind, name=name, owner=owner, status=status, data_source=source, details="{}",
                         created_at=t, created_by=ctx.user_id, updated_at=t, updated_by=ctx.user_id)
    item.institution = _text(body.get("institution"), "the institution", 120)
    item.check_reason = (_text(body.get("check_reason"), "why it needs checking", 300)
                         if status == "needs_checking" else None)
    item.login_kept_in = _text(body.get("login_kept_in"), "where the login is kept", 200)
    item.notes = _text(body.get("notes"), "the notes", 4000)
    _apply_number(item, body)
    balance = _cents(body.get("balance_cents"), negative=True) if kind == "account" else None
    db.add(item)
    db.flush()
    item.details = json.dumps(clean_details(db, kind, body.get("details") or {}, {}, item.id))
    after = {**snapshot(item), "kind": kind}
    if kind == "account":
        type_ = details_of(item)["type"]
        acct = Account(institution_id=manual_institution(db).id, name=name, type=K.ACCOUNT_TYPE_TO_ACCOUNT[type_],
                       owner=owner, source=Source.manual)
        db.add(acct)
        db.flush()
        item.account_id = acct.id
        if balance is not None:
            _check_debt(ctx, type_, balance)
            on = _iso(body.get("balance_on")) or today.isoformat()
            record_balance(db, acct.id, date.fromisoformat(on), balance)
            after["balance_cents"] = balance
    if from_suggestion:
        after["from_suggestion"] = from_suggestion
    record(db, ctx, "item.add", target_id=item.id, item_id=item.id, after=after)
    return item


def edit_item(db: Session, ctx, item: InventoryItem, body: dict, *, today: date) -> InventoryItem:
    if item.status == "closed":
        raise ItemRefused(CLOSED_RULE, 409)
    before = {**snapshot(item), "balance_cents": _balance(db, item)}
    if "name" in body:
        item.name = _name(body["name"])
    if "owner" in body:
        item.owner = _owner(ctx, body["owner"])
    if "institution" in body:
        item.institution = _text(body["institution"], "the institution", 120)
    if "status" in body and item.kind != "contact":
        item.status = _one(body["status"], ("confirmed", "needs_checking"), STATUS_RULE)
    if item.status == "confirmed":
        item.check_reason = None
    elif "check_reason" in body:
        item.check_reason = _text(body["check_reason"], "why it needs checking", 300)
    if "login_kept_in" in body:
        item.login_kept_in = _text(body["login_kept_in"], "where the login is kept", 200)
    if "notes" in body:
        item.notes = _text(body["notes"], "the notes", 4000)
    _apply_number(item, body)
    if "data_source" in body:
        if item.kind == "account" and item.data_source != "feed":
            item.data_source = _one(body["data_source"], ("statement", "manual"), SOURCE_RULE)
        elif item.kind in ("income", "insurance"):
            item.data_source = _one(body["data_source"], DATA_SOURCES, SOURCE_RULE)
    if "details" in body:
        item.details = json.dumps(clean_details(db, item.kind, body["details"], details_of(item), item.id))
    balance = before["balance_cents"]
    if item.kind == "account" and body.get("balance_cents") is not None:
        if item.data_source == "feed":
            raise ItemRefused(BALANCE_FEED, 409)
        balance = _cents(body["balance_cents"], negative=True)
        _check_debt(ctx, details_of(item).get("type"), balance)
        on = _iso(body.get("balance_on")) or today.isoformat()
        record_balance(db, item.account_id, date.fromisoformat(on), balance)
    _sync_account(db, item)
    b, a = changed(before, {**snapshot(item), "balance_cents": balance})
    if not a and not b:
        return item
    item.updated_at, item.updated_by = _now(), ctx.user_id
    record(db, ctx, "item.edit", target_id=item.id, item_id=item.id, before=b, after=a, note=body.get("note"))
    return item


def close_item(db: Session, ctx, item: InventoryItem, body: dict) -> InventoryItem:
    if item.status == "closed":
        raise ItemRefused(CLOSED_RULE, 409)
    on = _iso(body.get("closed_on"), CLOSED_ON_RULE)
    if not on:
        raise ItemRefused(CLOSED_ON_RULE)
    why = _text(body.get("why"), "why", 300)
    was = item.status
    item.status, item.closed_on, item.closed_reason = "closed", date.fromisoformat(on), why
    item.updated_at, item.updated_by = _now(), ctx.user_id
    if item.account_id is not None:
        db.get(Account, item.account_id).is_active = False
    record(db, ctx, "item.close", target_id=item.id, item_id=item.id, before={"status": was},
           after={"status": "closed", "closed_on": on}, note=why)
    return item


def reopen_item(db: Session, ctx, item: InventoryItem) -> InventoryItem:
    if item.status != "closed":
        raise ItemRefused(NOT_CLOSED, 409)
    item.status, item.closed_on, item.closed_reason = "confirmed", None, None
    item.updated_at, item.updated_by = _now(), ctx.user_id
    if item.account_id is not None:
        db.get(Account, item.account_id).is_active = True
    record(db, ctx, "item.reopen", target_id=item.id, item_id=item.id, before={"status": "closed"},
           after={"status": "confirmed"})
    return item


def reveal(db: Session, ctx, item: InventoryItem) -> str:
    """The full number, for the item page's Show button; each reveal is recorded (design pass 5)."""
    if not item.full_number:
        raise ItemRefused(NO_NUMBER, 404)
    record(db, ctx, "item.reveal", target_id=item.id, item_id=item.id)
    return item.full_number
