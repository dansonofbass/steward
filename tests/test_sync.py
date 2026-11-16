from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from steward.db.models import Account, AccountType, BalanceSnapshot, EventLog, Holding, Institution, SimplefinLink, Source, Transaction
from steward.events import log_event
from steward.services.simplefin.client import claim
from steward.services.simplefin.sync import LINK_PROBLEM_MSG, NEW_BANK_MSG, dismiss_sync_warning, run_sync
from tests.fake_simplefin import make_fake

H = ("testserver",)
NOW = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)
E = lambda y, m, d, h=19: int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp())  # noqa: E731


def _link(db, http):
    access = claim(http, "http://testserver/claim/abc", allowed_hosts=H)
    link = SimplefinLink(access_url=access, claimed_at=NOW)
    db.add(link); db.commit()
    return link


def _household(state):
    state.add_account("big", "Big Bank", "bigbank", "chk", 1450_00, E(2026, 10, 12), txns=[
        ("t1", E(2026, 10, 1), 4120_00, "PAYROLL ACME CORP"), ("t2", E(2026, 10, 5), -1000_00, "ONLINE TRANSFER TO SAV")])
    state.add_account("big", "Big Bank", "bigbank", "sav", 2200_00, E(2026, 10, 12), txns=[
        ("t3", E(2026, 10, 5), 1000_00, "ONLINE TRANSFER FROM CHK")])
    state.add_account("marcus", "Marcus", "marcus", "hy", 6500_00, E(2026, 10, 13, 2), txns=[])  # 02:00Z → Oct 12 Pacific


def test_first_sync_creates_everything(db):
    app, state = make_fake(); _household(state)
    with TestClient(app) as http:
        link = _link(db, http)
        res = run_sync(db, http, link, NOW, model=None, allowed_hosts=H)
    db.commit()
    assert (res.institutions_ok, res.institutions_failed, res.accounts_new, res.transactions_new) == (2, 0, 3, 3)
    insts = {i.simplefin_org_id: i for i in db.scalars(select(Institution)).all()}
    assert insts["big"].name == "Big Bank" and insts["big"].last_sync_at == NOW and insts["big"].last_error is None
    accts = {a.external_id: a for a in db.scalars(select(Account)).all()}
    assert accts["sfin:chk"].type == AccountType.unknown and accts["sfin:hy"].institution.name == "Marcus"
    assert db.get(BalanceSnapshot, (accts["sfin:hy"].id, date(2026, 10, 12))).balance_cents == 6500_00
    t = {x.external_id: x for x in db.scalars(select(Transaction)).all()}
    assert t["t2"].is_transfer and t["t2"].transfer_peer_id == t["t3"].id
    assert t["t1"].category == "income"
    msgs = [e.message for e in db.scalars(select(EventLog).where(EventLog.actionable.is_(True)))]
    assert sum("needs its type and owner" in m for m in msgs) == 3
    assert state.calls[0].get("start-date") == str(int((NOW - timedelta(days=89)).timestamp()))
    assert link.last_sync_at == NOW


def test_a_sync_matches_new_payments_to_set_asides_and_says_so(db):
    """Phase 11c: sync_now runs matching for a household book and logs one summary event. The synced account is
    made first and typed checking (a new account arrives as `unknown`, which is not a cash account, so its rows
    would not be candidates)."""
    from steward.db.models import SetAside, SetAsideMatch
    from steward.services.simplefin.sync import sync_now
    from tests.factories import make_account
    from tests.setaside_fixtures import AT
    app, state = make_fake(); _household(state)
    state.accounts[0].txns.append(("t7", E(2026, 8, 14), -1860_00, "SAFEGUARD INSURANCE"))
    acct = make_account(db, "Checking", type="checking", source="simplefin", institution_name="Big Bank")
    acct.external_id = "sfin:chk"
    acct.institution.simplefin_org_id = "big"
    db.add(SetAside(name="Car insurance", kind="yearly", amount_cents=186_000, due_month=8, due_day=14, first_month=date(2026, 1, 1),
                    payee_key="SAFEGUARD INSURANCE", category="insurance", created_at=AT, updated_at=AT))
    db.commit()
    with TestClient(app) as http:
        _link(db, http)
        res = sync_now(db.get_bind(), http, None, NOW, H)
    assert (res.accounts_new, res.transactions_new) == (2, 4)
    t = db.scalar(select(Transaction).where(Transaction.external_id == "t7"))
    m = db.scalar(select(SetAsideMatch).where(SetAsideMatch.transaction_id == t.id))
    assert (m.how, m.due_on, m.late) == ("auto", date(2026, 8, 14), False)
    msgs = [e.message for e in db.scalars(select(EventLog).where(EventLog.kind == "setaside"))]
    assert msgs == ["Steward matched 1 payment to set-asides: Car insurance (Aug 14, 2026)."]


