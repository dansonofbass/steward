"""The CSV downloads (spec P24, P25): managers only; the columns in order, signed amounts, a BOM and CRLF; All time,
a year or chosen dates (inclusive); notes only when asked for; every text cell guarded against formulas; one log line
each; the business report's lines equal the Business page's."""
import csv
import io
from datetime import date, datetime, timezone

from sqlalchemy import select

from steward.db.models import EventLog, Owner, TransactionNote
from tests.factories import login, make_account, make_person, make_txn

URL = "/api/b/ours/export/transactions.csv"


def _book(db):
    a = make_account(db, "Joint checking")
    make_txn(db, a, date(2025, 12, 31), -6418, "TRADER JOE'S #552", merchant="Trader Joe's", category="groceries")
    pay = make_txn(db, a, date(2026, 1, 1), 210000, "NORTHWIND PAYROLL", category="income")
    make_txn(db, a, date(2026, 3, 15), -2500, '=HYPERLINK("http://x","click")')
    r = make_txn(db, a, date(2026, 10, 14), -100, "-REFUND", category="shopping", business_pct=50)
    r.nickname = "@SUM(A1)"
    make_txn(db, a, date(2026, 10, 20), -50000, "+1 555 0100 TRANSFER", category="transfer", is_transfer=True)
    for body, day in (("zorblax first", 1), ("second note", 2)):
        db.add(TransactionNote(transaction_id=pay.id, author_id=1, author_name="JR", body=body,
                               created_at=datetime(2026, 10, day, tzinfo=timezone.utc)))
    db.commit()


def _rows(r) -> list[list[str]]:
    return list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"), newline="")))


HEAD = ["Date", "Account", "Description", "Name", "Category", "Amount", "Transfer", "Business %"]


def test_all_time_has_every_column_in_order_with_signed_amounts(signed_in, db):
    _book(db)
    r = signed_in.get(URL)
    assert r.status_code == 200
    assert r.content.startswith(b"\xef\xbb\xbf") and b"\r\n" in r.content and b"\n\n" not in r.content
    assert r.headers["content-disposition"] == 'attachment; filename="steward-ours-transactions-all.csv"'
    assert (r.headers["cache-control"], r.headers["x-content-type-options"]) == ("no-store", "nosniff")
    assert r.headers["content-type"].startswith("text/csv")
    assert _rows(r) == [HEAD,
                        ["2025-12-31", "Joint checking", "TRADER JOE'S #552", "Trader Joe's", "Groceries", "-64.18", "", ""],
                        ["2026-01-01", "Joint checking", "NORTHWIND PAYROLL", "", "Income", "2100.00", "", ""],
                        ["2026-03-15", "Joint checking", "'=HYPERLINK(\"http://x\",\"click\")", "", "Not sorted yet", "-25.00", "", ""],
                        ["2026-10-14", "Joint checking", "'-REFUND", "'@SUM(A1)", "Shopping", "-1.00", "", "50"],
                        ["2026-10-20", "Joint checking", "'+1 555 0100 TRANSFER", "", "Transfer", "-500.00", "yes", ""]]


def test_every_text_cell_is_guarded_against_formulas(signed_in, db):
    """Review focus 2: text that a spreadsheet would run is text; amounts stay numbers."""
    a = make_account(db, "=Evil account")
    for i, desc in enumerate(("=1+1", "+CMD", "-2", "@x", "\tTAB", "\rCR", "plain")):
        make_txn(db, a, date(2026, 10, 1 + i), -100 * (i + 1), desc)
    rows = _rows(signed_in.get(URL))[1:]
    assert [r[2] for r in rows] == ["'=1+1", "'+CMD", "'-2", "'@x", "'\tTAB", "'\rCR", "plain"]
    assert {r[1] for r in rows} == {"'=Evil account"}
    assert [r[5] for r in rows][:2] == ["-1.00", "-2.00"]


