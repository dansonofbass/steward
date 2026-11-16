import json
from pathlib import Path

import pytest

from steward.engine import college, datafiles
from steward.engine.datafiles import CollegeLevel
from steward.engine.inputs import Bucket, Child, Mix

FIXTURE = json.loads((Path(__file__).parents[2] / "web" / "src" / "screens" / "profile" / "college_outlook.fixture.json").read_text())
LEVELS = {k: CollegeLevel(v["years"], v["tuition_fees_cents"], v["living_cents"]) for k, v in FIXTURE["levels"].items()}


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda c: c["name"])
def test_the_outlook_matches_the_shared_fixture(case):
    kid = Child("Kid", case["birth_year"], case["level"], Bucket(case["balance_cents"], Mix(1.0, 0.0, 0.0)),
                case["monthly_cents"], case["share_pct"], case["covers_living"])
    got = college.outlook(kid, FIXTURE["plan_year"], case["real_return"], levels=LEVELS, growth=FIXTURE["growth"])
    assert (got.years, got.total_cents, got.covered_cents) == (
        case["expect"]["years"], case["expect"]["total_cents"], case["expect"]["covered_cents"])


def test_one_case_by_hand():
    # Half of in-state tuition for a kid starting in 2033: $5,975 a year grown 1% a year from 2026, for 2033-2036.
    kid = Child("Kid", 2015, "in_state_public", Bucket(0, Mix(1.0, 0.0, 0.0)), 0, 50, False)
    got = college.outlook(kid, 2026, 0.04, levels=LEVELS, growth=0.01)
    assert got.total_cents == round(sum(597_500 * 1.01 ** k for k in (7, 8, 9, 10)))


def test_the_outlook_reads_the_data_file_by_default_and_the_real_return_is_a_plain_geometric_mean():
    kid = Child("Kid", 2015, "private", Bucket(0, Mix(1.0, 0.0, 0.0)), 0)
    assert college.outlook(kid, 2026, 0.0).years == 4
    assert datafiles.college_levels()["private"].years == 4
    cash = college.real_return(Mix(0.0, 0.0, 1.0))
    stocks = college.real_return(Mix(1.0, 0.0, 0.0))
    assert -0.01 < cash < 0.02 < 0.04 < stocks < 0.09            # bills barely beat inflation; stocks did 6-7% real
    assert college.real_return(Mix(1.0, 0.0, 0.0, fee_bp=100)) == pytest.approx(stocks - 0.01, abs=0.002)
