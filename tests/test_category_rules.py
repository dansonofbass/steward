"""Rows by rule pattern, and the examples the model is taught with (phase 12 decision 3, ruling 16)."""
from datetime import date, datetime, timezone

from steward.db.models import CategorySource, MerchantRule
from steward.services.category_rules import example_rules, pattern_counts, spread, spread_targets
from tests.factories import make_account, make_txn


def rule(db, pattern, category, source=CategorySource.correction, at=datetime(2026, 10, 1, tzinfo=timezone.utc)):
    r = MerchantRule(pattern=pattern, merchant=pattern.title(), category=category, is_business=None, source=source, created_at=at)
    db.add(r)
    db.commit()
    return r


def test_examples_never_teach_reimbursement(db):
    """The gateway refuses a batch whose examples carry a category the model may not answer: a repayment's rule would
    otherwise stop every batch."""
    db.add_all([MerchantRule(pattern="ACME CORP EXP", merchant="Acme", category="reimbursement", is_business=None,
                             source=CategorySource.correction),
                MerchantRule(pattern="HARBOR GRILL", merchant="Harbor Grill", category="dining", is_business=None,
                             source=CategorySource.correction)])
    db.commit()
    assert example_rules(db) == [("HARBOR GRILL", "dining")]


def test_pattern_counts_normalize_every_row(db):
    a = make_account(db)
    for raw in ("UNION SERVICE CENTER #12", "UNION SERVICE CENTER 10/03", "union service center", "HARBOR GRILL"):
        make_txn(db, a, date(2026, 10, 1), -100, raw)
    counts = pattern_counts(db)
    assert counts["UNION SERVICE CENTER"] == 3 and counts["HARBOR GRILL"] == 1 and counts["NOTHING"] == 0


