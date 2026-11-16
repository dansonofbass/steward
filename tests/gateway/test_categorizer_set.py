"""The labelled set (spec 6.1, ruling 13): 600 fictional rows, the committed file is the generator's output, every
category the model may give is there, a tenth are vague, and the milestone 1 rules match none of them."""
import json
from collections import Counter

from steward.services.categorize import BUILTIN
from steward.services.transactions import tidy
from steward_gateway.categorize import ALLOWED
from tests.gateway.categorizer_set.make_set import HERE, build


def committed():
    return [json.loads(line) for line in (HERE / "set.jsonl").read_text().splitlines()]


def test_the_committed_file_is_the_generators_output():
    assert committed() == build()


def test_600_rows_with_every_allowed_category_and_60_vague():
    rows = committed()
    counts = Counter(r["category"] for r in rows)
    assert len(rows) == 600 and len({r["id"] for r in rows}) == 600
    assert set(counts) == set(ALLOWED) and counts["uncategorized"] == 60
    assert min(n for c, n in counts.items() if c != "uncategorized") >= 20   # 540 rows over 26 categories


def test_no_row_matches_a_milestone_1_rule():
    hits = [r["description"] for r in committed() if any(rx.search(tidy(r["description"])) for rx, _, _ in BUILTIN)]
    assert hits == []


def test_money_in_rows_are_positive_and_spending_negative():
    for r in committed():
        if r["category"] in ("income", "business_income", "interest"):
            assert r["amount_cents"] > 0, r
        elif r["category"] != "uncategorized":
            assert r["amount_cents"] < 0, r
