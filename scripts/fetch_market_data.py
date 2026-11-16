"""Regenerate src/steward/engine/data/market_1928_2025.csv from Damodaran's spreadsheet.

Usage:
    uv run --with xlrd python scripts/fetch_market_data.py [--xls path/to/histretSP.xls]

Without --xls the spreadsheet is downloaded from
https://www.stern.nyu.edu/~adamodar/pc/datasets/histretSP.xls into a temporary directory.
The script prints the sha256 of the CSV it wrote; paste it into datafiles.MARKET_CSV_SHA256
and update data/SOURCES.md (download date, spreadsheet sha256, last year) when the series grows.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import csv
import sys
import tempfile
import urllib.request
from pathlib import Path

import xlrd

URL = "https://www.stern.nyu.edu/~adamodar/pc/datasets/histretSP.xls"
OUT = Path(__file__).resolve().parents[1] / "src" / "steward" / "engine" / "data"


def build_csv(xls_path: Path) -> tuple[str, int]:
    wb = xlrd.open_workbook(str(xls_path))
    returns = wb.sheet_by_name("Returns by year")
    inflation = wb.sheet_by_name("Inflation Rate")
    cpi = {}
    for r in range(inflation.nrows):
        y = inflation.cell_value(r, 0)
        if isinstance(y, float) and y >= 1914:
            cpi[int(y)] = float(inflation.cell_value(r, 2))
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["year", "stock", "tbill", "tbond", "cpi"])
    last = 0
    for r in range(returns.nrows):
        y = returns.cell_value(r, 0)
        if not isinstance(y, float) or y < 1928:
            continue
        y = int(y)
        # columns: 1 = S&P 500 incl. dividends, 3 = 3-month T.Bill, 4 = US T.Bond (10-year)
        w.writerow([y, f"{returns.cell_value(r, 1):.6f}", f"{returns.cell_value(r, 3):.6f}",
                    f"{returns.cell_value(r, 4):.6f}", f"{cpi[y]:.6f}"])
        last = y
    return out.getvalue(), last


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xls", type=Path)
    args = ap.parse_args()
    if args.xls:
        xls = args.xls
    else:
        tmp = Path(tempfile.mkdtemp())
        xls = tmp / "histretSP.xls"
        urllib.request.urlretrieve(URL, xls)
        print(f"downloaded {URL} -> {xls} sha256 {hashlib.sha256(xls.read_bytes()).hexdigest()}")
    text, last = build_csv(xls)
    target = OUT / f"market_1928_{last}.csv"
    target.write_text(text)
    print(f"wrote {target} ({text.count(chr(10)) - 1} rows) sha256 {hashlib.sha256(text.encode()).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
