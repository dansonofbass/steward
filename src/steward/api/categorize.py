"""The household's category rules (phase 12 decision 2): see them with how many rows each covers, change a rule's
category, or remove it. Neither write touches a past row: a person spreads from a row when they want that."""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from steward.api.body import bad, json_object
from steward.api.review import top_categories
from steward.db.models import CATEGORIES, MerchantRule
from steward.deps import book_db, not_recorded, open_book
from steward.services.category_rules import pattern_counts, rule_out, rules_list

router = APIRouter(prefix="/categorize", dependencies=[Depends(open_book)])
NOT_A_CATEGORY = "That isn't one of the categories."
NO_SUCH_RULE = "No such rule."
RULE_REASON = "A category rule changes no past transaction; it only sorts the rows that arrive later."


def _rule_or_404(db: Session, rule_id: int) -> MerchantRule:
    r = db.get(MerchantRule, rule_id)
    if r is None:
        raise HTTPException(404, detail={"error": NO_SUCH_RULE})
    return r


@router.get("/usual")
def usual_categories(db: Session = Depends(book_db)):
    """Sorting redesign, Usual categories everywhere: the picker's "Your usual", ranked as Review's chips are."""
    return {"keys": top_categories(db)}


@router.get("/rules")
def list_rules(db: Session = Depends(book_db)):
    return {"rules": rules_list(db)}


@router.patch("/rules/{rule_id}")
@not_recorded(RULE_REASON)
def change_rule(rule_id: int, body: dict = Depends(json_object), db: Session = Depends(book_db)):
    r = _rule_or_404(db, rule_id)
    category = body.get("category")
    if category not in CATEGORIES or category == "uncategorized":
        raise bad(NOT_A_CATEGORY)
    r.category = category
    db.commit()
    return rule_out(r, pattern_counts(db)[r.pattern])


@router.delete("/rules/{rule_id}", status_code=204)
@not_recorded(RULE_REASON)
def remove_rule(rule_id: int, db: Session = Depends(book_db)):
    db.delete(_rule_or_404(db, rule_id))
    db.commit()
    return Response(status_code=204)