def test_second_sync_adds_only_new_and_overlaps_7_days(db):
    app, state = make_fake(); _household(state)
    with TestClient(app) as http:
        link = _link(db, http)
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
        state.accounts[0].txns.append(("t9", E(2026, 10, 11), -12_34, "BEAN & LEAF 0031"))
        later = NOW + timedelta(days=1)
        res = run_sync(db, http, link, later, model=None, allowed_hosts=H); db.commit()
    assert res.transactions_new == 1 and res.accounts_new == 0
    assert state.calls[1]["start-date"] == str(int((NOW - timedelta(days=7)).timestamp()))
    assert db.scalar(select(func.count()).select_from(Transaction)) == 4


def test_one_institution_failing_leaves_others_synced_and_old_rows_intact(db):
    app, state = make_fake(); _household(state)
    with TestClient(app) as http:
        link = _link(db, http)
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
        state.fail_conn = "marcus"
        state.accounts[0].txns.append(("t9", E(2026, 10, 11), -12_34, "BEAN & LEAF 0031"))
        res = run_sync(db, http, link, NOW + timedelta(days=1), model=None, allowed_hosts=H); db.commit()
    assert (res.institutions_ok, res.institutions_failed, res.transactions_new) == (1, 1, 1)
    marcus = db.scalar(select(Institution).where(Institution.simplefin_org_id == "marcus"))
    assert marcus.last_error == "Marcus needs you to sign in again at SimpleFIN"
    assert marcus.last_sync_at == NOW  # unchanged
    hy = db.scalar(select(Account).where(Account.external_id == "sfin:hy"))
    assert hy is not None and hy.institution_id == marcus.id  # Marcus's account row survives
    assert db.get(BalanceSnapshot, (hy.id, date(2026, 10, 12))).balance_cents == 6500_00  # and its snapshot
    assert db.scalar(select(func.count()).select_from(BalanceSnapshot)) == 3
    ev = db.scalars(select(EventLog).where(EventLog.kind == "sync", EventLog.resolved_at.is_(None))).all()
    assert [e.message for e in ev] == ["Marcus needs you to sign in again at SimpleFIN"]
    # a third run with the same failure doesn't duplicate the event
    with TestClient(app) as http:
        run_sync(db, http, link, NOW + timedelta(days=2), model=None, allowed_hosts=H); db.commit()
    assert db.scalar(select(func.count()).select_from(EventLog).where(EventLog.kind == "sync", EventLog.resolved_at.is_(None))) == 1
    # recovery resolves it
    state.fail_conn = None
    with TestClient(app) as http:
        run_sync(db, http, link, NOW + timedelta(days=3), model=None, allowed_hosts=H); db.commit()
    assert db.scalar(select(func.count()).select_from(EventLog).where(EventLog.kind == "sync", EventLog.resolved_at.is_(None))) == 0


def test_revoked_access_sets_link_error(db):
    app, state = make_fake(); _household(state)
    with TestClient(app) as http:
        link = _link(db, http)
        link.access_url = "http://bad:creds@testserver/simplefin"
        res = run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
    assert res.institutions_failed == 0 and "revoked" in link.last_error and link.last_sync_at is None
    assert db.scalar(select(func.count()).select_from(EventLog).where(EventLog.actionable.is_(True))) == 1


def test_pending_rows_skipped(db):
    app, state = make_fake()
    state.add_account("big", "Big Bank", "bigbank", "chk", 0, E(2026, 10, 12), txns=[("p", 0, -5_00, "PENDING", True)])
    with TestClient(app) as http:
        link = _link(db, http)
        res = run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
    assert res.transactions_new == 0 and db.scalar(select(func.count()).select_from(Transaction)) == 0


