import hashlib
import json
from datetime import date

import numpy as np
import pytest

from steward.engine import datafiles as d


def test_awi_series_matches_ssa():
    awi = d.awi()
    assert awi[1951] == 2799.16
    assert awi[1977] == 9779.44          # the base year of the 1979 bend points
    assert awi[1986] == 17321.82         # used in SSA's 2026 worked example
    assert awi[2024] == 69846.57 and max(awi) == d.LATEST_AWI_YEAR
    assert len(awi) == 74


def test_bend_points_match_ssa():
    bp = d.bend_points()
    assert bp[1979] == (180, 1085)
    assert bp[2021] == (996, 6002)
    assert bp[2025] == (1226, 7391)
    assert bp[2026] == (1286, 7749) and max(bp) == d.LATEST_BEND_YEAR
    # 2026 bend points are the 1979 ones scaled by AWI(2024)/AWI(1977), rounded to the dollar
    awi = d.awi()
    assert round(180 * awi[2024] / awi[1977]) == 1286 and round(1085 * awi[2024] / awi[1977]) == 7749


def test_taxable_maximum_matches_ssa():
    tm = d.taxable_max()
    assert tm[1937] == 3000 and tm[1951] == 3600 and tm[1979] == 22900
    assert tm[2025] == 176100 and tm[2026] == 184500 and max(tm) == d.LATEST_TAXABLE_MAX_YEAR
    assert all(tm[y] <= tm[y + 1] for y in range(1937, 2026))


def test_life_table_is_the_2023_period_table():
    lt = d.life_table()
    assert set(lt) == {"male", "female"} and lt["male"].shape == lt["female"].shape == (120,)
    assert lt["male"][0] == pytest.approx(0.006015) and lt["female"][0] == pytest.approx(0.005125)
    assert lt["male"][60] == pytest.approx(0.011337) and lt["female"][60] == pytest.approx(0.006923)
    assert lt["male"][95] == pytest.approx(0.262268) and lt["female"][95] == pytest.approx(0.216846)
    assert lt["male"][119] == lt["female"][119] == pytest.approx(0.926604)
    assert np.all(lt["male"][30:] > 0) and np.all(np.diff(lt["male"][30:]) > 0)


def test_market_series_and_checksum():
    d.verify_market_checksum()
    text = (d.DATA_DIR / "market_1928_2025.csv").read_bytes()
    assert hashlib.sha256(text).hexdigest() == d.MARKET_CSV_SHA256
    m = d.market()
    assert m.years[0] == 1928 and m.years[-1] == 2025 and len(m.years) == 98
    assert m.stock[0] == pytest.approx(0.438112) and m.stock[-1] == pytest.approx(0.177237)
    assert m.tbond[list(m.years).index(1982)] == pytest.approx(0.328145)
    assert m.tbill[list(m.years).index(1981)] == pytest.approx(0.140362)
    assert m.cpi[list(m.years).index(1980)] == pytest.approx(0.125163)
    assert m.cpi[list(m.years).index(2022)] == pytest.approx(0.064544)
    assert all(a.shape == (98,) for a in (m.stock, m.tbill, m.tbond, m.cpi))


def test_market_file_is_the_latest_by_name(tmp_path, monkeypatch):
    for year in (2025, 2027, 2026):
        (tmp_path / f"market_1928_{year}.csv").write_text("year,stock,tbill,tbond,cpi\n")
    (tmp_path / "market_1928_2030.csv.bak").write_text("")
    monkeypatch.setattr(d, "DATA_DIR", tmp_path)
    path, year = d.market_file()
    assert (path.name, year) == ("market_1928_2027.csv", 2027)
    with pytest.raises(d.DataError, match="market_1928_2027.csv has sha256"):
        d.verify_market_checksum()


def test_market_file_missing_is_loud(tmp_path, monkeypatch):
    monkeypatch.setattr(d, "DATA_DIR", tmp_path)
    with pytest.raises(d.DataError):
        d.market_file()


def test_market_checksum_mismatch_is_loud(tmp_path, monkeypatch):
    bad = tmp_path / "market_1928_2025.csv"
    bad.write_text("year,stock,tbill,tbond,cpi\n1928,0,0,0,0\n")
    monkeypatch.setattr(d, "DATA_DIR", tmp_path)
    with pytest.raises(d.DataError):
        d.verify_market_checksum()


def test_college_levels_split_tuition_from_living_costs_and_keep_today_s_totals():
    lv = d.college_levels()
    assert list(lv) == ["two_year", "in_state_public", "out_of_state_public", "private"]
    assert {k: v.years for k, v in lv.items()} == {"two_year": 2, "in_state_public": 4, "out_of_state_public": 4, "private": 4}
    # The four-year budgets are the totals every plan was solved with before Profile (profile spec, The data file).
    assert {k: v.tuition_fees_cents + v.living_cents for k, v in lv.items() if v.years == 4} == {
        "in_state_public": 3_099_000, "out_of_state_public": 5_092_000, "private": 6_547_000}
    assert all(v.tuition_fees_cents > 0 and v.living_cents > 0 for v in lv.values())
    assert d.college_costs_growth() == 0.01


def test_every_college_figure_has_its_source_and_the_file_a_checked_date():
    raw = json.loads((d.DATA_DIR / "college_2025.json").read_text())
    assert raw["url"].startswith("https://research.collegeboard.org/")
    assert date(2026, 10, 1) <= date.fromisoformat(raw["checked"]) <= date(2026, 12, 31)
    for key, v in raw["levels"].items():
        assert v["sector"].strip(), key
        assert set(v["sources"]) == {"tuition_fees_cents", "living_cents"}, key
        assert all(s.strip() for s in v["sources"].values()), key


def test_the_college_table_is_what_the_web_reads():
    t = d.college_table()
    assert t["growth"] == 0.01
    assert t["levels"]["two_year"] == {"years": 2, "tuition_fees_cents": d.college_levels()["two_year"].tuition_fees_cents,
                                       "living_cents": d.college_levels()["two_year"].living_cents}


def test_ss_constants_pin_2026_trustees_report():
    s = d.ss_constants()
    assert s["trust_fund_cut_year"] == 2034 and s["trust_fund_payable"] == 0.83
    assert s["oasi_only"] == {"depletion_year": 2032, "payable": 0.78}
    assert s["report"] == "2026 Trustees Report"
    assert s["early_rate_first_36_months"] == pytest.approx(5 / 9 / 100)
    assert s["early_rate_after_36_months"] == pytest.approx(5 / 12 / 100)
    assert s["delayed_credit_per_year"] == 0.08
    assert s["spousal_early_rate_first_36_months"] == pytest.approx(25 / 36 / 100)
    assert s["pia_rates"] == [0.9, 0.32, 0.15]
