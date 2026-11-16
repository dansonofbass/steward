from datetime import date

from sqlalchemy import func, select

from steward.db.models import TaxForm
from steward.demo_parent import seed_parent
from steward.inventory.suggestions import refresh
from steward.deps import today
from tests.factories import login

BOOK = "/api/b/margaret-ellis/inventory"
HARBOR = {"form": "1099-INT", "tax_year": 2025, "recipient": "margaret", "payer": "Harbor Savings Bank",
          "last4": "2207", "boxes": {"box_1": 5890, "box_4": 0}}


def _seeded(mdb, mctx):
    seed_parent(mdb, date(2026, 10, 18), by=mctx.user_id)
    refresh(mdb, date(2026, 10, 18))
    mdb.commit()


def test_a_form_joins_the_waiting_suggestion(margaret, mdb, mctx, client):
    _seeded(mdb, mctx)
    login(client, "jr")
    r = client.post(f"{BOOK}/tax-forms", json=HARBOR)
    assert r.status_code == 201
    assert r.json()["headline"] == "1099-INT saved. Harbor Savings Bank isn't in Margaret's inventory."
    assert r.json()["detail"] == ("Added to the suggestion already waiting for Harbor Savings Bank: account "
                                  "••2207, $58.90 interest in 2025.")
    card = next(s for s in client.get(f"{BOOK}/suggestions").json()["suggestions"] if s["payer"] == "Harbor Savings Bank")
    assert card["forms"] == ["1099-INT 2025 · ••2207 · $58.90 interest"]
    assert card["prefill"]["last4"] == "2207"
    row = client.get("/api/b/margaret-ellis/changes?kind=suggestions").json()["changes"][0]
    assert (row["text"], row["lines"]) == ("typed in a 1099-INT from Harbor Savings Bank", ["Tax year 2025 · ••2207"])


def test_an_ssa_1099_confirms_social_security(margaret, mdb, mctx, client):
    _seeded(mdb, mctx)
    login(client, "jr")
    r = client.post(f"{BOOK}/tax-forms", json={"form": "SSA-1099", "tax_year": 2025, "recipient": "margaret",
                                               "payer": "", "boxes": {"box_3": 2790000, "box_5": 2568000,
                                                                      "medicare": 222000}})
    assert r.json()["headline"] == "SSA-1099 saved. It matches Social Security."
    assert r.json()["detail"] == "Nothing new to add."


def test_a_new_payer_starts_a_suggestion(margaret, mdb, mctx, client):
    _seeded(mdb, mctx)
    login(client, "jr")
    r = client.post(f"{BOOK}/tax-forms", json={"form": "1099-R", "tax_year": 2025, "recipient": "margaret",
                                               "payer": "Lakeside Teachers Pension", "boxes": {"box_1": 1200000,
                                                                                             "box_7": "7"}})
    assert r.json()["headline"] == "1099-R saved. Lakeside Teachers Pension isn't in Margaret's inventory."
    assert r.json()["detail"] == "Added to Is this one of Margaret's?: $12,000.00 paid out in 2025."
    card = next(s for s in client.get(f"{BOOK}/suggestions").json()["suggestions"]
                if s["payer"] == "Lakeside Teachers Pension")
    assert card["eyebrow"] == "Suggested: income · pension" and card["why"] == "From Margaret's 2025 1099-R."


def test_refusals(margaret, client):
    login(client, "jr")
    for body, message in (({**HARBOR, "form": "W-2"}, "Choose 1099-INT, 1099-DIV, 1099-R or SSA-1099."),
                          ({**HARBOR, "recipient": "jr"}, "Choose one of this book's owners."),
                          ({**HARBOR, "tax_year": 1999}, f"Enter a tax year from 2000 to {today().year}."),
                          ({**HARBOR, "payer": ""}, "Enter the payer's name, up to 120 characters."),
                          ({**HARBOR, "last4": "12345"}, "Enter up to 4 digits or letters."),
                          ({**HARBOR, "boxes": {"box_1": "lots"}}, "Enter Box 1 (Interest income) in dollars and cents."),
                          ({**HARBOR, "boxes": {}}, "Enter Box 1 (Interest income) in dollars and cents."),
                          ({**HARBOR, "file_id": 999}, "No such file.")):
        r = client.post(f"{BOOK}/tax-forms", json=body)
        assert (r.status_code, r.json()) == (422 if message != "No such file." else 404, {"error": message}), body
    login(client, "vee")
    assert client.post(f"{BOOK}/tax-forms", json=HARBOR).status_code == 403


