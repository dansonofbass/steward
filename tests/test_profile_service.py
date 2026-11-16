"""Profile's five sections (profile spec, Completion): done from data whatever was said, otherwise the last answer;
Doesn't apply for Kids and college only; Home and cars needs the mortgage's rate (P22) and never waits on cars; the
resume point and each person's Later window (P5)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from steward.db.models import BalanceSnapshot, Child, SetupStep, SimplefinLink, SsEarnings
from steward.services import home_value, profile
from steward.services.profile import KIDS_EXIST, ONLY_KIDS, SectionRefused
from tests.factories import add_fact, make_account, make_user

T = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)


def statuses(db):
    return {s.key: s.status for s in profile.section_states(db)}


def you_facts(db):
    for k, v in (("jr.dob", "1982-05-01"), ("spouse.dob", "1984-08-01"), ("state", "CA"), ("filing_status", "mfj"),
                 ("jr.salary_cents", "16000000"), ("jr.k401_pct_bp", "1000"), ("employer.match_rate_bp", "5000"),
                 ("employer.match_cap_bp", "600")):
        add_fact(db, k, v)


def kid(db, label="Ava", year=2015, account=None, removed=None):
    c = Child(label=label, birth_year=year, cost_level="private", account_id=account.id if account else None,
              monthly_contribution_cents=0, removed_at=removed)
    db.add(c)
    db.commit()
    return c


def test_an_empty_household_has_every_section_not_started_and_says_what_each_needs(db):
    make_user(db)
    states = profile.section_states(db)
    assert [(s.key, s.status) for s in states] == [(k, "todo") for k in ("you", "kids", "home", "benefits", "banks")]
    d = {s.key: s.as_dict() for s in states}
    assert [d[k]["minutes"] for k in d] == [3, 2, 3, 5, 5]
    assert d["home"]["missing"] == "whether you own a home"
    assert d["kids"]["missing"] == "a kid, or No kids"
    assert d["benefits"]["missing"] == "JR's earnings record or Steward's estimate and the health insurance premium"
    assert d["banks"]["missing"] == "a linked bank or an account"


def test_you_and_your_partner_is_done_from_the_facts(db):
    make_user(db)
    you_facts(db)
    assert statuses(db)["you"] == "done"


def test_kids_need_a_kid_and_every_529_linked_and_skip_removed_kids(db):
    make_user(db)
    p529 = make_account(db, "Fidelity 529", type="plan529")
    kid(db, "Gone", 2012, p529, removed=T)                 # a removed kid's link doesn't count
    assert statuses(db)["kids"] == "todo"
    assert profile.missing(db)["kids"] == ["a kid, or No kids", "which kid Fidelity 529 belongs to"]
    gone = db.query(Child).filter_by(label="Gone").one()
    gone.account_id = None                                  # as DELETE /children releases it
    db.commit()
    kid(db, "Ava", 2015, p529)
    assert statuses(db)["kids"] == "done"


def test_doesnt_apply_is_for_kids_only_and_goes_stale_when_a_kid_or_529_appears(db):
    u = make_user(db)
    with pytest.raises(SectionRefused) as e:
        profile.set_section(db, "home", "doesnt_apply", u.id, T)
    assert (e.value.message, e.value.status) == (ONLY_KIDS, 422)
    profile.set_section(db, "kids", "doesnt_apply", u.id, T)
    db.commit()
    assert statuses(db)["kids"] == "doesnt_apply"
    make_account(db, "529", type="plan529")
    assert statuses(db)["kids"] == "todo"
    with pytest.raises(SectionRefused) as e:
        profile.set_section(db, "kids", "doesnt_apply", u.id, T)
    assert e.value.message == KIDS_EXIST


def test_home_and_cars_needs_the_value_and_with_a_mortgage_its_rate_payment_and_payoff(db):
    make_user(db)
    add_fact(db, "home.owns", "no")
    assert statuses(db)["home"] == "done"
    add_fact(db, "home.owns", "yes", as_of=date(2026, 10, 2))
    assert profile.missing(db)["home"] == ["the home's value"]
    add_fact(db, "home.value_cents", "125000000")
    assert statuses(db)["home"] == "done"
    make_account(db, "Mortgage", type="mortgage")
    assert profile.missing(db)["home"] == ["the mortgage's interest rate", "the monthly payment", "the payoff date"]
    add_fact(db, "mortgage.payment_cents", "268000")
    add_fact(db, "mortgage.payoff_date", "2051-09-01")
    assert profile.missing(db)["home"] == ["the mortgage's interest rate"]
    home_value.main_mortgage(db).rate_bp = 312              # the account's own rate counts, as the fact does
    db.commit()
    assert statuses(db)["home"] == "done"
    make_account(db, "Subaru", type="vehicle")              # cars never block
    assert statuses(db)["home"] == "done"


def test_a_home_value_or_an_active_property_says_yes_without_an_answer(db):
    make_user(db)
    make_account(db, "Home", type="property")
    assert profile.owns_home(db, {}) is True
    assert profile.missing(db)["home"] == ["the home's value"]


def test_benefits_takes_a_record_or_the_estimate_and_the_premium(db):
    make_user(db)
    add_fact(db, "health.premium_cents", "1680000")
    assert statuses(db)["benefits"] == "todo"
    add_fact(db, "jr.ss_estimate", "yes")
    assert statuses(db)["benefits"] == "done"
    db.add(SsEarnings(person="jr", year=2020, earnings_cents=5_000_000, imported_at=T))
    db.commit()
    assert statuses(db)["benefits"] == "done"


def test_banks_is_simplefin_or_any_bank_account(db):
    make_user(db)
    make_account(db, "Subaru", type="vehicle")
    assert statuses(db)["banks"] == "todo"
    db.add(SimplefinLink(access_url="https://bridge.example/fake"))
    db.commit()
    assert statuses(db)["banks"] == "done"


def test_done_needs_the_data_skip_on_complete_data_changes_nothing_and_done_clears_the_resume_point(db):
    u = make_user(db)
    with pytest.raises(SectionRefused) as e:
        profile.set_section(db, "home", "done", u.id, T)
    assert (e.value.message, e.value.status) == ("Still needed: whether you own a home.", 409)
    profile.set_resume(db, "you", "taxes", u.id, T)
    db.commit()
    s = next(x for x in profile.section_states(db) if x.key == "you")
    assert (s.status, s.resume_step) == ("todo", "taxes")
    you_facts(db)
    profile.set_section(db, "you", "done", u.id, T)
    db.commit()
    row = db.get(SetupStep, "you")
    assert (row.status, row.resume_step, row.user_id) == ("done", None, u.id)
    profile.set_section(db, "you", "skipped", 99, T)        # complete data: the person who finished it stays on record
    db.commit()
    assert db.get(SetupStep, "you").user_id == u.id


def test_a_resume_point_must_be_one_of_the_sections_steps(db):
    u = make_user(db)
    with pytest.raises(SectionRefused) as e:
        profile.set_resume(db, "home", "garage", u.id, T)
    assert e.value.status == 422
    profile.set_resume(db, "home", None, u.id, T)          # nothing to clear: no row is made
    assert db.get(SetupStep, "home") is None


def test_later_hides_the_line_for_a_week_and_then_it_is_back(db):
    u = make_user(db)
    profile.mark(db, u.id, T, later=True)
    db.commit()
    assert profile.marks_out(db, u.id, T)["later_until"] == (T + timedelta(days=7)).isoformat()
    assert profile.marks_out(db, u.id, T + timedelta(days=8))["later_until"] is None
    profile.mark(db, u.id, T, later=False)
    assert profile.marks_out(db, u.id, T)["later_until"] is None


def test_jrs_shape_after_0030_keeps_kids_and_home_done(db):
    """Review Focus 1: three kids with three 529s, one home with one mortgage and its rate as a fact, no home.owns."""
    make_user(db)
    home = make_account(db, "Home", type="property")
    mortgage = make_account(db, "Mortgage", type="mortgage")
    home.loan_id = mortgage.id                                  # what 0030 links
    db.add(BalanceSnapshot(account_id=home.id, as_of=date(2026, 10, 1), balance_cents=125_000_000))
    db.commit()
    for k, v in (("home.account_id", str(home.id)), ("home.value_cents", "125000000"), ("mortgage.rate_bp", "287.5"),
                 ("mortgage.payment_cents", "268000"), ("mortgage.payoff_date", "2051-03-01")):
        add_fact(db, k, v)
    for label, year in (("Ava", 2012), ("Ben", 2015), ("Cy", 2019)):
        kid(db, label, year, make_account(db, f"529 {label}", type="plan529"))
    s = statuses(db)
    assert (s["kids"], s["home"]) == ("done", "done")
    assert home_value.main_mortgage(db).id == mortgage.id
