"""Same-account detection's CPU budget, moved from tests/test_same_account_detect.py (flaky-test audit, Low: a
process_time budget is still a perf budget)."""
import time
from datetime import date, timedelta

import pytest
from sqlalchemy import insert

from steward.db.models import Account, AccountFeed, AccountType, Institution, Source, Transaction
from steward.services.same_account import detect
from steward.services.simplefin.client import SfAccount, SfTxn
from tests.same_account_fixtures import BALANCE, BALANCE_DAY, JOINT_DAYS, NOW

pytestmark = pytest.mark.perf


def test_detection_stays_quick_with_many_accounts(db):
    """Privacy and performance: detection runs per new account, inside the sync transaction. Forty same-named
    accounts at the bank, with 400 rows each, are looked at in well under a second of CPU."""
    inst = Institution(name="Betterment", source=Source.simplefin, simplefin_org_id="old", org_id="betterment")
    db.add(inst)
    db.flush()
    for n in range(40):
        a = Account(institution_id=inst.id, name="Joint Taxable", type=AccountType.brokerage_taxable, owner="joint",
                    source=Source.simplefin, external_id=f"sfin:old-{n}", created_at=NOW)
        db.add(a)
        db.flush()
        f = AccountFeed(account_id=a.id, external_id=a.external_id, institution_id=inst.id, name=a.name,
                        added_at=NOW, last_seen_at=NOW)
        db.add(f)
        db.flush()
        db.execute(insert(Transaction), [
            dict(account_id=a.id, posted_at=date(2026, 10, 26) - timedelta(days=i), amount_cents=-(n * 1000 + i),
                 raw_description="ROW", external_id=f"old-{n}-{i}", feed_id=f.id, imported_at=NOW)
            for i in range(400)])
    db.commit()
    incoming = SfAccount("sam-joint", "Joint Taxable", "sam", "USD", BALANCE, BALANCE_DAY,
                         [SfTxn(f"s{i}", d, c, desc) for i, (d, c, desc) in enumerate(JOINT_DAYS)])
    start = time.process_time()
    detect.find_candidate(db, incoming, "betterment", "Betterment", None)
    assert time.process_time() - start < 0.5