def test_a_csv_saves_every_row(margaret, mdb, mctx, client):
    _seeded(mdb, mctx)
    login(client, "jr")
    csv = ("form,tax_year,recipient,payer,last4,box_1,box_1a,box_1b,box_2a,box_3,box_4,box_5,box_7,medicare\n"
           "1099-INT,2025,Margaret,Harbor Savings Bank,2207,58.90,,,,,0,,,\n"
           "1099-DIV,2025,margaret,Lakeside Funds,8812,,312.40,200.00,15.00,,,,,\n")
    r = client.post(f"{BOOK}/tax-forms/csv", files={"file": ("tax_forms.csv", csv.encode(), "text/csv")})
    assert r.status_code == 201 and r.json()["saved"] == 2
    assert [x["headline"] for x in r.json()["results"]] == [
        "1099-INT saved. Harbor Savings Bank isn't in Margaret's inventory.", "1099-DIV saved. Lakeside Funds isn't in Margaret's inventory."]


def test_a_csv_with_a_bad_row_saves_nothing_and_names_the_row(margaret, mdb, client):
    login(client, "jr")
    csv = ("form,tax_year,recipient,payer,last4,box_1\n"
           "1099-INT,2025,Margaret,Harbor Savings Bank,2207,58.90\n"
           "1099-X,2025,Margaret,Somewhere,,1.00\n")
    r = client.post(f"{BOOK}/tax-forms/csv", files={"file": ("tax_forms.csv", csv.encode(), "text/csv")})
    assert (r.status_code, r.json()) == (422, {"error": "Row 3: Choose 1099-INT, 1099-DIV, 1099-R or SSA-1099."})
    mdb.rollback()
    assert mdb.scalar(select(func.count()).select_from(TaxForm)) == 0
    r = client.post(f"{BOOK}/tax-forms/csv", files={"file": ("x.csv", b"payer\nX\n", "text/csv")})
    assert r.json() == {"error": "The CSV needs the columns form, tax_year, recipient and payer."}


def test_a_csv_over_1_mb_is_refused_not_cut_off(margaret, mdb, client):
    login(client, "jr")
    header = "form,tax_year,recipient,payer,last4,box_1\n"
    row = "1099-INT,2025,Margaret,Harbor Savings Bank,2207,58.90\n"
    big = header + row * (1024 * 1024 // len(row) + 10)
    assert 1024 * 1024 < len(big) < 2 * 1024 * 1024
    r = client.post(f"{BOOK}/tax-forms/csv", files={"file": ("tax_forms.csv", big.encode(), "text/csv")})
    assert (r.status_code, r.json()) == (413, {"error": "That file is bigger than 1 MB."})
    mdb.rollback()
    assert mdb.scalar(select(func.count()).select_from(TaxForm)) == 0


def test_a_box_that_is_not_a_plain_amount_is_refused_not_a_500(margaret, mdb, client):
    login(client, "jr")
    for bad in ("1e30", "Infinity", "NaN", "sNaN"):
        csv = f"form,tax_year,recipient,payer,last4,box_1\n1099-INT,2025,Margaret,Harbor Savings Bank,2207,{bad}\n"
        r = client.post(f"{BOOK}/tax-forms/csv", files={"file": ("tax_forms.csv", csv.encode(), "text/csv")})
        assert r.status_code == 422, bad
        assert r.json()["error"].startswith("Row 2: "), bad


def test_a_true_or_non_integer_file_id_is_not_file_one(margaret, mdb, client):
    login(client, "jr")
    up = client.post(f"{BOOK}/files", files={"file": ("1099.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")})
    assert up.status_code == 201 and up.json()["file"]["id"] == 1
    for bad_id in (True, False, "1", 1.0, 1.5, [1]):
        r = client.post(f"{BOOK}/tax-forms", json={**HARBOR, "file_id": bad_id})
        assert (r.status_code, r.json()) == (404, {"error": "No such file."}), bad_id
    mdb.rollback()
    assert mdb.scalar(select(func.count()).select_from(TaxForm)) == 0
    assert client.post(f"{BOOK}/tax-forms", json={**HARBOR, "file_id": 1}).status_code == 201


def test_a_closed_item_is_not_the_match(margaret, client):
    login(client, "jr")
    acct = {"kind": "account", "name": "Old Harbor savings", "owner": "margaret", "institution": "Harbor Savings Bank",
            "last4": "2207", "status": "confirmed", "data_source": "statement", "details": {"type": "savings"},
            "balance_cents": 100000, "balance_on": "2026-10-13"}
    item = client.post(f"{BOOK}/items", json=acct).json()
    r = client.post(f"{BOOK}/tax-forms", json=HARBOR)
    assert r.json()["item_id"] == item["id"]
    client.post(f"{BOOK}/items/{item['id']}/close", json={"closed_on": "2026-10-01", "why": "Moved the money"})
    r = client.post(f"{BOOK}/tax-forms", json={**HARBOR, "tax_year": 2024})
    assert r.status_code == 201
    assert r.json()["item_id"] is None and "matches" not in r.json()["headline"]
