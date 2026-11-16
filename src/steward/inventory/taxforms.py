"""Tax forms typed in or imported from a CSV (spec 3.3; decision 10; rulings 19, 20). Reading PDF forms is out of
scope: the manager copies the boxes. A saved form feeds the suggester; result_for() says what it did."""
from __future__ import annotations

from steward import clock
import csv
import io
import json
import re
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import TAX_FORMS, InventoryItem, Suggestion, TaxForm
from steward.inventory.changes import record
from steward.inventory.present import possessive, usd
from steward.inventory.suggester import item_key, overlaps, payer

FORM_BOXES = {
    "1099-INT": [("box_1", "Box 1 (Interest income)"), ("box_4", "Box 4 (Federal income tax withheld)")],
    "1099-DIV": [("box_1a", "Box 1a (Total ordinary dividends)"), ("box_1b", "Box 1b (Qualified dividends)"),
                 ("box_2a", "Box 2a (Total capital gain distributions)"), ("box_4", "Box 4 (Federal income tax withheld)")],
    "1099-R": [("box_1", "Box 1 (Gross distribution)"), ("box_2a", "Box 2a (Taxable amount)"),
               ("box_4", "Box 4 (Federal income tax withheld)"), ("box_7", "Box 7 (Distribution code)")],
    "SSA-1099": [("box_3", "Box 3 (Benefits paid)"), ("box_5", "Box 5 (Net benefits)"),
                 ("medicare", "Medicare premiums (in Box 3's description)")],
}
REQUIRED = {"1099-INT": "box_1", "1099-DIV": "box_1a", "1099-R": "box_1", "SSA-1099": "box_5"}
FORM_RULE = "Choose 1099-INT, 1099-DIV, 1099-R or SSA-1099."
YEAR_RULE = "Enter a tax year from 2000 to {year}."
OWNER_RULE = "Choose one of this book's owners."
PAYER_RULE = "Enter the payer's name, up to 120 characters."
LAST4_RULE = "Enter up to 4 digits or letters."
BOX_RULE = "Enter {label} in dollars and cents."
CODE_RULE = "Enter the distribution code as printed, up to 2 characters."
COLUMNS_RULE = "The CSV needs the columns form, tax_year, recipient and payer."
TOO_MANY = "A CSV can hold up to 200 forms."
SSA = "Social Security Administration"


