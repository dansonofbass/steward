"""GET /api/next-dollar (cash-flow and tax spec section 6): read-only, after plan setup, household books only."""
from tests.factories import make_ready_household, make_user

FINISH = "Finish setting up the plan first."


def ready(db):
    make_user(db, "sam", "sam@x.com", "Sam")
    return make_ready_household(db)


def test_before_setup_it_says_finish_setup(frozen, signed_in, db):
    r = signed_in.get("/api/b/ours/next-dollar")
    assert r.status_code == 409 and r.json()["error"] == FINISH and r.json()["setup"][0]["key"] == "household"


def test_the_ready_household_gets_its_steps(frozen, signed_in, db):
    ready(db)
    r = signed_in.get("/api/b/ours/next-dollar")
    assert r.status_code == 200
    body = r.json()
    assert body["year"] == 2026 and body["settings"] == {"cash_months": 3, "debt_rate_bp": 700}
    assert [s["key"] for s in body["steps"]] == ["cash", "match", "hsa", "debt", "retirement", "invest"]
    hsa = body["steps"][2]
    assert hsa == {"key": "hsa", "title": "HSA", "status": "ask", "why": "Does your health plan qualify for an HSA?",
                   "in_cents": None, "room_cents": None, "rules_year": None, "choice": None, "needs_rate": [],
                   "payroll": None}
    assert body["steps"][1]["payroll"] == {"key": "jr.payroll_k401_cents", "cents": None}
    assert body["steps"][1]["status"] == "done"
    assert body["steps"][4]["choice"] == "roth_ira" and body["steps"][4]["rules_year"] == 2026
    invest = body["steps"][5]
    assert invest["needs_rate"] == [{"account_id": invest["needs_rate"][0]["account_id"], "name": "Mortgage"}]
    assert "backdoor Roth" in body["backdoor_sheet"]


def test_answers_change_the_steps(frozen, signed_in, db):
    ready(db)
    assert signed_in.post("/api/b/ours/facts", json={"key": "health.hsa_plan", "value": "no"}).status_code == 201
    assert signed_in.post("/api/b/ours/facts", json={"key": "next_dollar.cash_months", "value": "12"}).status_code == 201
    body = signed_in.get("/api/b/ours/next-dollar").json()
    assert "hsa" not in [s["key"] for s in body["steps"]]
    assert body["settings"]["cash_months"] == 12 and body["steps"][0]["title"] == "Cash for 12 months of spending"


def test_it_is_read_only_and_needs_sign_in(frozen, signed_in, db):
    ready(db)
    from steward.api.plan import router
    methods = {m for r in router.routes if r.path == "/next-dollar" for m in r.methods}
    assert methods == {"GET"}                            # Steward suggests; it never moves money
    signed_in.cookies.clear()
    assert signed_in.get("/api/b/ours/next-dollar").status_code == 401


def test_the_sweeps_see_the_route_as_book_scoped_and_read_only(app):
    from tests.test_isolation_sweep import api_routes
    found = [(m, calls) for p, m, _, calls in api_routes(app) if p == "/api/b/{slug}/next-dollar"]
    assert [m for m, _ in found] == ["GET"]
    from steward.deps import household_only, open_book
    assert open_book in found[0][1] and household_only in found[0][1]


def test_a_payroll_amount_counts_toward_the_hsa(frozen, signed_in, db):
    """Final review ruling I3: entered as a dated fact; blank hides the HSA's room."""
    ready(db)
    signed_in.post("/api/b/ours/facts", json={"key": "health.hsa_plan", "value": "yes"})
    hsa = next(s for s in signed_in.get("/api/b/ours/next-dollar").json()["steps"] if s["key"] == "hsa")
    assert hsa["payroll"] == {"key": "jr.payroll_hsa_cents", "cents": None} and hsa["room_cents"] is None
    assert signed_in.post("/api/b/ours/facts", json={"key": "jr.payroll_hsa_cents", "value": "600000"}).status_code == 201
    hsa = next(s for s in signed_in.get("/api/b/ours/next-dollar").json()["steps"] if s["key"] == "hsa")
    assert hsa["payroll"] == {"key": "jr.payroll_hsa_cents", "cents": 600_000}
    assert (hsa["in_cents"], hsa["room_cents"]) == (600_000, 875_000 - 600_000)


def test_a_viewer_cannot_enter_a_payroll_amount(frozen, client, ddb, ours, db):
    from tests.factories import login, make_person
    ready(db)
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "vee")
    assert client.post("/api/b/ours/facts", json={"key": "jr.payroll_hsa_cents", "value": "1"}).status_code == 403
