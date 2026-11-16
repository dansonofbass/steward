"""Spec 4.2: every result string is typed (the schema walk); spec 8.2: every tool is strict (but plan_what_if) with no extra fields; the
tool list is sorted and serialized the same every time (spec 8.3)."""
from steward_boundary import tools as T
from steward_boundary.canonical import canonical
from steward_boundary.validate import untyped_string_paths

EVERY = {"book_summary", "accounts", "balance_history", "cash_flow", "spending_by_category", "recurring", "holdings",
         "debts", "merchant_detail"}
HOUSEHOLD = {"facts", "plan_result", "plan_what_if", "plan_lever_impacts", "savings_checklist"}
PARENT = {"inventory", "money_in_monthly", "premiums", "flags", "care_projection"}
UNSUPPORTED = {"minimum", "maximum", "minLength", "maxLength", "pattern", "maxItems", "x-kind", "multipleOf"}


def test_the_nineteen_tools_and_their_books():
    assert [t.name for t in T.TOOLS] == sorted(EVERY | HOUSEHOLD | PARENT)
    for t in T.TOOLS:
        want = ("household", "parent") if t.name in EVERY else ("household",) if t.name in HOUSEHOLD else ("parent",)
        assert t.books == want, t.name


def test_merchant_detail_rows_are_typed_and_capped():
    spec = T.BY_NAME[T.MERCHANT]
    assert (T.MERCHANT_DAYS, T.MERCHANT_ROWS) == (92, 200)
    assert spec.status == "Asking for store names"
    row = {"date": "2026-10-18", "amount_cents": -1599, "category": "subscriptions", "merchant": "StreamBox",
           "account": "Account 2"}
    ok = {"rows": [row], "payees": [{"payee": "Payee 4", "name": "Bright Smile Ortho"}], "more": False}
    assert T.validate_result(T.MERCHANT, ok) == []
    assert T.validate_result(T.MERCHANT, {**ok, "rows": [{**row, "account": "Checking"}]})
    assert T.validate_result(T.MERCHANT, {**ok, "rows": [{**row, "merchant": "x" * 61}]})
    assert T.validate_result(T.MERCHANT, {**ok, "rows": [row] * 201})
    assert T.validate_input(T.MERCHANT, {"reason": "Totals can't name them.", "start": "2026-09-01", "end": "2026-10-18",
                                         "category": None, "payees": None}) == []
    assert T.validate_input(T.MERCHANT, {"start": "2026-09-01", "end": "2026-10-18", "category": None, "payees": None})


def test_the_two_store_name_errors_are_results_claude_can_get():
    assert T.DECLINED == "The person declined to share store names for this question. Answer from totals."
    assert T.NEEDS_MANAGER == "Store names need a manager's OK, and the person asking can't give it. Answer from totals."
    for e in (T.DECLINED, T.NEEDS_MANAGER):
        assert e in T.ERRORS and T.validate_result(T.MERCHANT, {"error": e}, is_error=True) == []


def test_no_result_schema_has_an_untyped_string():
    for t in T.TOOLS:
        assert untyped_string_paths(t.result_schema) == [], t.name
    assert untyped_string_paths(T.ERROR_RESULT) == []


def _objects(s):
    if isinstance(s, dict):
        if s.get("type") == "object":
            yield s
        for v in s.values():
            yield from _objects(v)
    elif isinstance(s, list):
        for v in s:
            yield from _objects(v)


def _keys(s):
    if isinstance(s, dict):
        for k, v in s.items():
            yield k
            if k != "properties":
                yield from _keys(v)
            else:
                for prop in v.values():
                    yield from _keys(prop)
    elif isinstance(s, list):
        for v in s:
            yield from _keys(v)


def test_holding_symbols_are_typed_by_their_shape():
    from steward_boundary.text import typed_ok
    from steward_boundary.validate import walk_strings
    content = {"holdings": [{"symbol": "VTI", "asset_class": "us_stock", "account": "Account 1", "value_cents": 1,
                             "cost_basis_cents": None, "as_of": "2026-10-01"}], "totals_by_asset_class": []}
    assert T.validate_result("holdings", content) == []
    kinds = {p: k for p, k, _ in walk_strings(T.result_schema("holdings", False), content)}
    assert kinds["$.holdings[0].symbol"] == "symbol"
    for bad in ("vti", "VTI1", "TOOLONG", "a@b.co", ""):
        assert T.validate_result("holdings", {**content, "holdings": [{**content["holdings"][0], "symbol": bad}]})
    assert typed_ok("symbol", "VTI") and not typed_ok("symbol", "VTI1")


def test_input_schemas_are_strict_compatible():
    for t in T.TOOLS:
        for o in _objects(t.input_schema):
            assert o["additionalProperties"] is False, t.name
            assert o["required"] == [k for k in o["properties"] if k in o["required"]], t.name
        assert not (set(_keys(t.input_schema)) & UNSUPPORTED), t.name


