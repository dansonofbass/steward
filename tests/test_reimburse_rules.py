"""Reimbursable spec, "Always reimbursable" and a repayment's payer: a rule marks the untouched matching rows now and
new rows at ingest, never a person's choice, a transfer or a business row; Reimbursement spread to matching deposits
takes the payer; Undo takes it all back."""
from datetime import date, datetime, timezone

from sqlalchemy import select

from steward.db.models import CategorySource, MerchantRule, ReimburseRule, Reimburser
from steward.services.importers.base import ParsedRow
from steward.services.ingest import ingest_rows
from tests.factories import login, make_account, make_txn, make_user

D = date(2026, 10, 3)
AT = datetime(2026, 10, 28, 17, 0, tzinfo=timezone.utc)


def _payer(db, name="Acme"):
    p = Reimburser(name=name, created_at=AT)
    db.add(p)
    db.commit()
    return p


def test_always_reimbursable_marks_untouched_matching_rows_never_a_persons_choice(client, db):
    make_user(db)
    login(client, "jr")
    acme = _payer(db)
    card = make_account(db, "Card", type="credit")
    t = make_txn(db, card, D, -40_000, "HILTON CHICAGO IL 0042", category="travel")
    two = make_txn(db, card, date(2026, 9, 3), -30_000, "HILTON CHICAGO IL 0040", category="travel")
    three = make_txn(db, card, date(2026, 8, 3), -30_000, "HILTON CHICAGO IL 0039", category="travel")
    said_no = make_txn(db, card, date(2026, 7, 3), -30_000, "HILTON CHICAGO IL 0038", category="travel")
    said_no.reimburse_source = "manual"
    biz = make_txn(db, card, date(2026, 6, 3), -30_000, "HILTON CHICAGO IL 0037", category="travel", business_pct=100)
    refund = make_txn(db, card, date(2026, 9, 9), 5_000, "HILTON CHICAGO IL 0041", category="travel")
    db.commit()
    r = client.post("/api/b/ours/reimburse/rules", json={"transaction_id": t.id})
    assert r.status_code == 201 and r.json()["also_marked"] == 2
    assert r.json()["rule"] == {"id": r.json()["rule"]["id"], "pattern": "HILTON CHICAGO IL", "reimburser_id": acme.id}
    db.rollback()
    assert (t.reimburser_id, t.reimburse_source) == (acme.id, "manual")
    assert [(x.reimburser_id, x.reimburse_source) for x in (two, three)] == [(acme.id, "rule")] * 2
    assert (said_no.reimburser_id, biz.reimburser_id, refund.reimburser_id) == (None, None, None)


def test_a_rule_needs_a_description_and_never_takes_a_transfer(client, db):
    make_user(db)
    login(client, "jr")
    _payer(db)
    a = make_account(db)
    blank = make_txn(db, a, D, -100, "*ABC")
    xfer = make_txn(db, a, D, -100, "PAYMENT THANK YOU", category="transfer", is_transfer=True)
    assert client.post("/api/b/ours/reimburse/rules", json={"transaction_id": blank.id}).json() == {
        "error": "This description has nothing a rule could match."}
    assert client.post("/api/b/ours/reimburse/rules", json={"transaction_id": xfer.id}).json() == {
        "error": "A transfer moves money between your own accounts, so it isn't reimbursable."}
    assert client.post("/api/b/ours/reimburse/rules", json={"transaction_id": 999}).status_code == 404


def test_a_rule_marks_new_charges_at_ingest_and_a_repayment_takes_its_payer(db):
    acme, globex = _payer(db, "Acme"), _payer(db, "Globex")
    db.add_all([ReimburseRule(pattern="HILTON CHICAGO IL", reimburser_id=acme.id, created_at=AT),
                ReimburseRule(pattern="GLOBEX EXPENSES", reimburser_id=globex.id, created_at=AT),
                MerchantRule(pattern="GLOBEX EXPENSES", merchant="Globex", category="reimbursement", is_business=None,
                             source=CategorySource.correction)])
    db.commit()
    new = ingest_rows(db, make_account(db), [ParsedRow(D, -40_000, "HILTON CHICAGO IL 0042", "a"),
                                             ParsedRow(D, 2_000, "HILTON CHICAGO IL 0043", "b"),
                                             ParsedRow(D, 90_000, "GLOBEX EXPENSES 7781", "c")],
                      batch=None, now=AT, model=None)
    db.commit()
    by = {t.external_id: t for t in new}
    assert (by["a"].reimburser_id, by["a"].reimburse_source) == (acme.id, "rule")
    assert by["b"].reimburser_id is None                  # money in that isn't a repayment: never by a rule
    assert (by["c"].category, by["c"].reimburser_id) == ("reimbursement", globex.id)


