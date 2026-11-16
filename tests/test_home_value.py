"""One home value (roadmap 11): Profile's "what the home would sell for" is the Home property account's balance."""
from tests.factories import make_user


def login(client, db):
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})


def homes(client):
    return [a for a in client.get("/api/b/ours/accounts").json()["accounts"] if a["type"] == "property"]


def fact(client, key="home.value_cents"):
    return client.get("/api/b/ours/facts").json()["facts"].get(key, {}).get("value")


def test_profile_value_makes_a_home_account(client, db):
    login(client, db)
    assert homes(client) == []
    r = client.post("/api/b/ours/facts", json={"key": "home.value_cents", "value": "92000000", "as_of": "2026-10-20"})
    assert r.status_code == 201
    [home] = homes(client)
    assert (home["name"], home["source"], home["owner"], home["balance_cents"], home["as_of"]) == \
        ("Home", "manual", "joint", 92000000, "2026-10-20")


def test_a_later_profile_value_updates_the_same_account(client, db):
    login(client, db)
    client.post("/api/b/ours/facts", json={"key": "home.value_cents", "value": "92000000", "as_of": "2026-01-02"})
    client.post("/api/b/ours/facts", json={"key": "home.value_cents", "value": "95000000", "as_of": "2026-10-20"})
    [home] = homes(client)
    assert (home["balance_cents"], home["as_of"]) == (95000000, "2026-10-20")


def test_a_balance_on_the_home_account_is_profiles_value(client, db):
    login(client, db)
    client.post("/api/b/ours/facts", json={"key": "home.value_cents", "value": "92000000", "as_of": "2026-10-01"})
    [home] = homes(client)
    r = client.post(f"/api/b/ours/accounts/{home['id']}/balance", json={"balance_cents": 97500000, "as_of": "2026-10-25"})
    assert r.status_code == 200
    assert fact(client) == "97500000"
    # An older balance (catching up history) doesn't overwrite a later Profile answer.
    client.post(f"/api/b/ours/accounts/{home['id']}/balance", json={"balance_cents": 80000000, "as_of": "2025-06-01"})
    assert fact(client) == "97500000"


def test_an_existing_property_account_is_used_not_duplicated(client, db):
    login(client, db)
    made = client.post("/api/b/ours/accounts", json={"name": "Our house", "type": "property", "owner": "joint",
                                                      "balance_cents": 88000000, "as_of": "2026-09-01"}).json()
    client.post("/api/b/ours/facts", json={"key": "home.value_cents", "value": "93000000", "as_of": "2026-10-20"})
    [home] = homes(client)
    assert (home["id"], home["name"], home["balance_cents"]) == (made["id"], "Our house", 93000000)


def test_with_two_properties_the_one_called_home_is_used(client, db):
    login(client, db)
    for name, cents in (("Rental", 50000000), ("Home", 90000000)):
        client.post("/api/b/ours/accounts", json={"name": name, "type": "property", "owner": "joint", "balance_cents": cents})
    client.post("/api/b/ours/facts", json={"key": "home.value_cents", "value": "91000000"})
    by_name = {a["name"]: a["balance_cents"] for a in homes(client)}
    assert by_name == {"Rental": 50000000, "Home": 91000000}


def test_with_two_properties_and_no_home_the_largest_is_the_home(client, db):
    """Final review: a third account for the same house would count it twice in net worth."""
    login(client, db)
    for name, cents in (("Our house", 90000000), ("Rental", 40000000)):
        client.post("/api/b/ours/accounts", json={"name": name, "type": "property", "owner": "joint", "balance_cents": cents})
    client.post("/api/b/ours/facts", json={"key": "home.value_cents", "value": "92000000"})
    by_name = {a["name"]: a["balance_cents"] for a in homes(client)}
    assert by_name == {"Our house": 92000000, "Rental": 40000000}


def test_a_hidden_home_account_comes_back_rather_than_a_second(client, db):
    login(client, db)
    home = client.post("/api/b/ours/accounts", json={"name": "Home", "type": "property", "owner": "joint",
                                                      "balance_cents": 80000000}).json()
    client.patch(f"/api/b/ours/accounts/{home['id']}", json={"is_active": False})
    client.post("/api/b/ours/facts", json={"key": "home.value_cents", "value": "91000000"})
    [again] = homes(client)
    assert (again["id"], again["is_active"], again["balance_cents"]) == (home["id"], True, 91000000)


def test_a_balance_on_another_property_leaves_profile_alone(client, db):
    login(client, db)
    client.post("/api/b/ours/facts", json={"key": "home.value_cents", "value": "92000000", "as_of": "2026-10-01"})
    rental = client.post("/api/b/ours/accounts", json={"name": "Rental", "type": "property", "owner": "joint",
                                                        "balance_cents": 40000000}).json()
    client.post(f"/api/b/ours/accounts/{rental['id']}/balance", json={"balance_cents": 41000000})
    assert fact(client) == "92000000"


def test_the_link_is_not_a_fact_anyone_can_set(client, db):
    login(client, db)
    r = client.post("/api/b/ours/facts", json={"key": "home.account_id", "value": "1"})
    assert r.status_code == 422
