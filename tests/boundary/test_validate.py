from steward_boundary.schema import ALIAS, BOOL, DATE, INT, MONTH, NUM, arr, enum, free_text, nullable, obj
from steward_boundary.validate import untyped_string_paths, validate, walk_strings

S = obj({"who": ALIAS, "on": DATE, "month": nullable(MONTH), "n": INT, "x": NUM, "ok": BOOL,
         "kind": enum(("a", "b")), "rows": arr(obj({"sym": nullable(free_text(12))}), 2)})
GOOD = {"who": "Person 1", "on": "2026-10-19", "month": None, "n": 3, "x": 1.5, "ok": True, "kind": "a",
        "rows": [{"sym": "VTI"}, {"sym": None}]}


def test_a_good_value_passes():
    assert validate(S, GOOD) == []


def test_dates_and_months_are_ascii_iso():
    """Full-width digits and impossible months don't pass a typed date or month (Task 2.5)."""
    for on in ("\uff12\uff10\uff12\uff16-10-19", "1234-56-78", "2026-13-01", "2026-10-32"):
        assert validate(S, {**GOOD, "on": on}) == ["$.on: doesn't match the allowed shape"], on
    assert validate(S, {**GOOD, "month": "2026-00"}) and validate(S, {**GOOD, "month": "\uff12\uff10\uff12\uff16-10"})


def test_each_kind_of_mistake_is_named_by_path_without_the_value():
    bad = {**GOOD, "who": "Margaret", "n": True, "kind": "c", "extra": 1, "rows": [{"sym": "x" * 13}] * 3}
    del bad["on"]
    errs = validate(S, bad)
    assert "$.who: doesn't match the allowed shape" in errs
    assert "$.n: expected a whole number" in errs
    assert "$.kind: not one of the allowed values" in errs
    assert "$: has 1 field(s) that aren't allowed" in errs
    assert "$.on: missing" in errs
    assert "$.rows: too many items" in errs
    assert "$.rows[0].sym: matches none of the allowed shapes" in errs
    assert not any("Margaret" in e for e in errs)


def test_walk_strings_reports_each_strings_kind():
    got = sorted(walk_strings(S, GOOD))
    assert got == [("$.kind", "enum", "a"), ("$.on", "date", "2026-10-19"), ("$.rows[0].sym", "free_text", "VTI"),
                   ("$.who", "alias", "Person 1")]


def test_untyped_strings_are_found():
    assert untyped_string_paths(obj({"a": {"type": "string"}, "b": arr(nullable({"type": "string"}))})) == [
        "$.a", "$.b[]"]
    assert untyped_string_paths(S) == []


def test_input_dates_use_format():
    s = obj({"start": {"type": "string", "format": "date"}})
    assert validate(s, {"start": "2026-10-01"}) == []
    assert validate(s, {"start": "Oct 1"}) == ["$.start: not a date"]


def test_a_disallowed_key_is_counted_never_named():
    errs = validate(obj({"a": DATE}), {"a": "2026-01-01", "Margaret Ellis 4111": 1})
    assert errs == ["$: has 1 field(s) that aren't allowed"]
    assert not any("Margaret" in e or "4111" in e for e in errs)