def test_connection_error_keeps_session_rows_and_counts_only_successes(db):
    app, state = make_fake(); _household(state)
    state.errlist.append({"code": "steward.parse", "msg": "bad account", "conn_id": "marcus"})
    with TestClient(app) as http:
        link = _link(db, http)
        res = run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
    assert (res.institutions_ok, res.institutions_failed, res.accounts_new, res.transactions_new) == (1, 1, 2, 3)
    assert db.scalar(select(func.count()).select_from(Account)) == 2  # marcus' account was not created


def test_exception_rolls_back_only_that_connection(db, monkeypatch):
    import steward.services.simplefin.sync as sync
    real = sync.record_balance

    def boom(db_, account_id, as_of, cents):
        if cents == 6500_00:
            raise RuntimeError("disk full")
        return real(db_, account_id, as_of, cents)
    monkeypatch.setattr(sync, "record_balance", boom)
    app, state = make_fake(); _household(state)
    with TestClient(app) as http:
        link = _link(db, http)
        res = run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
    assert (res.institutions_ok, res.institutions_failed, res.accounts_new) == (1, 1, 2)
    marcus = db.scalar(select(Institution).where(Institution.simplefin_org_id == "marcus"))
    assert marcus.last_error == "Marcus couldn't be synced. Steward will try again at the next sync."
    assert "disk full" not in marcus.last_error and marcus.last_sync_at is None
    assert db.scalar(select(func.count()).select_from(Account).where(Account.external_id == "sfin:hy")) == 0
    assert link.last_sync_at == NOW


def test_gateway_event_dedupes_and_resolves(db):
    from steward.services.categorizer_client import HttpModelClient
    app, state = make_fake(); _household(state)
    model = HttpModelClient.__new__(HttpModelClient)
    model.last_error = "unreachable"
    q = select(EventLog).where(EventLog.message == "The gateway is off, so categorization is paused", EventLog.resolved_at.is_(None))
    with TestClient(app) as http:
        link = _link(db, http)
        run_sync(db, http, link, NOW, model=model, allowed_hosts=H)
        run_sync(db, http, link, NOW + timedelta(days=1), model=model, allowed_hosts=H)
        assert len(db.scalars(q).all()) == 1
        model.last_error = None
        run_sync(db, http, link, NOW + timedelta(days=2), model=model, allowed_hosts=H)
        assert db.scalars(q).all() == []


def test_second_run_rollback_undoes_successful_connections(db):
    """SAVEPOINT must not commit the outer transaction when only SELECTs came first."""
    import steward.services.simplefin.sync as sync
    app, state = make_fake(); _household(state)
    with TestClient(app) as http:
        link = _link(db, http)
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
        state.accounts[0].txns.append(("t9", E(2026, 10, 11), -12_34, "BEAN & LEAF 0031"))
        real = sync.record_balance
        sync.record_balance = lambda d, i, a, c: (_ for _ in ()).throw(RuntimeError("x")) if c == 6500_00 else real(d, i, a, c)
        try:
            res = run_sync(db, http, link, NOW + timedelta(days=1), model=None, allowed_hosts=H)
        finally:
            sync.record_balance = real
        assert (res.institutions_ok, res.institutions_failed, res.transactions_new) == (1, 1, 1)
        db.rollback()
    assert db.scalar(select(func.count()).select_from(Transaction)) == 3
    assert db.get(SimplefinLink, link.id).last_sync_at == NOW


def test_errors_without_connection_land_on_the_link(db):
    app, state = make_fake(); _household(state)
    state.errlist.append({"code": "gen.auth", "msg": "Something odd", "conn_id": None})
    with TestClient(app) as http:
        link = _link(db, http)
        res = run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
        assert link.last_error == LINK_PROBLEM_MSG
        assert LINK_PROBLEM_MSG in res.errors and res.institutions_ok == 2
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
        assert db.scalar(select(func.count()).select_from(EventLog).where(
            EventLog.message == LINK_PROBLEM_MSG, EventLog.resolved_at.is_(None))) == 1
        state.errlist.clear()
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
    assert link.last_error is None
    assert db.scalar(select(func.count()).select_from(EventLog).where(
        EventLog.message.startswith("SimpleFIN "), EventLog.resolved_at.is_(None))) == 0