def test_a_year_and_chosen_dates_include_both_ends(signed_in, db):
    _book(db)
    last = signed_in.get(URL, params={"from": "2025-01-01", "to": "2025-12-31"})
    assert [r[0] for r in _rows(last)[1:]] == ["2025-12-31"]
    assert last.headers["content-disposition"] == 'attachment; filename="steward-ours-transactions-2025-01-01-2025-12-31.csv"'
    chosen = signed_in.get(URL, params={"from": "2026-01-01", "to": "2026-03-15"})
    assert [r[0] for r in _rows(chosen)[1:]] == ["2026-01-01", "2026-03-15"]


def test_notes_only_when_asked_for_newest_first(signed_in, db):
    _book(db)
    plain = signed_in.get(URL)
    assert b"zorblax" not in plain.content and "Notes" not in _rows(plain)[0]
    noted = _rows(signed_in.get(URL, params={"notes": "1"}))
    assert noted[0] == HEAD + ["Notes"]
    assert noted[2][-1] == "second note | zorblax first"


def test_each_download_writes_one_log_line(signed_in, db):
    _book(db)
    signed_in.get(URL)
    signed_in.get(URL, params={"from": "2026-01-01", "to": "2026-03-15", "notes": "1"})
    db.rollback()
    assert db.scalars(select(EventLog.message).where(EventLog.kind == "export").order_by(EventLog.id)).all() == [
        "JR downloaded transactions (all time)", "JR downloaded transactions (2026-01-01 to 2026-03-15, with notes)"]


def test_a_half_range_or_a_bad_date_is_refused(signed_in, db):
    for params in ({"from": "2026-01-01"}, {"to": "2026-01-01"}, {"from": "2026-13-01", "to": "2026-12-01"},
                   {"from": "2026-12-01", "to": "2026-01-01"}):
        r = signed_in.get(URL, params=params)
        assert (r.status_code, r.json()) == (422, {"error": "Choose a start and an end date."}), params
    assert signed_in.get(URL, params={"notes": "yes"}).status_code == 422


def test_viewers_get_404(client, ddb, ours):
    make_person(ddb, "val", [(ours.id, "viewer")])
    login(client, "val")
    for path in (URL, "/api/b/ours/export/business.csv"):
        assert (client.get(path).status_code, client.get(path).json()) == (404, {"error": "This book doesn't have that."})


def test_a_parent_book_has_no_business_column(client, margaret, mdb):
    login(client, "jr")
    make_txn(mdb, make_account(mdb, "Margaret checking"), date(2026, 10, 1), -100, "PHARMACY")
    rows = _rows(client.get("/api/b/margaret-ellis/export/transactions.csv"))
    assert rows[0] == HEAD[:-1] and rows[1][-1] == ""


def test_the_business_report_equals_the_business_page(frozen, signed_in, db):
    bchk = make_account(db, "Business checking", type="business_checking", owner=Owner.business)
    make_txn(db, bchk, date(2026, 3, 3), 300_000, "ACH CLIENT INV 1", category="business_income", is_business=True)
    make_txn(db, bchk, date(2026, 4, 3), -2_900, "NOTEFLOW PRO", category="subscriptions", business_pct=50)
    assert signed_in.get("/api/b/ours/export/business.csv").status_code == 404        # no business yet
    assert signed_in.put("/api/b/ours/business/settings", json={"type": "sole_prop"}).status_code == 200
    r = signed_in.get("/api/b/ours/export/business.csv", params={"year": "2026"})
    assert r.headers["content-disposition"] == 'attachment; filename="steward-ours-business-2026.csv"'
    page = signed_in.get("/api/b/ours/business", params={"year": "2026"}).json()
    lines = [[l["number"], l["label"], f"{l['counts_cents'] / 100:.2f}", str(l["count"]), l["note"] or ""] for l in page["lines"]]
    assert _rows(r) == [["Line", "Label", "Counts", "Rows", "Note"], *lines,
                        ["", "Income", "3000.00", "", ""], ["", "Expenses", "14.50", "", ""], ["", "Profit", "2985.50", "", ""]]
    assert signed_in.get("/api/b/ours/export/business.csv", params={"year": "2019"}).json() == {"error": "Choose this year or last year."}


def test_a_parent_book_has_no_business_report(client, margaret):
    login(client, "jr")
    assert client.get("/api/b/margaret-ellis/export/business.csv").status_code == 404
