"""Loaders for the bundled reference tables under data/. See data/SOURCES.md."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).parent / "data"

LATEST_AWI_YEAR = 2024          # SSA: "The national average wage index for 2024 is 69,846.57"
LATEST_BEND_YEAR = 2026         # bend points for workers first eligible in 2026
LATEST_TAXABLE_MAX_YEAR = 2026  # $184,500

MARKET_CSV_SHA256 = "809d73b38c55ebe74e99dbbcabadfefebc4de07e68938a13c1a18f51d1c9f0b2"


class DataError(RuntimeError):
    """A bundled data file is missing or not what SOURCES.md says it is."""


def _rows(name: str) -> list[dict[str, str]]:
    path = DATA_DIR / name
    if not path.exists():
        raise DataError(f"missing data file {path}")
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


@cache
def awi() -> dict[int, float]:
    return {int(r["year"]): float(r["awi"]) for r in _rows("awi.csv")}


@cache
def bend_points() -> dict[int, tuple[int, int]]:
    return {int(r["year"]): (int(r["first"]), int(r["second"])) for r in _rows("bend_points.csv")}


@cache
def taxable_max() -> dict[int, int]:
    return {int(r["year"]): int(r["taxable_max"]) for r in _rows("taxable_max.csv")}


@cache
def life_table() -> dict[str, np.ndarray]:
    rows = _rows("life_table_2023.csv")
    male = np.zeros(120)
    female = np.zeros(120)
    for r in rows:
        a = int(r["age"])
        male[a] = float(r["male_q"])
        female[a] = float(r["female_q"])
    return {"male": male, "female": female}


@dataclass(frozen=True)
class MarketData:
    years: np.ndarray
    stock: np.ndarray   # S&P 500 total return, nominal fraction
    tbill: np.ndarray   # 3-month T-bill, nominal fraction
    tbond: np.ndarray   # 10-year Treasury total return, nominal fraction
    cpi: np.ndarray     # CPI-U, December-to-December change as a fraction


_MARKET_NAME = re.compile(r"market_1928_(\d{4})\.csv")


def market_file() -> tuple[Path, int]:
    """The latest market_1928_<year>.csv and its end year, read from the name (scripts/fetch_market_data.py writes it)."""
    found = [(int(m.group(1)), p) for p in DATA_DIR.glob("market_1928_*.csv") if (m := _MARKET_NAME.fullmatch(p.name))]
    if not found:
        raise DataError(f"missing data file {DATA_DIR / 'market_1928_<year>.csv'}")
    year, path = max(found)
    return path, year


def verify_market_checksum() -> None:
    path, _ = market_file()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != MARKET_CSV_SHA256:
        raise DataError(
            f"{path.name} has sha256 {digest}, expected {MARKET_CSV_SHA256}; "
            "regenerate it with scripts/fetch_market_data.py and update SOURCES.md"
        )


@cache
def market() -> MarketData:
    verify_market_checksum()
    rows = _rows(market_file()[0].name)
    col = lambda k: np.array([float(r[k]) for r in rows])  # noqa: E731
    return MarketData(years=np.array([int(r["year"]) for r in rows]), stock=col("stock"),
                      tbill=col("tbill"), tbond=col("tbond"), cpi=col("cpi"))


@dataclass(frozen=True)
class CollegeLevel:
    """One school type's yearly budget (profile spec, The data file): tuition and fees, and living costs (housing and
    food, books and supplies, transportation and other expenses), in cents, for `years` years from 18."""
    years: int
    tuition_fees_cents: int
    living_cents: int


@cache
def _college() -> dict:
    return json.loads((DATA_DIR / "college_2025.json").read_text())


@cache
def college_levels() -> dict[str, CollegeLevel]:
    return {k: CollegeLevel(int(v["years"]), int(v["tuition_fees_cents"]), int(v["living_cents"]))
            for k, v in _college()["levels"].items()}


@cache
def college_costs_growth() -> float:
    return float(_college()["real_growth_per_year"])


def college_table() -> dict:
    """The table as the web reads it (GET /api/children, the Plan's inputs.college)."""
    return {"growth": college_costs_growth(),
            "levels": {k: {"years": v.years, "tuition_fees_cents": v.tuition_fees_cents, "living_cents": v.living_cents}
                       for k, v in college_levels().items()}}


@cache
def ss_constants() -> dict:
    return json.loads((DATA_DIR / "ss_constants.json").read_text())
