import pytest

NAME = "Enter a name of up to 80 characters."


def test_me_carries_the_profile_marks(signed_in):
    assert signed_in.get("/api/auth/me").json()["books"][0]["profile"] == {"seen": False, "confirmed": False, "later_until": None}
    signed_in.post("/api/b/ours/profile/seen", json={})
    assert signed_in.get("/api/auth/me").json()["books"][0]["profile"]["seen"] is True


def test_each_person_changes_their_own_name(signed_in):
    r = signed_in.patch("/api/auth/me", json={"display_name": "  Jordan  "})
    assert r.status_code == 200 and r.json()["user"]["display_name"] == "Jordan"
    assert signed_in.get("/api/auth/me").json()["user"]["display_name"] == "Jordan"
    assert signed_in.get("/api/b/ours/profile").json()["names"]["jr"] == "Jordan"


@pytest.mark.parametrize("body,error", [
    ({"display_name": ""}, NAME),
    ({"display_name": "   "}, NAME),
    ({"display_name": "x" * 81}, NAME),
    ({"display_name": 7}, NAME),
    ({}, NAME),
    ({"display_name": "Jo", "username": "boss"}, "Unknown field: username."),
])
def test_name_changes_are_checked(signed_in, body, error):
    r = signed_in.patch("/api/auth/me", json=body)
    assert r.status_code == 422 and r.json() == {"error": error}
    assert signed_in.get("/api/auth/me").json()["user"]["display_name"] == "JR"


def test_name_change_needs_json_and_sign_in(signed_in):
    assert signed_in.patch("/api/auth/me", content=b'{"display_name": "Jo"}').status_code == 415
    signed_in.post("/api/auth/logout")
    assert signed_in.patch("/api/auth/me", json={"display_name": "Jo"}).status_code == 401


ON_OFF = "Choose on or off."


def test_me_says_the_switches_were_never_chosen_until_they_are(signed_in):
    assert signed_in.get("/api/auth/me").json()["user"]["prefs"] == {"celebrations": None, "sound": None}
    r = signed_in.patch("/api/auth/me", json={"celebrations": False})
    assert r.status_code == 200 and r.json()["user"]["prefs"] == {"celebrations": False, "sound": None}
    signed_in.patch("/api/auth/me", json={"sound": True})
    assert signed_in.get("/api/auth/me").json()["user"]["prefs"] == {"celebrations": False, "sound": True}
    assert signed_in.get("/api/auth/me").json()["user"]["display_name"] == "JR"          # the name is left alone


def test_the_switches_are_each_persons_own(client, ddb, ours):
    from tests.factories import login, make_person
    make_person(ddb, "jr", [(ours.id, "manager")])
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "jr")
    client.patch("/api/auth/me", json={"celebrations": False, "sound": True})
    login(client, "vee")
    assert client.get("/api/auth/me").json()["user"]["prefs"] == {"celebrations": None, "sound": None}
    assert client.patch("/api/auth/me", json={"sound": True}).status_code == 200       # a viewer chooses their own


@pytest.mark.parametrize("body", [{"celebrations": "off"}, {"sound": 1}, {"celebrations": None}, {"sound": []}])
def test_a_switch_takes_only_true_or_false(signed_in, body):
    r = signed_in.patch("/api/auth/me", json=body)
    assert r.status_code == 422 and r.json() == {"error": ON_OFF}
    assert signed_in.get("/api/auth/me").json()["user"]["prefs"] == {"celebrations": None, "sound": None}


def test_a_name_and_a_switch_can_change_together(signed_in):
    r = signed_in.patch("/api/auth/me", json={"display_name": "Jordan", "celebrations": True})
    assert r.json()["user"]["display_name"] == "Jordan" and r.json()["user"]["prefs"]["celebrations"] is True
