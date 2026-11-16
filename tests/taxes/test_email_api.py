"""The email switch (ruling 11): a person's own, off by default; viewers may set theirs."""
from tests.factories import login, make_person


def test_off_by_default_and_each_persons_own(frozen, signed_in, db):
    assert signed_in.get("/api/b/ours/taxes/email").json() == {"on": False}
    assert signed_in.put("/api/b/ours/taxes/email", json={"on": True}).json() == {"on": True}
    assert signed_in.get("/api/b/ours/taxes/email").json() == {"on": True}
    bad = signed_in.put("/api/b/ours/taxes/email", json={"on": "yes"})
    assert bad.status_code == 422 and bad.json() == {"error": "Choose on or off."}


def test_a_viewer_sets_their_own(frozen, client, ddb, ours):
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "vee")
    assert client.put("/api/b/ours/taxes/email", json={"on": True}).json() == {"on": True}
