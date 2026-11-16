"""One preview for the whole batch (spec P15, P16, P17; Batch preview): new, already in Steward (by bank id, or the same
date, amount and tidied description, or an earlier file of the batch, matched by count), SimpleFIN already has these,
looks the same, the months covered and each file's unreadable rows."""
from datetime import date

from sqlalchemy import event

from tests.factories import login, make_account, make_person, make_txn
from tests.import_helpers import file_choice, preview, stage

HEAD = "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"


def chase(*rows) -> bytes:
    """A Chase card file (a known format, so no layout is sent) from (mm/dd/yyyy, amount, description) rows."""
    return (HEAD + "".join(f"{d},{d},{desc},Shopping,Sale,{a},\n" for d, a, desc in rows)).encode()


def _jr(client, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")


def _stage_all(client, items):
    """items: [(name, raw or None)]; returns (batch, [entries in order])."""
    batch, entries = None, []
    for name, raw in items:
        r = stage(client, name, raw, batch=batch).json()
        batch = r["batch"]
        entries += r["files"]
    return batch, entries


def test_every_count_on_a_mixed_four_file_batch(client, db, ddb, ours):
    _jr(client, ddb, ours)
    card = make_account(db, "Amex", type="credit")
    other = make_account(db, "Discover", type="credit")
    savings = make_account(db, "Savings", type="savings")
    checking = make_account(db, "Joint checking", type="checking", source="simplefin", institution_name="Chase")
    make_txn(db, card, date(2024, 10, 2), -650, "BLUE BOTTLE COFFEE")          # Already
    make_txn(db, card, date(2024, 10, 7), -8412, "HARBOR GROCERY")             # the file's Oct 6 row looks the same
    make_txn(db, checking, date(2024, 10, 15), -100, "SFIN ROW", external_id="sfin-1")   # SimpleFIN from Oct 15
    batch, e = _stage_all(client, [("amex-basic.csv", None), ("first-cu.csv", None), ("bank.ofx", None),
                                   ("discover.csv", None)])
    body = [file_choice(e[0], card.id, negate=True), file_choice(e[1], checking.id), file_choice(e[2], savings.id),
            file_choice(e[3], other.id)]
    p = preview(client, batch, body).json()
    assert (p["new"], p["already"], p["simplefin"], p["same"], p["unreadable"]) == \
        (15, 1, {"n": 2, "since": "2024-10-15"}, 1, 0)
    assert (p["from"], p["to"], p["accounts"], p["months"]) == ("2024-10-02", "2024-12-12", 4, 3)
    assert [(f["new"], f["already"], f["simplefin"], f["same"]) for f in p["files"]] == \
        [(8, 1, 0, 1), (1, 0, 2, 0), (3, 0, 0, 0), (3, 0, 0, 0)]
    assert p["files"][1]["left_out"] == {"pending": 1, "balance": 0, "totals": 0, "currency": 0}
    [same] = p["look"]["same"]
    assert (same["posted_at"], same["amount_cents"], same["description"], same["match"]) == \
        ("2024-10-06", -8412, "HARBOR GROCERY",
         {"where": "steward", "posted_at": "2024-10-07", "amount_cents": -8412, "description": "HARBOR GROCERY",
          "account": "Amex"})
    assert [r["description"] for r in p["look"]["already"]] == ["BLUE BOTTLE COFFEE"]
    [sf] = p["look"]["simplefin"]
    assert (sf["account_id"], sf["since"], [r["posted_at"] for r in sf["rows"]], sf["more"]) == \
        (checking.id, "2024-10-15", ["2024-10-16", "2024-10-18"], 0)


def test_overlapping_statements_in_one_batch_are_already_by_count(client, db, ddb, ours):
    _jr(client, ddb, ours)
    card = make_account(db, "Card", type="credit")
    q3 = chase(("09/10/2024", "-5.00", "A"), ("09/20/2024", "-6.00", "B"), ("09/30/2024", "-7.00", "C"))
    q4 = chase(("09/20/2024", "-6.00", "B"), ("09/30/2024", "-7.00", "C"), ("10/10/2024", "-8.00", "D"))
    batch, e = _stage_all(client, [("q3.csv", q3), ("q4.csv", q4)])
    p = preview(client, batch, [file_choice(x, card.id) for x in e]).json()
    assert [(f["new"], f["already"]) for f in p["files"]] == [(3, 0), (1, 2)]


def test_a_second_overlapping_statement_imports_only_the_new_months(client, db, ddb, ours):
    """Review focus 1: Q3 already imported in October; January's Q3+Q4 file brings only Q4. Two genuine coffees on one
    day stay two: one is Already (Steward has one), the other Looks the same."""
    _jr(client, ddb, ours)
    card = make_account(db, "Card", type="credit")
    for d, a, desc in (("2024-09-10", -500, "A"), ("2024-09-15", -450, "COFFEE CORNER"), ("2024-09-30", -700, "C")):
        make_txn(db, card, date.fromisoformat(d), a, desc)
    both = chase(("09/10/2024", "-5.00", "A"), ("09/15/2024", "-4.50", "COFFEE CORNER"),
                 ("09/15/2024", "-4.50", "COFFEE CORNER"), ("09/30/2024", "-7.00", "C"),
                 ("10/10/2024", "-8.00", "D"), ("11/10/2024", "-9.00", "E"))
    batch, [e] = _stage_all(client, [("q3-q4.csv", both)])
    p = preview(client, batch, [file_choice(e, card.id)]).json()
    assert (p["new"], p["already"], p["same"], p["from"], p["to"]) == (2, 3, 1, "2024-10-10", "2024-11-10")
    assert p["look"]["same"][0]["match"]["where"] == "steward"


def test_two_identical_coffees_in_one_file_are_one_new_and_one_looks_the_same(client, db, ddb, ours):
    _jr(client, ddb, ours)
    card = make_account(db, "Card", type="credit")
    batch, [e] = _stage_all(client, [("c.csv", chase(("10/14/2024", "-4.50", "COFFEE"), ("10/14/2024", "-4.50", "COFFEE")))])
    p = preview(client, batch, [file_choice(e, card.id)]).json()
    assert (p["new"], p["already"], p["same"], p["look"]["same"][0]["match"]["where"]) == (1, 0, 1, "file")
    chosen = preview(client, batch, [file_choice(e, card.id, include=[p["look"]["same"][0]["row"]])]).json()
    assert (chosen["new"], chosen["same"]) == (2, 0)
    assert chosen["digest"] != p["digest"]


def test_different_fitids_are_never_repeats_and_a_known_one_is_already(client, db, ddb, ours):
    _jr(client, ddb, ours)
    savings = make_account(db, "Savings", type="savings")
    make_txn(db, savings, date(2024, 10, 14), -5412, "SOMETHING ELSE", external_id="202410140001")
    from tests.bank_files import text
    twin = text("bank.ofx").replace("<FITID>202410170003<NAME>CITY POWER<MEMO>AUTOPAY",
                                    "<FITID>202410170003<NAME>CITY POWER<MEMO>AUTOPAY</STMTTRN>"
                                    "<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20241017<TRNAMT>-118.40<FITID>202410170004"
                                    "<NAME>CITY POWER<MEMO>AUTOPAY")
    batch, [e] = _stage_all(client, [("twin.ofx", twin.encode())])
    p = preview(client, batch, [file_choice(e, savings.id)]).json()
    assert (p["new"], p["already"], p["same"]) == (3, 1, 0)


def test_a_bank_id_seen_in_an_earlier_file_is_already_even_when_its_name_changed(client, db, ddb, ours):
    _jr(client, ddb, ours)
    savings = make_account(db, "Savings", type="savings")
    from tests.bank_files import text
    one = text("bank.ofx")
    two = one.replace("CITY POWER", "CITY POWER CO")
    batch, e = _stage_all(client, [("one.ofx", one.encode()), ("two.ofx", two.encode())])
    p = preview(client, batch, [file_choice(x, savings.id) for x in e]).json()
    assert [(f["new"], f["already"]) for f in p["files"]] == [(3, 0), (0, 3)]


def test_the_simplefin_line_is_dated_for_one_account_and_undated_for_two(client, db, ddb, ours):
    _jr(client, ddb, ours)
    a = make_account(db, "Checking A", type="checking", source="simplefin", institution_name="Chase")
    b = make_account(db, "Checking B", type="checking", source="simplefin", institution_name="Chase")
    make_txn(db, a, date(2024, 10, 1), -1, "SFIN", external_id="sfin-a")
    make_txn(db, b, date(2024, 10, 5), -1, "SFIN", external_id="sfin-b")
    rows = chase(("09/30/2024", "-5.00", "OLD"), ("10/10/2024", "-6.00", "NEW"))
    batch, [x] = _stage_all(client, [("x.csv", rows)])
    one = preview(client, batch, [file_choice(x, a.id)]).json()
    assert (one["new"], one["simplefin"]) == (1, {"n": 1, "since": "2024-10-01"})
    batch2, [y, z] = _stage_all(client, [("y.csv", rows), ("z.csv", chase(("10/20/2024", "-7.00", "LATER")))])
    two = preview(client, batch2, [file_choice(y, a.id), file_choice(z, b.id)]).json()
    assert two["simplefin"] == {"n": 2, "since": None}
    assert {s["account_id"]: s["since"] for s in two["look"]["simplefin"]} == {a.id: "2024-10-01", b.id: "2024-10-05"}
    too = preview(client, batch2, [file_choice(y, a.id), file_choice(z, b.id)], simplefin_include=[a.id]).json()
    assert (too["new"], too["simplefin"]) == (2, {"n": 1, "since": "2024-10-05"})


def test_a_held_file_adds_nothing_and_says_why(client, db, ddb, ours):
    _jr(client, ddb, ours)
    card = make_account(db, "Card", type="credit")
    # future-date.csv is 1 bad row in 3 (33%), which P17 holds; 1 in 31 is under the 5% line, so the good rows import.
    mostly_good = ("Date,Description,Amount\n" + "".join(f"10/{i % 28 + 1:02d}/2024,SHOP,-{i + 1}.00\n" for i in range(30))
                   + "01/15/2099,FUTURE PLACE,-5.00\n").encode()
    batch, e = _stage_all(client, [("mostly-bad.csv", None), ("future.csv", mostly_good)])
    p = preview(client, batch, [file_choice(e[0], card.id), file_choice(e[1], card.id)]).json()
    assert p["files"][0] == {**p["files"][0], "new": 0, "held": "30 rows can't be read. Check the columns.", "unreadable": 30}
    assert (p["files"][1]["new"], [x["text"] for x in p["files"][1]["errors"]]) == (30, ["Row 32: the date is in the future."])
    assert p["unreadable"] == 31


def test_a_new_layout_must_be_confirmed_and_every_file_needs_an_account(client, db, ddb, ours):
    _jr(client, ddb, ours)
    card = make_account(db, "Card", type="credit")
    batch, [e] = _stage_all(client, [("amex-basic.csv", None)])
    unconfirmed = {**file_choice(e, card.id), "layout": None}
    unsigned = {**file_choice(e, card.id), "layout": {**file_choice(e, card.id)["layout"], "negate": None}}
    for f in (unconfirmed, unsigned, {**file_choice(e, card.id), "account_id": None}):
        r = preview(client, batch, [f])
        assert (r.status_code, r.json()) == (422, {"error": "These files aren't ready yet."})
    bad = {**file_choice(e, card.id), "layout": {"mapping": {"date": 0, "description": 1}, "negate": True,
                                                  "date_format": "%m/%d/%Y"}}
    assert preview(client, batch, [bad]).json() == {"error": "Choose an amount column, or both a money-out and a money-in column."}
    assert preview(client, batch, [{**file_choice(e, 999999)}]).status_code == 404
    assert preview(client, "b_gone", [file_choice(e, card.id)]).status_code == 410
    assert preview(client, batch, [{**file_choice(e, card.id), "token": "f_other"}]).status_code == 410
    assert client.post("/api/b/ours/import/batch/preview", json={"batch": batch, "files": "x"}).status_code == 422


def test_a_date_column_the_server_never_dated_is_dated_from_the_sent_column(client, db, ddb, ours):
    """The confirm mapped Date to a column the staged layout had no format for: the preview works it out, never 422."""
    _jr(client, ddb, ours)
    bank = make_account(db, "Checking", type="checking")
    raw = b"Run Date,Payee Name,Amount\n10/14/2024,BLUE BOTTLE,-6.50\n10/21/2024,PAYROLL,2100.00\n"
    batch, [e] = _stage_all(client, [("odd.csv", raw)])
    assert (e["layout"]["mapping"], e["layout"]["date_format"]) == ({"amount": 2}, None)
    f = {"token": e["token"], "account_id": bank.id, "include": [],
         "layout": {"mapping": {"date": 0, "description": 1, "amount": 2}, "negate": False, "date_format": None}}
    r = preview(client, batch, [f])
    assert r.status_code == 200, r.text
    p = r.json()
    assert (p["new"], p["unreadable"], p["from"], p["to"]) == (2, 0, "2024-10-14", "2024-10-21")
    moved = {**f, "layout": {**f["layout"], "date_format": ""}}
    assert preview(client, batch, [moved]).json()["new"] == 2


def test_date_moved_to_another_column_in_the_confirm_is_read_in_that_columns_format(client, db, ddb, ours):
    _jr(client, ddb, ours)
    bank = make_account(db, "Checking", type="checking")
    raw = b"Date,Posted On,Description,Amount\n10/14/2024,2024-10-16,BLUE BOTTLE,-6.50\n10/21/2024,2024-10-22,PAY,2100.00\n"
    batch, [e] = _stage_all(client, [("moved.csv", raw)])
    assert (e["layout"]["mapping"]["date"], e["layout"]["date_format"]) == (0, "%m/%d/%Y")
    f = {"token": e["token"], "account_id": bank.id, "include": [],
         "layout": {"mapping": {"date": 1, "description": 2, "amount": 3}, "negate": False, "date_format": "%m/%d/%Y"}}
    p = preview(client, batch, [f]).json()
    assert (p["new"], p["unreadable"], p["from"], p["to"]) == (2, 0, "2024-10-16", "2024-10-22")


def test_a_changed_layout_reparses_that_file(client, db, ddb, ours):
    _jr(client, ddb, ours)
    card = make_account(db, "Card", type="credit")
    batch, [e] = _stage_all(client, [("amex-basic.csv", None)])
    as_is = preview(client, batch, [file_choice(e, card.id, negate=False)]).json()
    negated = preview(client, batch, [file_choice(e, card.id, negate=True)]).json()
    assert as_is["digest"] != negated["digest"] and (as_is["new"], negated["new"]) == (10, 10)


def test_a_preview_runs_at_most_six_plus_two_per_account_statements(client, db, ddb, ours, engine):
    _jr(client, ddb, ours)
    accts = [make_account(db, f"Card {i}", type="credit", source="simplefin", institution_name="Chase") for i in range(3)]
    batch, e = _stage_all(client, [(f"{i}.csv", chase((f"10/1{i}/2024", f"-{i + 1}.00", f"SHOP {i}"))) for i in range(3)])
    body = [file_choice(x, a.id) for x, a in zip(e, accts)]
    preview(client, batch, body)                                    # warm-up
    seen: list[str] = []

    def count(_conn, _cursor, statement, *_):
        if statement.lstrip().split(None, 1)[0].upper() in ("SELECT", "INSERT", "UPDATE", "DELETE", "WITH"):
            seen.append(statement)
    event.listen(engine, "before_cursor_execute", count)
    try:
        assert preview(client, batch, body).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(seen) <= 6 + 2 * 3, seen


def test_viewers_cant_preview(client, ddb, ours):
    make_person(ddb, "val", [(ours.id, "viewer")])
    login(client, "val")
    assert preview(client, "b_any", []).status_code == 404


NOT_UNDERSTOOD = (422, {"error": "That request wasn't understood."})


def _answer(r):
    return r.status_code, r.json()


def test_the_preview_refuses_a_repeated_over_long_or_odd_file_list(client, db, ddb, ours):
    """A preview plans each staged file at most once: a repeated token, more lines than staged files or a token
    that isn't a string is refused before anything is planned."""
    _jr(client, ddb, ours)
    card = make_account(db, "Card", type="credit")
    batch, [e] = _stage_all(client, [("amex-basic.csv", None)])
    line = file_choice(e, card.id, negate=True)
    assert _answer(preview(client, batch, [line, line])) == NOT_UNDERSTOOD
    assert _answer(preview(client, batch, [line, {**line, "token": "f_other"}])) == NOT_UNDERSTOOD
    assert _answer(preview(client, batch, [line] * 300)) == NOT_UNDERSTOOD
    assert _answer(preview(client, batch, [line] + [{**line, "token": f"f_{i}"} for i in range(300)])) == NOT_UNDERSTOOD
    for token in (None, 7, ["f_x"]):
        assert _answer(preview(client, batch, [{**line, "token": token}])) == NOT_UNDERSTOOD
    assert preview(client, batch, [line]).status_code == 200


def test_include_names_each_of_the_files_rows_at_most_once(client, db, ddb, ours):
    _jr(client, ddb, ours)
    card = make_account(db, "Card", type="credit")
    batch, [e] = _stage_all(client, [("amex-basic.csv", None)])                    # 10 rows: 0-9
    for include in ([10], [-1], [3, 3], ["1"], [True], [1.0], list(range(11))):
        r = preview(client, batch, [file_choice(e, card.id, negate=True, include=include)])
        assert _answer(r) == NOT_UNDERSTOOD, include
    ok = preview(client, batch, [file_choice(e, card.id, negate=True, include=[0, 9])])
    assert ok.status_code == 200 and ok.json()["new"] == 10


def test_the_commit_refuses_what_the_preview_refuses(client, db, ddb, ours):
    _jr(client, ddb, ours)
    card = make_account(db, "Card", type="credit")
    batch, [e] = _stage_all(client, [("amex-basic.csv", None)])
    line = file_choice(e, card.id, negate=True)
    digest = preview(client, batch, [line]).json()["digest"]
    for files in ([line, line], [{**line, "include": [3, 3]}], [{**line, "include": [10]}]):
        r = client.post("/api/b/ours/import/batch/commit", json={"batch": batch, "files": files, "digest": digest})
        assert _answer(r) == NOT_UNDERSTOOD


def test_a_reparse_with_no_room_is_busy_and_a_preview_without_one_still_answers(app, client, db, ddb, ours):
    _jr(client, ddb, ours)
    card, bank = make_account(db, "Card", type="credit"), make_account(db, "Bank", type="checking")
    batch, [amex, known] = _stage_all(client, [("amex-basic.csv", None), ("c.csv", chase(("10/14/2024", "-1.00", "A")))])
    store = app.state.import_staging
    store.cap = store.held_bytes()                                                # full: no room for a re-parse
    r = preview(client, batch, [file_choice(amex, card.id, negate=True)])
    assert _answer(r) == (503, {"error": "Steward is busy with other files. Try again in a few minutes."})
    assert preview(client, batch, [file_choice(known, bank.id)]).status_code == 200      # a known format: no re-parse
