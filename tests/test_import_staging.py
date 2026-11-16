"""Staging (spec P3, P38-P40): in memory, bound to the person and the book, gone after 30 idle minutes; 30 files and
100,000 rows a batch; a 200 MB cap across the process."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from steward.services import import_staging as S
from steward.services.import_staging import EXPIRED, ImportStaging, StagingRefused, build
from tests.bank_files import read

NOW = datetime(2026, 10, 30, 19, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 30)


def _files(name, raw=None):
    return build(name, read(name) if raw is None else raw, TODAY, lambda key: None)


def _refused(fn, *args):
    with pytest.raises(StagingRefused) as e:
        fn(*args)
    return e.value.status, e.value.message


def test_staging_expires_at_thirty_idle_minutes():
    s = ImportStaging()
    b = s.batch(1, 1, None, NOW)
    s.add(b, *_files("amex-basic.csv"), NOW)
    later = NOW + timedelta(minutes=29, seconds=59)
    assert list(s.batch(1, 1, b.id, later).files)                 # touching it starts the 30 minutes again
    assert _refused(s.batch, 1, 1, b.id, later + timedelta(minutes=30)) == (410, EXPIRED)


def test_another_person_or_book_never_reaches_a_batch():
    s = ImportStaging()
    b = s.batch(1, 1, None, NOW)
    assert _refused(s.batch, 2, 1, b.id, NOW) == (410, EXPIRED)
    assert _refused(s.batch, 1, 2, b.id, NOW) == (410, EXPIRED)
    s.add(b, *_files("amex-basic.csv"), NOW)
    token = next(iter(b.files))
    assert s.drop_file(2, 1, token, NOW) is False and token in b.files


def test_the_31st_file_is_refused():
    s = ImportStaging()
    b = s.batch(1, 1, None, NOW)
    for i in range(S.MAX_FILES):
        s.add(b, *_files(f"f{i}.csv", f"Date,Description,Amount\n10/14/2024,SHOP {i},-1.00\n".encode()), NOW)
    assert _refused(s.add, b, *_files("f30.csv", b"Date,Description,Amount\n10/14/2024,SHOP 30,-1.00\n"), NOW) == \
        (422, "A batch holds up to 30 files. Import these, then add the rest.")


def test_the_row_after_the_limit_is_refused():
    assert S.MAX_ROWS == 100_000
    s = ImportStaging(max_rows=12)
    b = s.batch(1, 1, None, NOW)
    s.add(b, *_files("amex-basic.csv"), NOW)                                       # 10 rows
    s.add(b, *_files("two.csv", b"Date,Description,Amount\n10/14/2024,A,-1.00\n10/15/2024,B,-2.00\n"), NOW)   # 12
    assert _refused(s.add, b, *_files("one.csv", b"Date,Description,Amount\n10/16/2024,C,-3.00\n"), NOW) == \
        (422, "A batch holds up to 100,000 rows. Import these, then add the rest.")


def test_the_cap_across_the_process_is_busy_and_removal_frees_it():
    assert S.CAP_BYTES == 200 * 1024 * 1024
    sha, size, files = _files("amex-basic.csv")
    s = ImportStaging(cap=size + files[0].weight)
    first, second = s.batch(1, 1, None, NOW), s.batch(2, 1, None, NOW)
    s.add(first, sha, size, files, NOW)                                            # exactly at the cap
    big = _files("big.csv", b"Date,Description,Amount\n" + b"10/14/2024,SHOP,-1.00\n" * 400)
    assert _refused(s.add, second, *big, NOW) == (503, "Steward is busy with other files. Try again in a few minutes.")
    assert s.drop_file(1, 1, next(iter(first.files)), NOW) is True
    assert first.uploads == {}


def test_a_multi_account_ofx_is_one_upload_with_a_line_per_account():
    sha, size, files = _files("two-accounts.ofx")
    assert [f.name for f in files] == ["two-accounts.ofx · ••1111", "two-accounts.ofx · ••2222"]
    assert {f.sha256 for f in files} == {sha} and [f.hint_key for f in files] == ["ofx:HARBORCU:1111", "ofx:HARBORCU:2222"]
    s = ImportStaging()
    b = s.batch(1, 1, None, NOW)
    s.add(b, sha, size, files, NOW)
    assert (len(b.files), len(b.uploads)) == (2, 1)


def test_a_staged_file_keeps_its_parse_for_each_layout():
    sha, size, [f] = _files("amex-basic.csv")
    s = ImportStaging()
    b = s.batch(1, 1, None, NOW)
    s.add(b, sha, size, [f], NOW)
    negated = replace(f.layout, negate=True)
    assert s.parsed_for(b, f, f.layout, TODAY, NOW) is f.parsed
    once = s.parsed_for(b, f, negated, TODAY, NOW)
    assert once is s.parsed_for(b, f, negated, TODAY, NOW) and once.rows[0].amount_cents == -650


def _cells(table):
    return sum(len(c) for _, c in table.rows) + len(table.header)


def test_the_weight_counts_the_table_the_rows_and_the_reparse():
    """The cap counts what staging holds: the decoded text, the table's cells, the parsed rows and the re-parse."""
    sha, size, [f] = _files("amex-basic.csv")
    assert f.weight >= 2 * size + _cells(f.table) * S.SLOT_BYTES + len(f.table.rows) * S.TABLE_ROW_BYTES + \
        len(f.parsed.rows) * S.ROW_BYTES
    assert f.weight == S.table_weight(f.table, size) + S.parse_weight(f.parsed)
    s = ImportStaging()
    b = s.batch(1, 1, None, NOW)
    s.add(b, sha, size, [f], NOW)
    assert s.held_bytes() == size + f.weight
    again = s.parsed_for(b, f, replace(f.layout, negate=True), TODAY, NOW)
    assert S.parse_weight(again) >= S.PARSE_BYTES + len(again.rows) * S.ROW_BYTES
    assert s.held_bytes() == size + f.weight + S.parse_weight(again)
    assert s.drop_file(1, 1, f.token, NOW) is True and s.held_bytes() == 0


