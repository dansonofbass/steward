from dataclasses import replace

from steward.engine.inputs import Levers
from steward.engine.levers import LEVER_BY_KEY, LEVERS, ObservedTry, clamp, default_try, impact_text, try_value, with_try
from steward.engine.synthetic import synthetic_household


def test_clamp_brings_values_onto_the_scale():
    hh = synthetic_household().household     # JR 44, spouse 42, plan year 2026
    wild = Levers(save_more_monthly_cents=999_999, spending_pct=300, consulting_cents=20_000_000, consulting_until_age=75,
                  gift_cents=-5, gift_until_year=1999, spouse_earnings_cents=12_345_678, spouse_start_year=2000, spouse_stop_age=99,
                  jr_claim_age=75, spouse_claim_age=50, college_levels=("private",), full_ss_benefits=True)
    c = clamp(wild, hh)
    assert c.save_more_monthly_cents == 300_000 and c.spending_pct == 130
    assert c.consulting_cents == 15_000_000 and c.consulting_until_age == 70
    assert c.gift_cents == 0 and c.gift_until_year == 2026
    assert c.spouse_earnings_cents == 12_000_000 and c.spouse_start_year == 2026 and c.spouse_stop_age == 70
    assert c.jr_claim_age == 70 and c.spouse_claim_age == 62
    assert c.college_levels == ("in_state_public",) * 3   # wrong length -> each child's own level, spelled out
    assert c.full_ss_benefits is True


def test_clamp_snaps_to_steps_and_leaves_good_values_alone():
    hh = synthetic_household().household
    assert clamp(Levers(save_more_monthly_cents=52_600, spending_pct=93, consulting_cents=650_000), hh) == \
        Levers(save_more_monthly_cents=55_000, spending_pct=95, consulting_cents=700_000, college_levels=("in_state_public",) * 3)
    good = Levers(save_more_monthly_cents=50_000, spending_pct=90, jr_claim_age=70, college_levels=("private", "in_state_public", "out_of_state_public"))
    assert clamp(good, hh) == good
    assert clamp(Levers(consulting_until_age=30), hh).consulting_until_age == 44
    assert clamp(Levers(spouse_stop_age=30), hh).spouse_stop_age == 42



def test_lever_specs_follow_the_spec_table_order():
    assert [l.key for l in LEVERS] == ["save_more", "spending", "consulting", "gift", "spouse_earnings", "jr_claim", "spouse_claim", "college", "full_ss"]
    assert LEVERS[0].label == "Save more each month" and LEVERS[-1].label == "Full Social Security benefits"
    assert LEVERS[2].fields == ("consulting_cents", "consulting_until_age")


def test_with_try_moves_one_lever_at_a_time():
    hh = synthetic_household().household
    assumed = Levers()
    trial = Levers(save_more_monthly_cents=50_000, spending_pct=90, consulting_cents=600_000, consulting_until_age=60,
                   jr_claim_age=70, college_levels=("in_state_public", "in_state_public", "in_state_public"), full_ss_benefits=True)
    assert with_try(assumed, trial, "save_more") == Levers(save_more_monthly_cents=50_000)
    assert with_try(assumed, trial, "consulting") == Levers(consulting_cents=600_000, consulting_until_age=60)
    assert with_try(assumed, trial, "spouse_claim") == assumed
    child1 = with_try(Levers(college_levels=("private", "private", "private")), trial, "college", children=hh.children, child_index=1)
    assert child1.college_levels == ("private", "in_state_public", "private")
    own = with_try(assumed, trial, "college", children=hh.children, child_index=0)      # assumed None -> each child's own level first
    assert own.college_levels == ("in_state_public", "in_state_public", "in_state_public")