def test_unplaceable_account_is_reported(db):
    app, state = make_fake()
    state.add_account("big", "Big Bank", "bigbank", "chk", 1_00, E(2026, 10, 12))
    state.add_account("ghost", "Ghost", "ghost", "g1", 1_00, E(2026, 10, 12))
    orig = state.payload
    state.payload = lambda start, pending: {**orig(start, pending), "connections": [
        c for c in orig(start, pending)["connections"] if c["conn_id"] != "ghost"]}
    with TestClient(app) as http:
        link = _link(db, http)
        res = run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
    msg = "SimpleFIN sent an account Steward couldn't place: g1"
    assert msg in res.errors and res.institutions_ok == 1
    assert db.scalar(select(func.count()).select_from(EventLog).where(EventLog.message == msg)) == 1


def test_window_reaches_back_to_the_stalest_institution(db):
    app, state = make_fake(); _household(state)
    with TestClient(app) as http:
        link = _link(db, http)
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
        big = db.scalar(select(Institution).where(Institution.simplefin_org_id == "big"))
        big.last_sync_at = NOW - timedelta(days=20)
        link.last_sync_at = NOW - timedelta(hours=1)
        db.commit()
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H)
    assert state.calls[-1]["start-date"] == str(int((NOW - timedelta(days=27)).timestamp()))


def test_window_after_the_first_pull_is_capped_at_44_days(db):
    app, state = make_fake(); _household(state)
    with TestClient(app) as http:
        link = _link(db, http)
        link.last_sync_at = NOW - timedelta(days=200)
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H)
    assert state.calls[-1]["start-date"] == str(int((NOW - timedelta(days=44)).timestamp()))


def test_a_connection_that_never_synced_does_not_widen_the_window(db):
    """JR's three failing connections have no good sync; they must not make every sync ask for 90 days."""
    app, state = make_fake(); _household(state)
    with TestClient(app) as http:
        link = _link(db, http)
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
        db.add(Institution(name="Never", source=Source.simplefin, simplefin_org_id="never", last_error="x"))
        link.last_sync_at = NOW - timedelta(hours=1)
        db.commit()
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H)
    assert state.calls[-1]["start-date"] == str(int((NOW - timedelta(hours=1, days=7)).timestamp()))


def test_a_stale_connection_widens_the_window_only_to_the_cap(db):
    app, state = make_fake(); _household(state)
    with TestClient(app) as http:
        link = _link(db, http)
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
        big = db.scalar(select(Institution).where(Institution.simplefin_org_id == "big"))
        big.last_sync_at = NOW - timedelta(days=60)
        link.last_sync_at = NOW - timedelta(hours=1)
        db.commit()
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H)
    assert state.calls[-1]["start-date"] == str(int((NOW - timedelta(days=44)).timestamp()))


def test_recommended_range_notice_is_logged_not_shown(db, caplog):
    app, state = make_fake(); _household(state)
    state.errlist.append({"code": "gen.range", "conn_id": None,
                          "msg": "Requested date range exceeds recommended range of 45 days"})
    with TestClient(app) as http:
        link = _link(db, http)
        with caplog.at_level("INFO", logger="steward.services.simplefin.sync"):
            res = run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
    assert link.last_error is None and res.errors == [] and res.institutions_ok == 2
    assert db.scalar(select(func.count()).select_from(EventLog).where(EventLog.kind == "sync")) == 0
    assert "exceeds recommended range" in caplog.text


def test_link_level_problem_is_a_plain_line_with_the_raw_text_only_in_the_log(db, caplog):
    app, state = make_fake(); _household(state)
    state.errlist.append({"code": "gen.weird", "msg": "Internal server glitch 0x1F", "conn_id": None})
    with TestClient(app) as http:
        link = _link(db, http)
        with caplog.at_level("WARNING", logger="steward.services.simplefin.sync"):
            res = run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
    assert link.last_error == LINK_PROBLEM_MSG and res.errors == [LINK_PROBLEM_MSG]
    assert "0x1F" not in link.last_error and "0x1F" in caplog.text


