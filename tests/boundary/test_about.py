"""The about line (Ask about this, P4, P13): one sentence per wire object, dates in words and a word between any two
numbers, so every kind at its extreme values passes the question path's text rule with the about alias issued."""
import pytest

from steward_boundary import vocab as V
from steward_boundary.about import about_text
from steward_boundary.protocol import ABOUT, check_frame
from steward_boundary.text import is_question_safe

CTX = "Today is Friday, October 30, 2026. This is a household book. The person asking is Person 1. "


def test_each_kind_reads_as_the_spec_says():
    assert about_text({"kind": "account", "account": "Account 3"}) == "It's about Account 3."
    assert about_text({"kind": "category", "category": "dining", "month": "2026-10"}) == \
        "It's about Eating out (category dining) in October 2026."
    assert about_text({"kind": "plan"}) == "It's about the retirement plan."
    assert about_text({"kind": "transaction", "date": "2026-10-16", "amount_cents": -8072,
                       "category": "uncategorized", "account": "Account 3"}) == \
        ("It's about one transaction: $80.72 out on October 16, 2026, category Not sorted yet (uncategorized), "
         "in Account 3.")
    assert about_text({"kind": "transaction", "date": "2026-10-01", "amount_cents": 120_000, "category": "income",
                       "account": "Account 1"}) == \
        "It's about one transaction: $1,200.00 in on October 1, 2026, category Income (income), in Account 1."
    assert about_text({"kind": "flag", "check": "large", "date": "2026-10-14"}) == \
        "It's about a flag from the large check on October 14, 2026."
    assert about_text({"kind": "care", "scenario": 2, "level": "in_home_help"}) == \
        "It's about care scenario 2 (in_home_help)."
    assert about_text({"kind": "care"}) == "It's about the care projection."


def test_every_category_has_its_words():
    assert set(V.CATEGORY_WORDS) == set(V.CATEGORIES)


def _extremes() -> list[dict]:
    out: list[dict] = []
    for alias in ("Account 1", "Account 9999"):
        out.append({"kind": "account", "account": alias})
        for cents in (0, 1, -1, 999_999_999, -999_999_999):
            for day in ("2026-01-01", "2026-12-31", "2099-12-31"):
                for category in ("dining", "uncategorized"):
                    out.append({"kind": "transaction", "date": day, "amount_cents": cents, "category": category,
                                "account": alias})
    for month in ("2026-01", "2026-12", "2099-12"):
        out += [{"kind": "category", "category": c, "month": month} for c in V.CATEGORIES]
    for day in ("2026-01-01", "2099-12-31"):
        out += [{"kind": "flag", "check": c, "date": day} for c in V.FLAG_CHECKS]
    for n in (1, 5, 9999):
        out += [{"kind": "care", "scenario": n, "level": level} for level in V.CARE_LEVELS]
    return out + [{"kind": "plan"}, {"kind": "care"}]


@pytest.mark.parametrize("about", _extremes())
def test_every_kind_at_extreme_values_passes_the_text_rule(about):
    assert check_frame(ABOUT, about) == []
    issued = frozenset({"Person 1"} | ({about["account"]} if "account" in about else set()))
    assert is_question_safe(about_text(about), issued=issued)
    assert is_question_safe(CTX + about_text(about), issued=issued)


def test_an_iso_date_would_trip_the_rule():
    """Why the line writes dates in words (P13): three numbers joined only by punctuation are one number."""
    assert not is_question_safe("It's about one transaction: $80.72 out on 2026-10-16, in Account 3.",
                                issued=frozenset({"Account 3"}))