# Anthropic compiles every strict schema in a request into one grammar. It refuses the request when more than 16
# parameters are unions (a type list, anyOf or oneOf) or more than 24 are optional (not in required), and, past an
# unpublished size, with "Schema is too complex" (both 400s of 2026-10-25). Each optional parameter roughly doubles
# the grammar, so strict schemas keep almost none; a tool whose input is mostly optional is sent without strict and
# the NAS's validate_input checks it. The tool list is one request's worth, so the strict ones are counted together.
UNION_LIMIT, STRICT_OPTIONAL_LIMIT = 16, 4


def _props(s):
    """Every (property schema, optional) pair in a schema, through nested objects, array items and union branches."""
    if not isinstance(s, dict):
        return
    for branch in s.get("anyOf", []) + s.get("oneOf", []):
        yield from _props(branch)
    if "items" in s:
        yield from _props(s["items"])
    required = set(s.get("required", []))
    for k, v in (s.get("properties") or {}).items():
        yield v, k not in required
        yield from _props(v)


def _is_union(s):
    return isinstance(s.get("type"), list) or "anyOf" in s or "oneOf" in s


def test_strict_schemas_stay_under_the_union_and_optional_limits():
    props = [p for d in T.definitions() if d["strict"] for p in _props(d["input_schema"])]
    assert sum(_is_union(s) for s, _ in props) <= UNION_LIMIT
    assert sum(optional for _, optional in props) <= STRICT_OPTIONAL_LIMIT


def test_only_plan_what_if_is_sent_without_strict():
    assert [d["name"] for d in T.definitions() if not d["strict"]] == ["plan_what_if"]


def test_what_if_levers_are_optional_and_not_nullable():
    levers = T.BY_NAME["plan_what_if"].input_schema["properties"]["levers"]
    assert T.BY_NAME["plan_what_if"].input_schema["required"] == ["levers"]
    assert levers["required"] == [] and set(levers["properties"]) == {*T.WHAT_IF_INTS, "college_levels",
                                                                     "full_ss_benefits"}
    assert not any(_is_union(s) for s in levers["properties"].values())
    assert "leave out the levers that stay as they are" in T.BY_NAME["plan_what_if"].description
    assert T.validate_input("plan_what_if", {"levers": {}}) == []
    assert T.validate_input("plan_what_if", {"levers": {"save_more_monthly_cents": 50_000,
                                                        "college_levels": ["private"], "full_ss_benefits": False}}) == []
    # An older caller's nulls still mean "unchanged"; a wrong type or an unknown lever is still refused.
    assert T.validate_input("plan_what_if", {"levers": {"spending_pct": None, "college_levels": None,
                                                        "save_more_monthly_cents": 1}}) == []
    assert T.validate_input("plan_what_if", {"levers": {"spending_pct": "90"}})
    assert T.validate_input("plan_what_if", {"levers": {"retire_age": 60}})
    assert T.validate_input("plan_what_if", {}) == ["$.levers: missing"]
    # A null for a required field is still refused.
    assert T.validate_input("balance_history", {"months": 12, "by_account_type": None})


def test_definitions_are_sorted_strict_and_stable():
    d = T.definitions()
    assert [x["name"] for x in d] == sorted(x["name"] for x in d)
    assert all(isinstance(x["strict"], bool) and set(x) == {"name", "description", "input_schema", "strict"} for x in d)
    assert canonical(d) == canonical(T.definitions())


def test_descriptions_and_status_words_are_plain():
    for t in T.TOOLS:
        # merchant_detail's description (plan B Task 1) runs 660 characters: it has to say when to ask and how
        # the approval works, so the cap is 700.
        assert 40 <= len(t.description) <= 700 and "!" not in t.description, t.name
        # Plan B ruling 15: "Looking at", "Trying" and "Asking for" are the status openings.
        assert t.status.startswith(("Looking at", "Trying", "Asking for")) and t.status[0].isupper(), t.name
        for word in ("elder", "senior", "patient", "jr", "JR", "Sam", "Margaret"):
            assert word not in t.description.split(), (t.name, word)


def test_validate_input_and_results():
    assert T.validate_input("balance_history", {"months": 12, "by_account_type": False}) == []
    assert T.validate_input("balance_history", {"months": 12}) == ["$.by_account_type: missing"]
    assert T.validate_input("nope", {}) == ["$: no such tool"]
    assert T.validate_result("debts", {"debts": [{"account": "Account 2", "kind": "mortgage", "balance_cents": 1,
                                                  "rate_bp": 625.0, "payment_cents": None, "payoff_month": "2048-06"}]}) == []
    assert T.validate_result("debts", {"error": "Not in this book."}, is_error=True) == []
    assert T.validate_result("debts", {"error": "Something else."}, is_error=True)