def test_recovery_does_not_resolve_a_longer_institution_name(db):
    app, state = make_fake()
    state.add_account("c1", "Chase", "chase", "a", 1_00, E(2026, 10, 12))
    with TestClient(app) as http:
        link = _link(db, http)
        log_event(db, "warn", "sync", "Chase Business needs you to sign in again at SimpleFIN", actionable=True)
        log_event(db, "warn", "sync", "Chase needs you to sign in again at SimpleFIN", actionable=True)
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
    open_ = [e.message for e in db.scalars(select(EventLog).where(EventLog.kind == "sync", EventLog.resolved_at.is_(None)))]
    assert open_ == ["Chase Business needs you to sign in again at SimpleFIN"]


def test_an_error_for_a_connection_steward_has_never_seen_is_logged_not_shown(db, caplog):
    """JR's "A bank connection (MBR-...) needs you to sign in again": SimpleFIN still lists an old connection with
    no name and no accounts here. Nothing for a person to do, so no row and no warning."""
    app, state = make_fake(); _household(state)
    state.fail_conn = "marcus"
    with TestClient(app) as http:
        link = _link(db, http)
        with caplog.at_level("WARNING", logger="steward.services.simplefin.sync"):
            res = run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
    assert db.scalar(select(Institution).where(Institution.simplefin_org_id == "marcus")) is None
    assert (res.institutions_ok, res.institutions_failed, res.errors) == (1, 0, [])
    assert db.scalar(select(func.count()).select_from(EventLog).where(EventLog.kind == "sync")) == 0
    assert "marcus" in caplog.text and "old connection" in caplog.text


def test_a_failing_connection_with_no_accounts_here_is_not_a_warning(db):
    app, state = make_fake(); _household(state)
    db.add(Institution(name="Old Credit Union", source=Source.simplefin, simplefin_org_id="marcus")); db.commit()
    state.fail_conn = "marcus"
    with TestClient(app) as http:
        link = _link(db, http)
        res = run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
    m = db.scalar(select(Institution).where(Institution.simplefin_org_id == "marcus"))
    assert m.last_error == "Old Credit Union needs you to sign in again at SimpleFIN"  # Banks still says why
    assert (res.institutions_failed, res.errors) == (0, [])
    assert db.scalar(select(func.count()).select_from(EventLog).where(EventLog.kind == "sync")) == 0


def test_a_dismissed_warning_stays_dismissed_until_the_error_changes_or_clears(db):
    app, state = make_fake(); _household(state)
    unresolved = select(EventLog.message).where(EventLog.kind == "sync", EventLog.resolved_at.is_(None))
    with TestClient(app) as http:
        link = _link(db, http)
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
        state.fail_conn = "marcus"
        run_sync(db, http, link, NOW + timedelta(days=1), model=None, allowed_hosts=H); db.commit()
        msg = "Marcus needs you to sign in again at SimpleFIN"
        assert db.scalars(unresolved).all() == [msg]
        ev = db.scalar(select(EventLog).where(EventLog.message == msg))
        dismiss_sync_warning(db, ev, NOW + timedelta(days=1, hours=1)); db.commit()
        marcus = db.scalar(select(Institution).where(Institution.simplefin_org_id == "marcus"))
        assert ev.resolved_at is not None and marcus.dismissed_error == msg
        res = run_sync(db, http, link, NOW + timedelta(days=2), model=None, allowed_hosts=H); db.commit()
        assert db.scalars(unresolved).all() == [] and res.institutions_failed == 1  # still failing, not nagging
        # a different error for the same connection is news again
        state.fail_conn = None
        state.errlist.append({"code": "act.other", "msg": "Weird upstream text", "conn_id": "marcus"})
        run_sync(db, http, link, NOW + timedelta(days=3), model=None, allowed_hosts=H); db.commit()
        assert db.scalars(unresolved).all() == ["Marcus: SimpleFIN reported a problem with this connection. Steward will try again at the next sync."]
        assert marcus.dismissed_error is None and "Weird" not in marcus.last_error
        # recovery clears everything
        state.errlist.clear()
        run_sync(db, http, link, NOW + timedelta(days=4), model=None, allowed_hosts=H); db.commit()
        assert db.scalars(unresolved).all() == [] and marcus.last_error is None
        # the same error coming back after a recovery is news again
        state.fail_conn = "marcus"
        run_sync(db, http, link, NOW + timedelta(days=5), model=None, allowed_hosts=H); db.commit()
        assert db.scalars(unresolved).all() == [msg]