def test_default_try_values_follow_the_spec():
    hh = synthetic_household().household
    assumed = Levers(save_more_monthly_cents=20_000)
    levers, notes = default_try(hh, assumed, ObservedTry(consulting_12mo_cents=612_345, gift_12mo_cents=1_000_000, spouse_earnings_cents=6_000_000))
    assert levers.save_more_monthly_cents == 70_000 and levers.spending_pct == 90
    assert levers.consulting_cents == 600_000 and levers.consulting_until_age == 60
    assert levers.gift_cents == 1_000_000 and levers.gift_until_year == 2036
    assert levers.spouse_earnings_cents == 6_000_000 and levers.spouse_start_year == 2027 and levers.spouse_stop_age == 65
    assert levers.jr_claim_age == 70 and levers.spouse_claim_age == 70 and levers.full_ss_benefits is True
    assert levers.college_levels == ("in_state_public", "in_state_public", "in_state_public")   # already the lowest level
    assert notes == ()
    hh2 = synthetic_household(children=(replace(hh.children[0], cost_level="private"), replace(hh.children[1], cost_level="out_of_state_public"))).household
    levers, notes = default_try(hh2, Levers(), ObservedTry())
    assert levers.college_levels == ("out_of_state_public", "in_state_public")
    assert levers.consulting_cents == 100_000 and levers.gift_cents == 50_000 and levers.spouse_earnings_cents == 100_000
    assert notes == ("consulting: No history yet", "gift: No history yet", "spouse_earnings: No history yet")


def test_impact_text_in_plain_words():
    assert impact_text(0, 64, 64) == "No change" and impact_text(None, 64, 64) == "No change"
    assert impact_text(-1, 64, 64) == "about 1 month earlier" and impact_text(-4, 64, 64) == "about 4 months earlier"
    assert impact_text(7, 64, 65) == "about 7 months later"
    assert impact_text(-24, 64, 62) == "about 2 years earlier" and impact_text(13, 64, 65) == "about 1 year later"
    assert impact_text(18, 64, 66) == "about 2 years later" and impact_text(30, 64, 67) == "about 3 years later"
    assert impact_text(-42, 64, 61) == "about 4 years earlier"
    assert impact_text(None, None, 64) == "Comfortable by 64"
    assert impact_text(None, 64, None) == "Not by 70"
    assert impact_text(None, None, None) == "Still not by 70"


def test_try_value_reports_each_lever_in_its_own_unit():
    hh = synthetic_household().household
    lv = Levers(save_more_monthly_cents=50_000, spending_pct=90, jr_claim_age=70, college_levels=("private", "private", "private"), full_ss_benefits=True)
    by_key = {l.key: l for l in LEVERS}
    assert try_value(by_key["save_more"], lv) == 50_000 and try_value(by_key["spending"], lv) == 90
    assert try_value(by_key["jr_claim"], lv) == 70 and try_value(by_key["full_ss"], lv) is True
    assert try_value(by_key["college"], lv, child_index=2) == "private"
    assert try_value(by_key["college"], Levers(), child_index=2, children=hh.children) == "in_state_public"


def test_clamp_leaves_unset_years_at_zero():
    hh = synthetic_household().household
    c = clamp(Levers(gift_until_year=0, spouse_start_year=0), hh)
    assert c.gift_until_year == 0 and c.spouse_start_year == 0      # M2-A pre-flight ruling 3, pinned directly


def test_the_try_ladder_keeps_today_s_steps_and_never_proposes_two_year_on_its_own():
    hh = synthetic_household().household
    kids = tuple(replace(c, cost_level=l) for c, l in zip(hh.children, ("private", "out_of_state_public", "two_year")))
    hh = replace(hh, children=kids)
    tr, _ = default_try(hh, clamp(Levers(), hh), ObservedTry())
    assert tr.college_levels == ("out_of_state_public", "in_state_public", "two_year")
    in_state = replace(hh, children=tuple(replace(c, cost_level="in_state_public") for c in kids))
    assert default_try(in_state, clamp(Levers(), in_state), ObservedTry())[0].college_levels == ("in_state_public",) * 3
    assert LEVER_BY_KEY["college"].label == "College type"
