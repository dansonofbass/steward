from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from steward.api.body import bad
from steward.deps import book_db, open_book, today
from steward.services import cashflow as svc

router = APIRouter(dependencies=[Depends(open_book)])


@router.get("/cashflow")
def get_cashflow(months: str = "12", db: Session = Depends(book_db)):
    if not (months.isascii() and months.isdigit()) or not 1 <= int(months) <= 60:
        raise bad("Choose between 1 and 60 months.")
    t = today()
    return {"as_of": t.isoformat(), "months": svc.cashflow(db, t, int(months))}