def test_connection_error_prefers_con_code_and_repeated_txn_ids_are_ignored(db):
    app, state = make_fake()
    state.add_account("big", "Big Bank", "bigbank", "chk", 1_00, E(2026, 10, 12), txns=[
        ("d", E(2026, 10, 1), -1_00, "X"), ("d", E(2026, 10, 1), -1_00, "X")])
    state.add_account("m", "Marcus", "m", "hy", 1_00, E(2026, 10, 12))
    state.errlist.append({"code": "act.other", "msg": "odd", "conn_id": "m"})
    state.errlist.append({"code": "con.auth", "msg": "re-auth", "conn_id": "m"})
    with TestClient(app) as http:
        link = _link(db, http)
        res = run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
    assert res.transactions_new == 1
    marcus = db.scalar(select(Institution).where(Institution.simplefin_org_id == "m"))
    assert marcus.last_error == "Marcus needs you to sign in again at SimpleFIN"
    assert res.errors == []  # no accounts here depend on Marcus yet, so Home doesn't warn


def test_persisting_link_problem_keeps_one_event_row(db):
    app, state = make_fake(); _household(state)
    state.errlist.append({"code": "gen.auth", "msg": "Something odd", "conn_id": None})
    with TestClient(app) as http:
        link = _link(db, http)
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
    assert db.scalar(select(func.count()).select_from(EventLog).where(
        EventLog.message == LINK_PROBLEM_MSG)) == 1


def test_capped_range_notice_is_one_info_event_not_a_link_problem(db):
    app, state = make_fake(); _household(state)
    state.errlist.append({"code": "gen.range", "conn_id": None,
                          "msg": "Requested date range exceeds limit of 90 days and was capped"})
    with TestClient(app) as http:
        link = _link(db, http)
        for _ in range(2):
            res = run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
    assert link.last_error is None and res.errors == [] and res.institutions_ok == 2
    evs = db.scalars(select(EventLog).where(EventLog.message.like("SimpleFIN limited%"))).all()
    assert len(evs) == 1 and evs[0].level == "info" and evs[0].actionable is False


def test_real_link_error_still_shows_beside_a_capped_notice(db):
    app, state = make_fake(); _household(state)
    state.errlist.append({"code": "gen.range", "conn_id": "bigbank", "msg": "Date range EXCEEDS LIMIT, CAPPED"})
    state.errlist.append({"code": "gen.auth", "msg": "Something odd", "conn_id": None})
    with TestClient(app) as http:
        link = _link(db, http)
        res = run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
    assert link.last_error == LINK_PROBLEM_MSG
    assert res.institutions_failed == 0


def test_a_sign_in_warning_for_a_connection_with_no_accounts_here_is_resolved(db):
    """A warning an older Steward raised for a connection with no accounts here (JR's three "A bank connection (MBR-...)"
    rows) goes away on the next sync instead of staying open on Home."""
    app, state = make_fake(); _household(state)
    msg = "Old Credit Union needs you to sign in again at SimpleFIN"
    db.add(Institution(name="Old Credit Union", source=Source.simplefin, simplefin_org_id="marcus", last_error=msg))
    log_event(db, "warn", "sync", msg, actionable=True); db.commit()
    state.fail_conn = "marcus"
    with TestClient(app) as http:
        link = _link(db, http)
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
    assert db.scalar(select(func.count()).select_from(EventLog).where(
        EventLog.kind == "sync", EventLog.resolved_at.is_(None))) == 0


