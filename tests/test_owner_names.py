import pytest

from steward.books.owners import (
    CHOOSE_NAMES, HOUSEHOLD_OWNER_NAMES, NAMES_DIFFER, OwnerName, default_owner, from_json, owner_key,
    owner_options, parse_owner_names, to_json,
)
from steward.books.people import Person, household_people


def test_household_keeps_the_four_keys():
    assert [o.key for o in HOUSEHOLD_OWNER_NAMES] == ["jr", "spouse", "joint", "business"]


def test_keys_come_from_labels():
    assert owner_key("Robert (husband)") == "robert-husband"
    assert owner_key("Mom (Robin's)") == "mom-robins"
    assert owner_key("  José  ") == "jose"
    names = parse_owner_names(["Margaret", " Robert (husband) ", "Joint"])
    assert names == (OwnerName("margaret", "Margaret"), OwnerName("robert-husband", "Robert (husband)"),
                     OwnerName("joint", "Joint"))
    assert from_json(to_json(names)) == names


@pytest.mark.parametrize("bad", [[], [""], ["   "], ["x" * 41], "Margaret", [1], ["a"] * 9])
def test_bad_lists_are_refused_in_plain_words(bad):
    with pytest.raises(ValueError, match=CHOOSE_NAMES):
        parse_owner_names(bad)


def test_names_that_make_the_same_key_are_refused():
    with pytest.raises(ValueError, match=NAMES_DIFFER):
        parse_owner_names(["Joint", "joint!"])


def test_household_labels_follow_the_people_and_parent_labels_are_kept():
    people = (Person(4, "sam", "Sam"), Person(2, "jr", "JR Hale"))
    assert household_people(people) == (people[1], people[0])
    shown = owner_options("household", HOUSEHOLD_OWNER_NAMES, people)
    assert [(o.key, o.label) for o in shown] == [("jr", "JR Hale"), ("spouse", "Sam"), ("joint", "Joint"),
                                                 ("business", "Business")]
    assert [o.label for o in owner_options("household", HOUSEHOLD_OWNER_NAMES, ())] == ["Person 1", "Joint", "Business"]
    parent = parse_owner_names(["Margaret", "Joint"])
    assert owner_options("parent", parent, people) == parent


def test_default_owner_is_joint_when_there_is_one():
    assert default_owner(HOUSEHOLD_OWNER_NAMES) == "joint"
    assert default_owner(parse_owner_names(["Margaret"])) == "margaret"
