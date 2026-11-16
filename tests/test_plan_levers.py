import json

import pytest

from steward.engine import Levers, ObservedTry, clamp
from steward.engine.synthetic import synthetic_household
from steward.services.plan_levers import (
    LEVER_KEYS, LeverError, LeverState, lever_specs, parse_levers, resolve_state, state_from_json, state_json,
)

HH = synthetic_household().household          # plan year 2026, JR 44, three children at in-state public
SEEN = ObservedTry(consulting_12mo_cents=600_000, gift_12mo_cents=1_000_000, spouse_earnings_cents=0)


@pytest.mark.parametrize("data,message", [
    ({"spending_pct": "90"}, "Spending in retirement must be a whole number."),
    ({"consulting_cents": True}, "Consulting income must be a whole number."),
    ({"jr_claim_age": 67.5}, "{person1}'s claiming age must be a whole number."),
    ({"gift_cents": None}, "Yearly gift must be a whole number."),
    ({"full_ss_benefits": "no"}, "Full Social Security benefits must be on or off."),
    ({"college_levels": "private"}, "College types must be a list with one level per child."),
    ({"college_levels": [1, 2, 3]}, "College types must be a list with one level per child."),
    ({"save_more_monthly_cents": 10**13}, "Save more each month is too large."),
    ({"retire_at": 55}, "There's no lever called retire_at."),
    ([1, 2], "The lever values weren't understood."),
])
def test_parse_levers_refuses_wrong_types_in_plain_words(data, message):
    with pytest.raises(LeverError) as e:
        parse_levers(data, Levers())
    assert str(e.value) == message


def test_parse_levers_accepts_integral_floats_and_keeps_the_base():
    lv = parse_levers({"jr_claim_age": 70.0, "college_levels": None, "full_ss_benefits": True}, Levers())
    assert lv.jr_claim_age == 70 and isinstance(lv.jr_claim_age, int)
    assert lv.college_levels is None and lv.full_ss_benefits is True
    assert parse_levers(None, Levers(spending_pct=95)) == Levers(spending_pct=95)


def test_defaults_follow_the_vault():
    state, notes = resolve_state({}, None, HH, SEEN)
    assert state.assumed == clamp(Levers(), HH)
    t = state.trial
    assert (t.consulting_cents, t.gift_cents, t.gift_until_year, t.jr_claim_age, t.spending_pct, t.save_more_monthly_cents) == \
        (600_000, 1_000_000, 2036, 70, 90, 50_000)
    assert state.pinned == frozenset() and notes == {"spouse_earnings": "No history yet"}
    bare, notes = resolve_state({}, None, HH, ObservedTry())
    assert bare.trial.consulting_cents == 100_000 and set(notes) == {"consulting", "gift", "spouse_earnings"}


def test_sending_a_try_value_pins_it_and_pinned_values_stay():
    state, notes = resolve_state({"try": {"consulting_cents": 2_000_000, "spouse_earnings_cents": 6_000_000}}, None, HH, SEEN)
    assert state.trial.consulting_cents == 2_000_000 and state.trial.spouse_earnings_cents == 6_000_000
    assert state.pinned == {"consulting", "spouse_earnings"} and notes == {}
    later, _ = resolve_state({}, state, HH, ObservedTry(consulting_12mo_cents=900_000))
    assert later.trial.consulting_cents == 2_000_000          # pinned: stays
    assert later.trial.gift_cents == 50_000                   # unpinned: follows the vault (no gift now: first step)


def test_unpinning_returns_to_the_vault_figure():
    pinned, _ = resolve_state({"try": {"consulting_cents": 2_000_000}}, None, HH, SEEN)
    back, _ = resolve_state({"pinned": []}, pinned, HH, SEEN)
    assert back.trial.consulting_cents == 600_000 and back.pinned == frozenset()


def test_assumed_values_are_clamped_and_kept_from_the_saved_plan():
    state, _ = resolve_state({"assumed": {"spending_pct": 300, "jr_claim_age": 75, "consulting_cents": -5}}, None, HH, SEEN)
    assert (state.assumed.spending_pct, state.assumed.jr_claim_age, state.assumed.consulting_cents) == (130, 70, 0)
    again, _ = resolve_state({"assumed": {"jr_claim_age": 68}}, state, HH, SEEN)
    assert again.assumed.spending_pct == 130 and again.assumed.jr_claim_age == 68


def test_saved_college_levels_survive_a_deleted_child():
    three = LeverState(Levers(college_levels=("private",) * 3), Levers(), frozenset({"college"}))
    two_kids = synthetic_household(children=HH.children[:2]).household
    state, _ = resolve_state({}, three, two_kids, SEEN)
    assert state.assumed.college_levels == ("in_state_public", "in_state_public")
    assert len(state.trial.college_levels) == 2


def test_body_shape_is_checked():
    for body, message in (({"assumed": [1]}, "The lever values weren't understood."),
                          ({"pinned": "consulting"}, "The pinned levers weren't understood."),
                          ({"pinned": ["retire"]}, "There's no lever called retire."),
                          ({"levers": {}}, "Unknown field: levers.")):
        with pytest.raises(LeverError) as e:
            resolve_state(body, None, HH, SEEN)
        assert str(e.value) == message


def test_state_json_round_trip_and_garbage():
    state, _ = resolve_state({"try": {"consulting_cents": 2_000_000}}, None, HH, SEEN)
    text = state_json(state)
    assert json.loads(text)["pinned"] == ["consulting"] and json.loads(text)["try"]["consulting_cents"] == 2_000_000
    assert state_from_json(text) == state
    for garbage in ("", "[]", '{"assumed": {}}', '{"assumed": {"x": 1}, "try": {}}',
                    '{"assumed": {}, "try": {}, "pinned": ["nope"]}'):
        assert state_from_json(garbage) is None


def test_lever_specs_use_display_names():
    specs = {s["key"]: s for s in lever_specs({"jr": "Alex", "spouse": "Sam", "joint": "Joint"})}
    assert list(specs) == list(LEVER_KEYS)
    assert specs["jr_claim"]["label"] == "Alex claims Social Security at"
    assert specs["spouse_earnings"]["label"] == "Sam's earnings, a year"
    assert specs["spouse_claim"]["label"] == "Sam claims Social Security at"
    assert specs["save_more"]["scale"] == {"lo": 0, "hi": 300_000, "step": 5_000}
    assert specs["college"]["scale"] is None and specs["consulting"]["fields"] == ["consulting_cents", "consulting_until_age"]
