"""The synthetic parent's flags (spec 11; README "Margaret's flags"), raised by the real checks over the seed."""
import json
from collections import Counter
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from steward.db.models import Flag, WatchKnown
from steward.demo_parent import seed_parent
from steward.demo_watching import seed_watching
from steward.watch.due import latest_due
from steward.watch.store import also_of

TODAY = date(2026, 10, 19)


def test_margarets_flags_match_the_mockup(margaret, mdb, mctx):
    seed_parent(mdb, TODAY, by=mctx.user_id)
    ids = seed_watching(mdb, TODAY, by=mctx.user_id)
    flags = {k: mdb.get(Flag, v) for k, v in ids.items()}
    assert len(list(mdb.scalars(select(Flag)))) == 9
    assert Counter(f.status for f in flags.values()) == {"open": 5, "checking": 1, "expected": 1, "handled": 2}
    assert sorted(k for k, f in flags.items() if f.severity == "urgent") == ["gift", "premium", "zelle"]
    assert [(k, flags[k].check, flags[k].summary) for k in ids] == [
        ("gift", "scam", "$500.00 gift card at CVS Pharmacy"),
        ("premium", "premium", "the Evergreen Mutual long-term care premium hasn't left Joint checking"),
        ("zelle", "payee", "$1,200.00 by Zelle to J. Smith"),
        ("low", "low", "Way2Save savings is under its $25,000.00 floor"),
        ("streambox", "monthly", "StreamBox, $15.99 on Sep 18 and Oct 18"),
        ("ralphs", "duplicate", "$64.18 at Ralphs on Oct 13 and again on Oct 14"),
        ("dentist", "large", "$640.00 to Brea Family Dental"),
        ("clearpath", "duplicate", "$38.40 at Clearpath Rx on Sep 18 and again on Sep 19"),
        ("puzzle", "monthly", "Daily Puzzle Club, $9.99 on Aug 3 and Sep 3"),
    ]
    assert [a["check"] for a in also_of(flags["gift"])] == ["large"]
    assert flags["premium"].due_on == date(2026, 10, 12)
    assert flags["ralphs"].note == "Asked Margaret about two trips to Ralphs. Waiting to hear back."
    assert (flags["dentist"].status, flags["dentist"].note) == ("expected", "Margaret's crown. Margaret told me about it on Sunday.")
    [k] = mdb.scalars(select(WatchKnown)).all()
    assert (k.payee_name, k.low_cents, k.high_cents) == ("Brea Family Dental", 48_000, 80_000)
    assert json.loads(flags["low"].facts)["balance_cents"] == 2_248_010


SHAPE = {("duplicate", "checking", "normal"): 1, ("duplicate", "handled", "normal"): 1,
         ("large", "expected", "normal"): 1, ("low", "open", "normal"): 1, ("monthly", "handled", "normal"): 1,
         ("monthly", "open", "normal"): 1, ("payee", "open", "urgent"): 1, ("premium", "open", "urgent"): 1,
         ("scam", "open", "urgent"): 1}


@pytest.mark.parametrize("today", [date(2026, 10, 1) + timedelta(days=n) for n in range(0, 62, 3)] + [date(2026, 10, 3), date(2026, 11, 15)])
def test_margarets_flags_are_the_same_whatever_day_it_is(margaret, mdb, mctx, today):
    """The e2e seed runs on today's date. The premium's due date moves when the 10th is a weekend, and Globe Mutual's
    payments move with the 15th, but the same nine flags in the same states come out."""
    seed_parent(mdb, today, by=mctx.user_id)
    ids = seed_watching(mdb, today, by=mctx.user_id)
    flags = list(mdb.scalars(select(Flag)))
    assert dict(Counter((f.check, f.status, f.severity) for f in flags)) == SHAPE
    assert sorted(ids) == sorted(["gift", "premium", "zelle", "low", "streambox", "ralphs", "dentist", "clearpath", "puzzle"])
    assert mdb.get(Flag, ids["premium"]).due_on == latest_due(10, today)[1]
