"""Building blocks for Care's tests on the fictional parent book "Margaret Ellis"."""
import json
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from steward.care.store import Setup
from steward.db.models import Account, AccountType, InventoryItem, Source
from steward.inventory import kinds as K
from steward.services.accounts import manual_institution, record_balance

NOW = datetime(2026, 10, 13, 19, tzinfo=timezone.utc)
TODAY = date(2026, 10, 13)
OWNERS = {"margaret": "Margaret", "robert-husband": "Robert (husband)", "joint": "Joint"}
SETUP = Setup(person="margaret", birth_year=1944, spouse_birth_year=None, state="CA", care_inflation_bp=400,
              spending_monthly_cents=None)


def add_item(db: Session, kind: str, name: str, details: dict, *, status: str = "confirmed") -> InventoryItem:
    item = InventoryItem(kind=kind, name=name, owner="margaret", status=status, data_source="manual",
                         details=json.dumps(details), created_at=NOW, updated_at=NOW)
    db.add(item)
    db.flush()
    return item


def add_account(db: Session, name: str, type_: str, cents: int | None, *, roth: bool = False,
                status: str = "confirmed") -> tuple[InventoryItem, Account]:
    acct = Account(institution_id=manual_institution(db).id, name=name, owner="margaret", source=Source.manual,
                   type=AccountType.roth_ira if roth else K.ACCOUNT_TYPE_TO_ACCOUNT[type_])
    db.add(acct)
    db.flush()
    item = add_item(db, "account", name, {"type": type_}, status=status)
    item.account_id = acct.id
    if cents is not None:
        record_balance(db, acct.id, TODAY, cents)
    db.flush()
    return item, acct