def test_examples_are_the_households_corrections_most_rows_first_newest_on_ties(db):
    a = make_account(db)
    for raw, n in (("UNION SERVICE CENTER", 3), ("HARBOR GRILL", 2), ("BEAN CAFE", 2), ("ONLINE TRANSFER TO SAV", 5)):
        for i in range(n):
            make_txn(db, a, date(2026, 10, 1), -100, f"{raw} {i}")
    rule(db, "UNION SERVICE CENTER", "home")
    rule(db, "HARBOR GRILL", "dining", at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    rule(db, "BEAN CAFE", "dining", at=datetime(2026, 9, 2, tzinfo=timezone.utc))
    rule(db, "ONLINE TRANSFER TO SAV", "transfer")                 # the model can't answer transfer
    rule(db, "VANGUARD BUY", "investment")                         # nor investment
    rule(db, "COSTCO WHSE", "groceries", source=CategorySource.rule)   # not the household's correction
    assert example_rules(db) == [("UNION SERVICE CENTER", "home"), ("BEAN CAFE", "dining"), ("HARBOR GRILL", "dining")]
    assert example_rules(db, limit=2) == [("UNION SERVICE CENTER", "home"), ("BEAN CAFE", "dining")]


def test_spread_targets_are_exactly_ruling_12s_rows(db):
    chk = make_account(db)
    sav = make_account(db, "Savings", type="savings", institution_name="Other")
    ira = make_account(db, "Roth", type="roth_ira", institution_name="Robo")
    r = rule(db, "UNION SERVICE CENTER", "home")
    d = date(2026, 9, 1)
    yes = [make_txn(db, chk, d, -8000, "UNION SERVICE CENTER 1"),
           make_txn(db, chk, d, -8000, "UNION SERVICE CENTER 2", category="shopping", category_source=CategorySource.model),
           make_txn(db, chk, d, -8000, "UNION SERVICE CENTER 3", category="shopping", category_source=CategorySource.rule)]
    yes[0].guess_category, yes[0].guess_pct = "shopping", 40
    no = [make_txn(db, chk, d, -8000, "UNION SERVICE CENTER 4", category="gifts", category_source=CategorySource.correction),
          make_txn(db, chk, d, -8000, "UNION SERVICE CENTER 5"),                                   # reviewed below
          make_txn(db, chk, d, -8000, "UNION SERVICE CENTER 6", is_transfer=True, category="transfer", category_source=CategorySource.rule),
          make_txn(db, ira, d, -8000, "UNION SERVICE CENTER 7", category="investment", category_source=CategorySource.rule),
          make_txn(db, chk, d, -8000, "UNION SERVICE CENTER 8", category="home", category_source=CategorySource.rule),   # already home
          make_txn(db, chk, d, -8000, "UNION SERVICE", ),                                           # another pattern
          make_txn(db, sav, d, 8000, "UNION SERVICE CENTER 9")]                                    # paired below
    no[1].reviewed_at = datetime(2026, 9, 2, tzinfo=timezone.utc)
    no[6].transfer_peer_id = no[2].id
    db.commit()
    assert sorted(t.id for t in spread_targets(db, r)) == sorted(t.id for t in yes)
    at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert spread(db, r, at) == sorted(t.id for t in yes)
    db.commit()
    for t in yes:
        db.refresh(t)
        assert (t.category, t.category_source, t.merchant, t.reviewed_at) == ("home", CategorySource.correction, "Union Service Center", at)
        assert t.guess_category is None and t.guess_pct is None
    for t in no:
        db.refresh(t)
        assert t.category_source != CategorySource.correction or t.category == "gifts"


def test_spreading_a_transfer_rule_pairs_the_rows(db):
    chk = make_account(db)
    card = make_account(db, "Card", type="credit", institution_name="Other")
    r = rule(db, "CHASE EPAY", "transfer")
    out = make_txn(db, chk, date(2026, 9, 5), -40000, "CHASE EPAY 0042")
    back = make_txn(db, card, date(2026, 9, 7), 40000, "PAYMENT RECEIVED")
    assert spread(db, r, datetime(2026, 10, 1, tzinfo=timezone.utc)) == [out.id]
    db.commit()
    db.refresh(out); db.refresh(back)
    assert out.is_transfer and out.transfer_peer_id == back.id and back.category == "transfer"


from sqlalchemy import event

from steward.services.category_rules import matching_counts


def test_matching_is_spread_targets_without_the_category_condition(db):
    """Spec, The matching count: the same set spread_targets uses, minus its category condition, minus the row itself."""
    chk = make_account(db)
    ira = make_account(db, "Roth", type="roth_ira", institution_name="Robo")
    d = date(2026, 9, 1)
    me = make_txn(db, chk, d, -8000, "UNION SERVICE CENTER 0")
    make_txn(db, chk, d, -8000, "UNION SERVICE CENTER 1")
    make_txn(db, chk, d, -8000, "UNION SERVICE CENTER 2", category="shopping", category_source=CategorySource.model)
    make_txn(db, chk, d, -8000, "UNION SERVICE CENTER 3", category="home", category_source=CategorySource.rule)
    make_txn(db, chk, d, -8000, "union  service center 7")                                     # case and spaces fold
    make_txn(db, chk, d, -8000, "UNION SERVICE CENTER 4", category="gifts", category_source=CategorySource.correction)
    make_txn(db, chk, d, -8000, "UNION SERVICE CENTER 5", is_transfer=True, category="transfer",
             category_source=CategorySource.rule)
    make_txn(db, ira, d, -8000, "UNION SERVICE CENTER 6", category="investment", category_source=CategorySource.rule)
    make_txn(db, chk, d, -8000, "UNION SERVICE")                                                # another pattern
    seen = make_txn(db, chk, d, -8000, "UNION SERVICE CENTER 8")
    seen.reviewed_at = datetime(2026, 9, 2, tzinfo=timezone.utc)
    db.commit()
    # A rule in a category no row has: spread_targets is then exactly the reachable rows, this one included.
    probe = MerchantRule(pattern="UNION SERVICE CENTER", merchant="x", category="kids", is_business=None,
                         source=CategorySource.correction)
    assert matching_counts(db, [me])[me.id] == len(spread_targets(db, probe)) - 1 == 4


def test_matching_counts_a_page_in_one_query(db, engine):
    a = make_account(db)
    rows = [make_txn(db, a, date(2026, 10, d), -100, f"SHOP {'ABC'[d % 3]} 00{d}") for d in range(1, 10)]
    for t in rows:
        t.raw_description                                   # loaded now, so only the count's own query is seen
    seen: list[str] = []

    def count(_conn, _cursor, statement, *_args):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        counts = matching_counts(db, rows)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    # The engine's own BEGIN (db/engine.py) isn't a query; the page's count is exactly one SELECT.
    assert len([s for s in seen if s.lstrip().upper().startswith("SELECT")]) == 1
    assert counts[rows[0].id] == 2                          # "SHOP B": rows 1, 4 and 7


def test_an_unnormalizable_description_has_no_matching_count(db):
    """Review Focus 3: no rule can be made for it, so nothing would be remembered."""
    a = make_account(db)
    star = make_txn(db, a, date(2026, 10, 1), -100, "*ABC")
    make_txn(db, a, date(2026, 10, 2), -100, "*ABC")
    assert matching_counts(db, [star]) == {star.id: None}