class FormRefused(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def clean_form(body: dict, owner_keys: set[str], this_year: int) -> dict:
    form = body.get("form")
    if form not in TAX_FORMS:
        raise FormRefused(FORM_RULE)
    year = body.get("tax_year")
    if isinstance(year, bool) or not isinstance(year, int) or not 2000 <= year <= this_year:
        raise FormRefused(YEAR_RULE.format(year=this_year))
    if body.get("recipient") not in owner_keys:
        raise FormRefused(OWNER_RULE)
    name = body.get("payer") if isinstance(body.get("payer"), str) else ""
    name = name.strip() or (SSA if form == "SSA-1099" else "")
    if not name or len(name) > 120:
        raise FormRefused(PAYER_RULE)
    last4 = body.get("last4")
    if last4 in (None, ""):
        last4 = None
    elif not isinstance(last4, str) or not re.fullmatch(r"[0-9A-Za-z]{1,4}", last4.strip()):
        raise FormRefused(LAST4_RULE)
    else:
        last4 = last4.strip().upper()
    raw = body.get("boxes") if isinstance(body.get("boxes"), dict) else {}
    boxes = {}
    for key, label in FORM_BOXES[form]:
        v = raw.get(key)
        if v in (None, ""):
            continue
        if key == "box_7":
            if not isinstance(v, str) or not re.fullmatch(r"[0-9A-Za-z]{1,2}", v.strip()):
                raise FormRefused(CODE_RULE)
            boxes[key] = v.strip().upper()
        elif isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 10**12:
            raise FormRefused(BOX_RULE.format(label=label))
        else:
            boxes[key] = v
    needed = REQUIRED[form]
    if needed not in boxes:
        raise FormRefused(BOX_RULE.format(label=dict(FORM_BOXES[form])[needed]))
    got = payer(name)
    return {"form": form, "tax_year": year, "recipient": body["recipient"], "payer": name,
            "payer_key": " ".join(got[0]) if got else name.upper()[:120], "last4": last4, "boxes": boxes}


def save_form(db: Session, ctx, clean: dict, *, file_id: int | None = None, note: str | None = None) -> TaxForm:
    f = TaxForm(form=clean["form"], tax_year=clean["tax_year"], recipient=clean["recipient"], payer=clean["payer"],
                payer_key=clean["payer_key"], last4=clean["last4"], boxes=json.dumps(clean["boxes"]), file_id=file_id,
                created_at=clock.now(), created_by=ctx.user_id)
    db.add(f)
    db.flush()
    record(db, ctx, "taxform.add", target_id=f.id, note=note,
           after={"form": f.form, "payer": f.payer, "tax_year": f.tax_year, "last4": f.last4})
    return f


def _cents(text: str, label: str) -> int | None:
    t = text.strip().replace("$", "").replace(",", "")
    if not t:
        return None
    try:
        d = Decimal(t)
    except InvalidOperation:
        raise FormRefused(BOX_RULE.format(label=label)) from None
    try:
        if not d.is_finite() or d != d.quantize(Decimal("0.01")) or d < 0:
            raise FormRefused(BOX_RULE.format(label=label))
    except InvalidOperation:   # a huge exponent such as 1e30 overflows quantize
        raise FormRefused(BOX_RULE.format(label=label)) from None
    return int(d * 100)


def parse_csv(text: str, owners: dict[str, str]) -> list[dict]:
    """Rows as tax-form bodies. owners: key → label; a recipient may be either, in any case. Raises FormRefused
    naming the row (the header is row 1)."""
    reader = csv.DictReader(io.StringIO(text))
    cols = {c.strip().lower() for c in (reader.fieldnames or [])}
    if not {"form", "tax_year", "recipient", "payer"} <= cols:
        raise FormRefused(COLUMNS_RULE)
    by_label = {**{k.lower(): k for k in owners}, **{v.lower(): k for k, v in owners.items()}}
    out = []
    for n, row in enumerate(reader, start=2):
        if n > 201:
            raise FormRefused(TOO_MANY)
        r = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        form = r.get("form", "").upper()
        try:
            if form not in TAX_FORMS:
                raise FormRefused(FORM_RULE)
            labels = dict(FORM_BOXES[form])
            boxes = {}
            for key in labels:
                if key == "box_7":
                    if r.get(key):
                        boxes[key] = r[key]
                else:
                    cents = _cents(r.get(key, ""), labels[key])
                    if cents is not None:
                        boxes[key] = cents
            year = int(r["tax_year"]) if r.get("tax_year", "").isdigit() else None
            out.append({"form": form, "tax_year": year, "recipient": by_label.get(r.get("recipient", "").lower()),
                        "payer": r.get("payer", ""), "last4": r.get("last4") or None, "boxes": boxes, "_row": n})
        except FormRefused as e:
            raise FormRefused(f"Row {n}: {e}") from None
    return out


def _facts(f: TaxForm) -> str:
    b = json.loads(f.boxes or "{}")
    acct = f"account ••{f.last4}, " if f.last4 else ""
    if f.form == "1099-INT":
        return f"{acct}{usd(b['box_1'])} interest in {f.tax_year}"
    if f.form == "1099-DIV":
        return f"{acct}{usd(b['box_1a'])} dividends in {f.tax_year}"
    if f.form == "1099-R":
        return f"{usd(b['box_1'])} paid out in {f.tax_year}"
    return f"{usd(b['box_5'])} in benefits in {f.tax_year}"


def result_for(db: Session, f: TaxForm, open_before: set[tuple[str, str]], name: str) -> dict:
    for s in db.scalars(select(Suggestion).where(Suggestion.status == "open").order_by(Suggestion.id)):
        if f.id in json.loads(s.evidence).get("form_ids", []):
            joined = (s.kind, s.payer_key) in open_before
            detail = (f"Added to the suggestion already waiting for {f.payer}: {_facts(f)}." if joined
                      else f"Added to Is this one of {possessive(name)}?: {_facts(f)}.")
            return {"headline": f"{f.form} saved. {f.payer} isn't in {possessive(name)} inventory.", "detail": detail,
                    "suggestion_id": s.id, "item_id": None}
    if db.scalar(select(Suggestion.id).where(Suggestion.payer_key == f.payer_key, Suggestion.status == "dismissed")):
        return {"headline": f"{f.form} saved.", "detail": f"{f.payer} was answered Not {possessive(name)}, so nothing was suggested.",
                "suggestion_id": None, "item_id": None}
    key = tuple(f.payer_key.split())
    for item in db.scalars(select(InventoryItem).where(InventoryItem.status != "closed").order_by(InventoryItem.id)):
        d = json.loads(item.details or "{}")
        social = f.form == "SSA-1099" and d.get("source") == "social_security"
        if social or overlaps(item_key(item.institution), key):
            return {"headline": f"{f.form} saved. It matches {item.name}.", "detail": "Nothing new to add.",
                    "suggestion_id": None, "item_id": item.id}
    return {"headline": f"{f.form} saved.", "detail": "Nothing new to add.", "suggestion_id": None, "item_id": None}
