from datetime import date

from steward.db.models import BalanceSnapshot
from tests.factories import add_fact, make_account

H = "/api/b/ours/profile/home"


def snap(db, a, cents, day=date(2026, 10, 1)):
    db.add(BalanceSnapshot(account_id=a.id, as_of=day, balance_cents=cents))
    db.commit()


def test_an_empty_household_has_no_answer_and_nothing_listed(frozen, signed_in):
    assert signed_in.get(H).json() == {"owns_home": None, "where_you_live": None, "properties": [], "cars": [],
                                       "loans": [], "mortgages": []}


def test_homes_mortgages_and_cars_as_profile_shows_them(frozen, signed_in, db):
    home, cabin = make_account(db, "Home", type="property"), make_account(db, "Cabin", type="property")
    m1, m2 = make_account(db, "Chase mortgage", type="mortgage"), make_account(db, "Cabin loan", type="mortgage")
    car, loan = make_account(db, "Subaru", type="vehicle"), make_account(db, "Auto loan", type="loan")
    spare = make_account(db, "Old mortgage", type="mortgage")
    for a, cents in ((home, 125_000_000), (cabin, 40_000_000), (m1, -57_130_000), (m2, -9_000_000), (car, 2_000_000),
                     (loan, -1_200_000), (spare, -100_000)):
        snap(db, a, cents)
    home.loan_id, cabin.loan_id, car.loan_id, m1.rate_bp = m1.id, m2.id, loan.id, 287
    db.commit()
    for k, v in (("home.account_id", str(home.id)), ("mortgage.payment_cents", "268000"), ("mortgage.payoff_date", "2051-03-01")):
        add_fact(db, k, v)
    body = signed_in.get(H).json()
    assert (body["owns_home"], body["where_you_live"]) == (True, home.id)
    where, other = body["properties"]
    assert (where["name"], where["value_cents"], where["mortgage"]["name"], where["mortgage"]["balance_cents"]) == (
        "Home", 125_000_000, "Chase mortgage", 57_130_000)
    assert (where["mortgage"]["rate_bp"], where["mortgage"]["payment_cents"], where["mortgage"]["payoff_date"]) == (287, 268_000, "2051-03-01")
    assert (other["mortgage"]["name"], other["mortgage"]["payment_cents"], other["mortgage"]["payoff_date"]) == ("Cabin loan", None, None)
    assert [(c["name"], c["loan"]["name"]) for c in body["cars"]] == [("Subaru", "Auto loan")]
    assert [m["name"] for m in body["mortgages"]] == ["Old mortgage"] and body["loans"] == []


def test_where_you_live_moves_the_link_and_the_value_and_undoes(frozen, signed_in, db):
    home, cabin = make_account(db, "Home", type="property"), make_account(db, "Cabin", type="property")
    snap(db, home, 125_000_000)
    snap(db, cabin, 40_000_000)
    add_fact(db, "home.account_id", str(home.id))
    r = signed_in.put(f"{H}/where", json={"account_id": cabin.id})
    assert r.status_code == 200 and r.json()["where_you_live"] == cabin.id
    facts = signed_in.get("/api/b/ours/facts").json()["facts"]
    assert (facts["home.account_id"]["value"], facts["home.value_cents"]["value"]) == (str(cabin.id), "40000000")
    assert signed_in.post(f"/api/b/ours/undo/{r.json()['undo']}").status_code == 200
    assert signed_in.get(H).json()["where_you_live"] == home.id
    assert signed_in.put(f"{H}/where", json={"account_id": 999}).json() == {"error": "Choose one of your homes."}


def test_a_property_takes_a_mortgage_once_and_a_car_a_loan(frozen, signed_in, db):
    home, cabin = make_account(db, "Home", type="property"), make_account(db, "Cabin", type="property")
    m, loan, chk = make_account(db, "Mortgage", type="mortgage"), make_account(db, "Auto loan", type="loan"), make_account(db, "Checking")
    A = "/api/b/ours/accounts"
    assert signed_in.patch(f"{A}/{home.id}", json={"loan_id": m.id}).json()["loan_id"] == m.id
    r = signed_in.patch(f"{A}/{cabin.id}", json={"loan_id": m.id})
    assert r.status_code == 409 and r.json() == {"error": "That mortgage is on another home already."}
    assert signed_in.patch(f"{A}/{cabin.id}", json={"loan_id": loan.id}).json() == {"error": "Choose one of your mortgage accounts."}
    r = signed_in.patch(f"{A}/{chk.id}", json={"loan_id": m.id})
    assert r.json() == {"error": "Only a vehicle or a home has a loan against it here."}


def test_the_detected_payment_rides_with_where_you_live(frozen, signed_in, db):
    from tests.test_mortgage_payment import pay
    home, m, chk = make_account(db, "Home", type="property"), make_account(db, "Mortgage", type="mortgage"), make_account(db)
    home.loan_id = m.id
    db.commit()
    add_fact(db, "home.account_id", str(home.id))
    pay(db, chk, m, date(2026, 10, 1), 268_000)
    assert signed_in.get(H).json()["properties"][0]["mortgage"]["detected"] == {
        "posted_at": "2026-10-01", "amount_cents": 268_000, "varied": None}