def test_an_ofx_weighs_its_rows_and_its_text_once():
    sha, size, files = _files("two-accounts.ofx")
    s = ImportStaging()
    b = s.batch(1, 1, None, NOW)
    s.add(b, sha, size, files, NOW)
    assert s.held_bytes() == size + sum(S.parse_weight(f.parsed) for f in files)


def test_alternating_layouts_hold_one_reparse_and_a_steady_weight():
    sha, size, [f] = _files("amex-basic.csv")
    s = ImportStaging()
    b = s.batch(1, 1, None, NOW)
    s.add(b, sha, size, [f], NOW)
    out, credit = replace(f.layout, negate=True), replace(f.layout, negate=False)
    totals = []
    for layout in [out, credit] * 4:
        got = s.parsed_for(b, f, layout, TODAY, NOW)
        assert f.reparse is got
        totals.append(s.held_bytes())
    assert len(set(totals)) == 1 and totals[0] == size + f.weight + S.parse_weight(f.reparse)
    assert s.parsed_for(b, f, f.layout, TODAY, NOW) is f.parsed and f.reparse is not None


def test_a_reparse_past_the_cap_is_busy_and_the_held_parse_stays():
    sha, size, [f] = _files("amex-basic.csv")
    unread = replace(f.layout, negate=True, date_format="%Y-%m-%d")             # every row an error: a light parse
    negated = replace(f.layout, negate=True)
    light, heavy = S.parse_weight(S.parse(f.table, unread, TODAY)), S.parse_weight(S.parse(f.table, negated, TODAY))
    assert light < heavy
    s = ImportStaging(cap=size + f.weight + light)
    b = s.batch(1, 1, None, NOW)
    s.add(b, sha, size, [f], NOW)
    held = s.parsed_for(b, f, unread, TODAY, NOW)
    assert _refused(s.parsed_for, b, f, negated, TODAY, NOW) == \
        (503, "Steward is busy with other files. Try again in a few minutes.")
    assert f.reparse is held and s.parsed_for(b, f, unread, TODAY, NOW) is held
    assert s.held_bytes() == size + f.weight + light
    assert s.parsed_for(b, f, f.layout, TODAY, NOW) is f.parsed


def test_the_first_reparse_past_the_cap_is_busy_and_the_staged_parse_stays():
    sha, size, [f] = _files("amex-basic.csv")
    s = ImportStaging(cap=size + f.weight)
    b = s.batch(1, 1, None, NOW)
    s.add(b, sha, size, [f], NOW)
    assert _refused(s.parsed_for, b, f, replace(f.layout, negate=True), TODAY, NOW)[0] == 503
    assert f.reparse is None and s.parsed_for(b, f, f.layout, TODAY, NOW) is f.parsed


def test_room_is_checked_from_the_raw_size_before_any_parse():
    sha, size, files = _files("amex-basic.csv")
    s = ImportStaging(cap=size + files[0].weight + 1000 * S.RAW_FACTOR)
    s.room_for(1000, NOW)                                                         # nothing held yet
    b = s.batch(1, 1, None, NOW)
    s.add(b, sha, size, files, NOW)
    s.room_for(1000, NOW)                                                         # exactly at the cap
    assert _refused(s.room_for, 1001, NOW) == (503, "Steward is busy with other files. Try again in a few minutes.")


def test_a_fourth_batch_drops_that_persons_least_recently_touched_one_in_that_book():
    assert S.MAX_BATCHES == 3
    s = ImportStaging()
    mine = [s.batch(1, 1, None, NOW + timedelta(minutes=i)) for i in range(3)]
    theirs, other_book = s.batch(2, 1, None, NOW), s.batch(1, 2, None, NOW)
    s.batch(1, 1, mine[0].id, NOW + timedelta(minutes=5))                         # touched: now the newest
    fourth = s.batch(1, 1, None, NOW + timedelta(minutes=6))
    assert _refused(s.batch, 1, 1, mine[1].id, NOW + timedelta(minutes=6)) == (410, EXPIRED)
    for b, who, book in [(mine[0], 1, 1), (mine[2], 1, 1), (fourth, 1, 1), (theirs, 2, 1), (other_book, 1, 2)]:
        assert s.batch(who, book, b.id, NOW + timedelta(minutes=6)) is b
