"""A synthetic Steward data folder as it was before books (book revision 0007, sign-in tables inside steward.db).
Made-up rows in every table. Nothing here is real."""
import hashlib
import sqlite3  # noqa: F401 - documents that rows are written with plain SQL, as the old release stored them

from alembic import command
from sqlalchemy import text

from steward.db.engine import make_engine
from steward.db.keys import ensure_key
from steward.db.migrate import _config

TOKEN_JR = "token-for-jr-phone-made-up"
CREDENTIAL = bytes.fromhex("0a0b0c0d0e0f")
MOVED = ("user", "passkey", "password_reset", "session")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


ROWS = [
    "INSERT INTO user (id, username, email, display_name, password_hash, created_at, failed_logins, locked_until) "
    "VALUES (1, 'jr', 'jr@example.com', 'JR', '$argon2id$v=19$m=65536,t=3,p=4$made$up', '2026-01-02 03:04:05.000000', 0, NULL)",
    "INSERT INTO user (id, username, email, display_name, password_hash, created_at, failed_logins, locked_until) "
    "VALUES (2, 'sam', 'sam@example.com', 'Sam', '$argon2id$v=19$m=65536,t=3,p=4$also$madeup', '2026-01-02 03:04:06.000000', 2, '2026-10-01 00:00:00.000000')",
    f"INSERT INTO session (id, user_id, token_hash, device_label, created_at, last_seen_at, expires_at, revoked_at) "
    f"VALUES (5, 1, '{token_hash(TOKEN_JR)}', 'Phone', '2026-10-17 00:00:00.000000', '2026-10-17 00:00:00.000000', '2099-01-01 00:00:00.000000', NULL)",
    f"INSERT INTO passkey (id, user_id, credential_id, public_key, sign_count, label, created_at) "
    f"VALUES (3, 1, x'{CREDENTIAL.hex()}', x'a1b2c3', 7, 'Phone', '2026-10-01 00:00:00.000000')",
    "INSERT INTO password_reset (id, user_id, token_hash, expires_at, used_at) "
    "VALUES (4, 2, 'aaaa', '2026-10-01 00:15:00.000000', '2026-10-01 00:05:00.000000')",
    "INSERT INTO institution (id, name, source) VALUES (1, 'Manual', 'manual')",
    "INSERT INTO account (id, institution_id, name, type, owner, source, external_id, currency, is_active, created_at) "
    "VALUES (1, 1, 'Checking', 'checking', 'joint', 'manual', NULL, 'USD', 1, '2026-01-01 00:00:00.000000')",
    "INSERT INTO account (id, institution_id, name, type, owner, source, external_id, currency, is_active, created_at) "
    "VALUES (2, 1, '529 Oldest', 'plan529', 'jr', 'manual', NULL, 'USD', 1, '2026-01-01 00:00:00.000000')",
    "INSERT INTO import_batch (id, account_id, filename, format, row_count, imported_at, imported_by, rolled_back_at) "
    "VALUES (1, 1, 'made-up.csv', 'chase_checking', 2, '2026-02-01 00:00:00.000000', 2, NULL)",
    "INSERT INTO \"transaction\" (id, account_id, posted_at, amount_cents, raw_description, external_id, merchant, category, "
    "is_business, is_transfer, transfer_peer_id, category_source, reviewed_at, snoozed_until, imported_at, import_batch_id) "
    "VALUES (1, 1, '2026-02-01', -1234, 'GREENLEAF MARKET #12', NULL, 'Greenleaf Market', 'groceries', 0, 0, NULL, 'rule', NULL, NULL, '2026-02-01 00:00:00.000000', 1)",
    "INSERT INTO \"transaction\" (id, account_id, posted_at, amount_cents, raw_description, external_id, merchant, category, "
    "is_business, is_transfer, transfer_peer_id, category_source, reviewed_at, snoozed_until, imported_at, import_batch_id) "
    "VALUES (2, 1, '2026-02-02', -1234, 'GREENLEAF MARKET #12', NULL, 'Greenleaf Market', 'groceries', 0, 0, NULL, 'rule', NULL, NULL, '2026-02-02 00:00:00.000000', 1)",
    "INSERT INTO duplicate_keep (a_id, b_id, kept_at) VALUES (1, 2, '2026-02-03 00:00:00.000000')",
    "INSERT INTO holding (id, account_id, as_of, symbol, name, shares_milli, cost_basis_cents, market_value_cents, expense_ratio_bp) "
    "VALUES (1, 2, '2026-10-01', 'VTI', 'Total Stock', 1000, NULL, 500000, 3)",
    "INSERT INTO balance_snapshot (account_id, as_of, balance_cents) VALUES (1, '2026-10-01', 400000)",
    "INSERT INTO fact (id, key, value, as_of, note, created_at) VALUES (1, 'state', 'CA', '2026-10-01', NULL, '2026-10-01 00:00:00.000000')",
    "INSERT INTO merchant_rule (id, pattern, merchant, category, is_business, source, created_at) "
    "VALUES (1, 'GREENLEAF MARKET', 'Greenleaf Market', 'groceries', NULL, 'correction', '2026-02-01 00:00:00.000000')",
    "INSERT INTO event_log (id, at, level, kind, message, actionable, resolved_at) "
    "VALUES (1, '2026-10-01 00:00:00.000000', 'info', 'import', 'Imported 2 rows into Checking from made-up.csv', 0, NULL)",
    "INSERT INTO simplefin_link (id, access_url, claimed_at, last_sync_at, last_error) "
    "VALUES (1, 'https://made:up@bridge.example/simplefin', '2026-10-01 00:00:00.000000', NULL, NULL)",
    "INSERT INTO plan (id, saved_at, saved_by, levers, engine_version, comfortable_age, likely_age) "
    "VALUES (1, '2026-10-02 00:00:00.000000', 1, '{\"assumed\": {}, \"try\": {}, \"pinned\": []}', 'af1e043', 61, 58)",
    "INSERT INTO ss_earnings (person, year, earnings_cents, imported_at) VALUES ('jr', 2020, 5000000, '2026-10-01 00:00:00.000000')",
    "INSERT INTO child (id, label, birth_year, cost_level, account_id, monthly_contribution_cents) "
    "VALUES (1, 'Oldest', 2015, 'in_state_public', 2, 30000)",
    "INSERT INTO asset_class (symbol, class, source) VALUES ('ZZFUNDX', 'bond', 'override')",
    "INSERT INTO setup_step (step, status, user_id, at) VALUES ('pay', 'skipped', 2, '2026-10-03 00:00:00.000000')",
    "INSERT INTO user_setup (user_id, seen_at, confirmed_at, home_hidden_at) VALUES (1, '2026-10-03 00:00:00.000000', NULL, NULL)",
    "INSERT INTO user_setup (user_id, seen_at, confirmed_at, home_hidden_at) VALUES (2, '2026-10-03 00:00:00.000000', '2026-10-03 00:00:00.000000', NULL)",
]


