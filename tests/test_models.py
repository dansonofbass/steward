from datetime import date, datetime, timezone
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session as OrmSession

from steward.db.engine import make_engine
from steward.db.keys import ensure_key
from steward.db.migrate import run_migrations
from steward.db.models import (
    Account, AccountType, Institution, Owner, Source, Transaction, CategorySource, CATEGORIES,
    EventLog, Base,
)


def test_migrate_creates_all_tables(settings):
    eng = make_engine(settings.db_path, ensure_key(settings.key_path))
    run_migrations(eng)
    names = set(inspect(eng).get_table_names())
    assert {
        "institution", "account", "transaction", "holding", "balance_snapshot", "fact",
        "merchant_rule", "import_batch", "event_log",
        "simplefin_link",
    } <= names


def test_cents_are_integers(settings):
    eng = make_engine(settings.db_path, ensure_key(settings.key_path))
    run_migrations(eng)
    with OrmSession(eng) as s:
        inst = Institution(name="Manual", source=Source.manual)
        acct = Account(institution=inst, name="Checking", type=AccountType.checking,
                       owner=Owner.joint, source=Source.manual)
        s.add_all([inst, acct]); s.flush()
        s.add(Transaction(account_id=acct.id, posted_at=date(2026, 1, 2), amount_cents=-10,
                          raw_description="A", category="uncategorized",
                          category_source=CategorySource.none))
        s.add(Transaction(account_id=acct.id, posted_at=date(2026, 1, 3), amount_cents=-20,
                          raw_description="B", category="uncategorized",
                          category_source=CategorySource.none))
        s.commit()
        total = sum(t.amount_cents for t in s.scalars(select(Transaction)))
        assert total == -30 and isinstance(total, int)


def test_categories_fixed_list():
    assert "uncategorized" in CATEGORIES and "transfer" in CATEGORIES
    assert len(CATEGORIES) == len(set(CATEGORIES))


def test_timestamps_round_trip_timezone_aware(settings):
    eng = make_engine(settings.db_path, ensure_key(settings.key_path))
    run_migrations(eng)
    locked = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
    with OrmSession(eng) as s:
        s.add(EventLog(level="info", kind="system", message="x", resolved_at=locked))
        s.commit()
    with OrmSession(eng) as s:
        loaded = s.scalars(select(EventLog)).one().resolved_at
        assert loaded.tzinfo is not None
        assert loaded == locked


def test_migration_matches_models(settings):
    eng = make_engine(settings.db_path, ensure_key(settings.key_path))
    run_migrations(eng)
    with eng.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []


def test_naive_datetime_is_rejected(settings):
    import pytest
    eng = make_engine(settings.db_path, ensure_key(settings.key_path))
    run_migrations(eng)
    with OrmSession(eng) as s:
        s.add(EventLog(level="info", kind="system", message="x", resolved_at=datetime(2026, 3, 4, 5, 6, 7)))
        with pytest.raises(Exception, match="naive datetime; pass an aware UTC datetime"):
            s.flush()


def test_upgrade_keeps_rows_and_allows_unknown_type(settings):
    from alembic import command
    from sqlalchemy import text
    from steward.db.migrate import _config
    eng = make_engine(settings.db_path, ensure_key(settings.key_path))
    cfg = _config(eng)
    command.upgrade(cfg, "0002")
    with eng.begin() as c:
        c.execute(text("INSERT INTO institution (id, name, source) VALUES (1, 'M', 'manual')"))
        c.execute(text("INSERT INTO account (id, institution_id, name, type, owner, source, currency, "
                       "is_active, created_at) VALUES (1, 1, 'A', 'checking', 'joint', 'manual', 'USD', 1, "
                       "'2026-01-01 00:00:00')"))
        c.execute(text("INSERT INTO \"transaction\" (account_id, posted_at, amount_cents, raw_description, "
                       "category, is_business, is_transfer, category_source, imported_at) VALUES "
                       "(1, '2026-01-02', -10, 'x', 'uncategorized', 0, 0, 'none', '2026-01-02 00:00:00')"))
    run_migrations(eng)
    with OrmSession(eng) as s:
        assert s.query(Transaction).count() == 1 and s.query(Account).count() == 1
        s.add(Account(institution_id=1, name="U", type=AccountType.unknown,
                      owner=Owner.joint, source=Source.manual))
        s.commit()
        assert s.query(Account).count() == 2