def test_with_one_payer_a_repayment_a_category_rule_sorted_takes_that_payer(db):
    acme = _payer(db)
    db.add(MerchantRule(pattern="ACME CORP EXP", merchant="Acme", category="reimbursement", is_business=None,
                        source=CategorySource.correction))
    db.commit()
    (t,) = ingest_rows(db, make_account(db), [ParsedRow(D, 50_000, "ACME CORP EXP", "a")], batch=None, now=AT,
                       model=None)
    assert t.reimburser_id == acme.id


def test_sorting_a_deposit_as_reimbursement_remembers_the_payer_spreads_it_and_undoes(client, db):
    make_user(db)
    login(client, "jr")
    _payer(db, "Acme")
    globex = _payer(db, "Globex")
    chk = make_account(db)
    t = make_txn(db, chk, D, 50_000, "GLOBEX EXPENSES 1")
    o = make_txn(db, chk, date(2026, 9, 3), 40_000, "GLOBEX EXPENSES 2")
    r = client.patch(f"/api/b/ours/transactions/{t.id}",
                     json={"category": "reimbursement", "reimburser_id": globex.id, "apply_to_matching": True})
    assert r.json()["result"]["applied"] == 1
    db.rollback()
    assert (t.reimburser_id, o.reimburser_id, o.category) == (globex.id, globex.id, "reimbursement")
    assert db.scalar(select(ReimburseRule.reimburser_id).where(ReimburseRule.pattern == "GLOBEX EXPENSES")) == globex.id
    assert client.post(f"/api/b/ours/undo/{r.json()['result']['undo']}").status_code == 200
    db.rollback()
    assert (t.reimburser_id, o.reimburser_id, o.category) == (None, None, "uncategorized")
    assert db.scalars(select(ReimburseRule)).all() == []


def test_a_spread_onto_transfer_takes_a_rule_mark_off(client, db):
    make_user(db)
    login(client, "jr")
    acme = _payer(db)
    a = make_account(db)
    t = make_txn(db, a, D, -40_000, "CHASE EPAY 0042")
    o = make_txn(db, a, date(2026, 9, 3), -40_000, "CHASE EPAY 0041")
    o.reimburser_id, o.reimburse_source = acme.id, "rule"
    db.commit()
    client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "transfer", "apply_to_matching": True})
    db.rollback()
    assert (o.category, o.reimburser_id) == ("transfer", None)


def test_posting_a_rule_is_one_action_and_undo_takes_the_marks_and_the_rule_back(client, db):
    make_user(db)
    login(client, "jr")
    acme = _payer(db)
    card = make_account(db, "Card", type="credit")
    t = make_txn(db, card, D, -40_000, "HILTON CHICAGO IL 0042", category="travel")
    two = make_txn(db, card, date(2026, 9, 3), -30_000, "HILTON CHICAGO IL 0040", category="travel")
    db.commit()
    r = client.post("/api/b/ours/reimburse/rules", json={"transaction_id": t.id})
    assert r.status_code == 201 and r.json()["also_marked"] == 1
    db.rollback()
    assert (t.reimburser_id, two.reimburser_id) == (acme.id, acme.id)
    assert client.post(f"/api/b/ours/undo/{r.json()['undo']}").status_code == 200
    db.rollback()
    assert (t.reimburser_id, two.reimburser_id) == (None, None)
    assert db.scalars(select(ReimburseRule)).all() == []


def test_a_spread_off_reimbursement_takes_the_payer_off_the_matching_deposit(client, db):
    make_user(db)
    login(client, "jr")
    acme = _payer(db)
    a = make_account(db)
    t = make_txn(db, a, D, 40_000, "ACME PAYROLL 0042")
    o = make_txn(db, a, date(2026, 9, 3), 40_000, "ACME PAYROLL 0041", category="reimbursement")
    o.reimburser_id, o.reimburse_source = acme.id, "rule"
    db.commit()
    client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "income", "apply_to_matching": True})
    db.rollback()
    assert (o.category, o.reimburser_id, o.trip_id) == ("income", None, None)


def test_ingest_leaves_a_manual_row_with_a_payer_alone(db):
    acme, globex = _payer(db), _payer(db, "Globex")
    a = make_account(db)
    db.add(ReimburseRule(pattern="HILTON CHICAGO IL", reimburser_id=globex.id, created_at=AT))
    t = make_txn(db, a, D, -40_000, "HILTON CHICAGO IL 0042")
    t.reimburser_id, t.reimburse_source = acme.id, "manual"
    db.commit()
    from steward.services.reimburse_rules import apply_rules
    assert apply_rules(db, [t]) == 0
    assert (t.reimburser_id, t.reimburse_source) == (acme.id, "manual")
