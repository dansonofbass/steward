"""Unknown fund symbols and the household's asset-class overrides (spec 7)."""
# "target_date" in a row's class is a display value outside `classes`; PUT accepts only the four classes.
import re

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from steward.api.body import bad, json_object
from steward.db.models import ASSET_CLASSES, AssetClass
from steward.deps import book_db, household_only, open_book, today
from steward.services.asset_classes import symbol_rows

router = APIRouter(prefix="/asset-classes", dependencies=[Depends(open_book), Depends(household_only)])
SYMBOL = re.compile(r"[A-Z0-9.\-]{1,20}")
CHOOSE = "Choose US stocks, international stocks, bonds or cash."


def _out(db: Session) -> dict:
    return {"symbols": symbol_rows(db, today().year), "classes": list(ASSET_CLASSES)}


@router.get("")
def list_symbols(db: Session = Depends(book_db)):
    return _out(db)


@router.put("")
def set_class(body: dict = Depends(json_object), db: Session = Depends(book_db)):
    symbol = body.get("symbol")
    if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol.strip().upper()):
        raise bad("Enter the fund's ticker symbol.")
    symbol = symbol.strip().upper()
    if "class" not in body:
        raise bad(CHOOSE)
    cls = body["class"]
    row = db.get(AssetClass, symbol)
    if cls is None:
        if row is not None:
            db.delete(row)
    elif cls in ASSET_CLASSES:
        if row is None:
            db.add(AssetClass(symbol=symbol, asset_class=cls, source="override"))
        else:
            row.asset_class, row.source = cls, "override"
    else:
        raise bad(CHOOSE)
    db.commit()
    return _out(db)