def test_a_dismissed_sync_failure_stays_dismissed_while_it_keeps_failing(db, monkeypatch):
    import steward.services.simplefin.sync as sync
    real = sync.record_balance
    monkeypatch.setattr(sync, "record_balance",
                        lambda d, i, a, c: (_ for _ in ()).throw(RuntimeError("x")) if c == 6500_00 else real(d, i, a, c))
    app, state = make_fake(); _household(state)
    unresolved = select(EventLog.message).where(EventLog.kind == "sync", EventLog.resolved_at.is_(None))
    msg = "Marcus couldn't be synced. Steward will try again at the next sync."
    with TestClient(app) as http:
        link = _link(db, http)
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
        assert db.scalars(unresolved).all() == [msg]
        ev = db.scalar(select(EventLog).where(EventLog.message == msg))
        dismiss_sync_warning(db, ev, NOW + timedelta(hours=1)); db.commit()
        res = run_sync(db, http, link, NOW + timedelta(days=1), model=None, allowed_hosts=H); db.commit()
        assert db.scalars(unresolved).all() == [] and res.institutions_failed == 1  # still failing, not nagging
        monkeypatch.setattr(sync, "record_balance", real)
        run_sync(db, http, link, NOW + timedelta(days=2), model=None, allowed_hosts=H); db.commit()
    marcus = db.scalar(select(Institution).where(Institution.simplefin_org_id == "marcus"))
    assert marcus.last_error is None and marcus.dismissed_error is None


def test_a_bank_added_after_the_first_pull_gets_45_days_and_the_log_says_so(db):
    app, state = make_fake()
    state.add_account("big", "Big Bank", "bigbank", "chk", 1_00, E(2026, 10, 12))
    with TestClient(app) as http:
        link = _link(db, http)
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
        state.add_account("marcus", "Marcus", "marcus", "hy", 1_00, E(2026, 12, 11))
        later = NOW + timedelta(days=60)
        res = run_sync(db, http, link, later, model=None, allowed_hosts=H); db.commit()
        run_sync(db, http, link, later + timedelta(days=1), model=None, allowed_hosts=H); db.commit()
    assert res.accounts_new == 1
    assert state.calls[1]["start-date"] == str(int((later - timedelta(days=44)).timestamp()))
    evs = db.scalars(select(EventLog).where(EventLog.message == NEW_BANK_MSG.format(name="Marcus"))).all()
    assert len(evs) == 1 and evs[0].level == "info" and evs[0].kind == "sync" and evs[0].actionable is False
    assert db.scalar(select(func.count()).select_from(EventLog).where(EventLog.message.like("Big Bank is new%"))) == 0


def test_a_bank_back_after_more_than_the_window_says_older_transactions_may_be_missing(db):
    """Review of this branch: with the 44-day cap, a bank out of reach for 60 days comes back without days 44 to 60.
    The person is told once, on Home, with what to do; a bank that was away less than the window isn't mentioned."""
    from steward.services.simplefin.sync import GAP_MSG
    app, state = make_fake(); _household(state)
    with TestClient(app) as http:
        link = _link(db, http)
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
        big = db.scalar(select(Institution).where(Institution.simplefin_org_id == "big"))
        marcus = db.scalar(select(Institution).where(Institution.simplefin_org_id == "marcus"))
        big.last_sync_at = NOW - timedelta(days=60)
        marcus.last_sync_at = NOW - timedelta(days=20)
        link.last_sync_at = NOW - timedelta(hours=1)
        db.commit()
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H); db.commit()
        run_sync(db, http, link, NOW + timedelta(hours=6), model=None, allowed_hosts=H); db.commit()
    gap = GAP_MSG.format(name="Big Bank", since="Aug 13", cut="Aug 29")
    evs = db.scalars(select(EventLog).where(EventLog.message.like("% may be missing%"))).all()
    assert [e.message for e in evs] == [gap]
    assert evs[0].level == "warn" and evs[0].kind == "sync" and evs[0].actionable is True


def test_card_interest_missing_from_the_suggestions_is_a_fee(db):
    """Phase 12 decision 10 on the fallback path: a row with no precomputed suggestion (a new account) still gets the
    amount-aware built-in rules."""
    app, state = make_fake()
    state.add_account("big", "Big Bank", "bigbank", "card", -500_00, E(2026, 10, 12), txns=[
        ("i1", E(2026, 10, 3), -12_34, "INTEREST CHARGE"), ("i2", E(2026, 10, 4), 3_12, "INTEREST PAID")])
    with TestClient(app) as http:
        link = _link(db, http)
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H, suggestions={})
    db.commit()
    t = {x.external_id: x for x in db.scalars(select(Transaction)).all()}
    assert (t["i1"].category, t["i2"].category) == ("fees", "interest")