def make_pre_books_vault(settings) -> str:
    """steward.db at revision 0007 with a row in every table, keyed with steward.key. Returns the raw key."""
    key = ensure_key(settings.key_path)
    eng = make_engine(settings.db_path, key)
    command.upgrade(_config(eng), "0007")
    with eng.begin() as c:
        for sql in ROWS:
            c.execute(text(sql))
    eng.dispose()
    return key


AFTER_THE_MOVE = ("is_placeholder", "celebrations", "sound","business_pct", "business_source", "business_line", "business_hint",
                  "business_answered_at", "guess_category", "guess_pct", "model_asked_at", "rate_bp", "dismissed_error", "reimburser_id", "trip_id", "reimburse_source", "inputs_summary", "advisory_fee_bp", "loan_id", "sends_holdings", "sends_transactions", "holdings_seen_at", "transactions_seen_at", "import_id", "org_id", "feed_id", "share_pct", "covers_living", "removed_at", "resume_step", "later_until", "home_hidden_at", "nickname", "note_by", "note_by_name")  # columns migrations 0014, 0016, 0018, 0025, 0026, 0027, 0028, 0030, 0032 (nickname, note_by, note_by_name; amount_cents and note are checked per table) and the placeholder work added later (0030 also drops home_hidden_at)


def snapshot(engine, skip=MOVED) -> dict[str, list[tuple]]:
    """Every row of every table except `skip`, in rowid (or primary key) order, as SQLite returns it."""
    out = {}
    with engine.connect() as c:
        raw = c.connection.driver_connection
        names = [r[0] for r in raw.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for name in names:
            if name in skip or name == "alembic_version":
                continue
            cols = sorted(r[1] for r in raw.execute(f'PRAGMA table_info("{name}")') if r[1] not in AFTER_THE_MOVE)  # added after the move
            col_sql = ", ".join(f'"{col}"' for col in cols)
            out[name] = [tuple(r) for r in raw.execute(f'SELECT {col_sql} FROM "{name}" ORDER BY {col_sql}')]
    return out


def sign_in_rows(engine) -> dict[str, list[tuple]]:
    with engine.connect() as c:
        raw = c.connection.driver_connection
        out = {}
        for name in MOVED:
            cols = sorted(r[1] for r in raw.execute(f'PRAGMA table_info("{name}")') if r[1] not in AFTER_THE_MOVE)  # added after the move
            col_sql = ", ".join(f'"{col}"' for col in cols)
            out[name] = [tuple(r) for r in raw.execute(f'SELECT {col_sql} FROM "{name}" ORDER BY id')]
        return out
