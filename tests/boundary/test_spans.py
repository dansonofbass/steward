import pytest

from steward_boundary.spans import Edit, apply, merge, outside, overlaps, shift


def test_overlapping_edits_merge_into_one_that_covers_both():
    """The wider's label wins, but nothing of the narrower is left behind (Task 2 security review)."""
    a, b, c = Edit(0, 4, "[name]", "gliner"), Edit(2, 10, "[organization]", "gliner"), Edit(12, 14, "[name]", "steward")
    assert merge([a, b, c]) == [Edit(0, 10, "[organization]", "gliner"), c]


def test_a_chain_of_overlaps_merges_whole():
    edits = [Edit(0, 6, "[name]", "gliner"), Edit(5, 9, "[phone]", "presidio"), Edit(8, 14, "[name]", "gliner")]
    assert merge(edits) == [Edit(0, 14, "[name]", "gliner")]
    text = "Margaret Q Ellis!"
    assert apply(text, edits)[0] == "[name]is!"


def test_touching_edits_both_stay_and_empty_ones_go():
    assert merge([Edit(0, 3, "x", "steward"), Edit(3, 5, "y", "steward"), Edit(6, 6, "z", "steward")]) == [
        Edit(0, 3, "x", "steward"), Edit(3, 5, "y", "steward")]


def test_apply_returns_chips_in_the_new_text():
    text = "Margaret paid Linda Park"
    new, chips = apply(text, [Edit(0, 8, "Parent", "steward"), Edit(14, 24, "[name]", "gliner")])
    assert new == "Parent paid [name]"
    assert [new[c["start"]:c["end"]] for c in chips] == ["Parent", "[name]"]
    assert [c["layer"] for c in chips] == ["steward", "gliner"]


def test_apply_refuses_edits_outside_the_text():
    with pytest.raises(ValueError):
        apply("short", [Edit(3, 9, "[name]", "steward")])
    with pytest.raises(ValueError):
        apply("short", [Edit(-1, 2, "[name]", "steward")])


def test_shift_moves_earlier_chips_past_later_edits():
    first, chips = apply("Robert asked Bob Smith about it", [Edit(0, 6, "Person 2", "steward")])
    assert first == "Person 2 asked Bob Smith about it"
    later = [Edit(15, 24, "[name]", "gliner")]
    final, more = apply(first, later)
    moved = shift(chips, later)
    assert final == "Person 2 asked [name] about it"
    assert [final[c["start"]:c["end"]] for c in moved + more] == ["Person 2", "[name]"]
    # a chip after an edit moves by the edit's change in length
    _, tail = apply("a Bob b Person 1", [Edit(8, 16, "Person 1", "steward")])
    assert shift(tail, [Edit(2, 5, "[name]", "gliner")])[0]["start"] == 11


def test_shift_refuses_a_later_edit_that_overlaps_a_chip():
    _, chips = apply("Robert asked", [Edit(0, 6, "Person 2", "steward")])
    with pytest.raises(ValueError):
        shift(chips, [Edit(5, 10, "[name]", "gliner")])


def test_overlaps():
    assert overlaps(2, 5, [(4, 9)]) and not overlaps(2, 4, [(4, 9)])


def test_outside_cuts_a_span_around_protected_ones():
    """A detector span that runs into an alias is cut to the parts outside it, never dropped whole."""
    assert outside(0, 17, [(0, 8)]) == [(8, 17)]
    assert outside(0, 20, [(5, 9), (12, 14)]) == [(0, 5), (9, 12), (14, 20)]
    assert outside(5, 9, [(0, 20)]) == []
    assert outside(3, 6, []) == [(3, 6)]