def _robo(state):
    state.add_account("robo", "Robo Invest", "robo", "tax", 180_000_00, E(2026, 10, 12),
                      txns=[("t1", E(2026, 10, 1), 50_000, "CONTRIBUTION")])
    state.holdings["tax"] = [
        {"id": "h1", "symbol": "VTI", "description": "Vanguard Total Stock Market ETF", "shares": "400.1234",
         "market_value": "108000.004", "cost_basis": "90000"},
        {"id": "h2", "description": "Cash sweep", "market_value": "72000.00"}]


def test_holdings_are_saved_for_the_balance_day_and_a_second_sync_that_day_replaces_them(db, monkeypatch):
    from decimal import Decimal
    from steward.services import costs
    monkeypatch.setattr(costs, "table", lambda: {"VTI": costs.Fund("VTI", "x", Decimal("0.03"), "https://x.test", date(2026, 10, 28))})
    app, state = make_fake(); _robo(state)
    with TestClient(app) as http:
        link = _link(db, http)
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H)
        db.commit()
        acct = db.scalar(select(Account).where(Account.external_id == "sfin:tax"))
        rows = db.scalars(select(Holding).where(Holding.account_id == acct.id).order_by(Holding.id)).all()
        assert [(h.as_of, h.symbol, h.name, h.shares_milli, h.market_value_cents, h.cost_basis_cents, h.expense_ratio_bp, h.import_id)
                for h in rows] == [
            (date(2026, 10, 12), "VTI", "Vanguard Total Stock Market ETF", 400_123, 108_000_00, 90_000_00, 3, None),
            (date(2026, 10, 12), None, "Cash sweep", 0, 72_000_00, None, None, None)]
        assert (acct.sends_holdings, acct.sends_transactions) == (True, True)
        assert acct.holdings_seen_at == NOW and acct.transactions_seen_at == NOW
        state.holdings["tax"] = [{"id": "h1", "symbol": "VTI", "description": "Vanguard Total Stock Market ETF",
                                  "shares": "401", "market_value": "109000"}]
        run_sync(db, http, link, NOW + timedelta(hours=6), model=None, allowed_hosts=H)
        db.commit()
    rows = db.scalars(select(Holding).where(Holding.account_id == acct.id)).all()
    assert [(h.as_of, h.symbol, h.market_value_cents) for h in rows] == [(date(2026, 10, 12), "VTI", 109_000_00)]


def test_a_sync_without_holdings_keeps_the_last_ones_and_records_what_was_sent(db):
    """Review Focus 2: the bank stops sending holdings. Yesterday's stay, with their date; the account records that
    this sync sent none, and when holdings were last seen."""
    app, state = make_fake(); _robo(state)
    with TestClient(app) as http:
        link = _link(db, http)
        run_sync(db, http, link, NOW, model=None, allowed_hosts=H)
        db.commit()
        del state.holdings["tax"]
        state.accounts[0].txns.clear()
        run_sync(db, http, link, NOW + timedelta(days=1), model=None, allowed_hosts=H)
        db.commit()
    acct = db.scalar(select(Account).where(Account.external_id == "sfin:tax"))
    assert [h.market_value_cents for h in db.scalars(select(Holding).where(Holding.account_id == acct.id).order_by(Holding.id))] == [
        108_000_00, 72_000_00]
    assert (acct.sends_holdings, acct.sends_transactions) == (False, False)
    assert acct.holdings_seen_at == NOW and acct.transactions_seen_at == NOW


def test_an_account_that_never_sends_holdings_has_none_and_says_so(db):
    app, state = make_fake(); _household(state)
    with TestClient(app) as http:
        run_sync(db, http, _link(db, http), NOW, model=None, allowed_hosts=H)
    db.commit()
    hy = db.scalar(select(Account).where(Account.external_id == "sfin:hy"))
    assert (hy.sends_holdings, hy.sends_transactions, hy.holdings_seen_at) == (False, False, None)
    assert db.scalar(select(func.count()).select_from(Holding)) == 0
