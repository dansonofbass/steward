"""What a new layout sends (PDF statements spec P13), from the lines the sandbox wrote. The lines themselves, P14's
mask and the scan test live in steward_pdf.lines (remote-reading P56), where the child runs them on either machine;
they're re-exported here for the NAS's readers."""
from __future__ import annotations

from steward.services.statements import dates, money
from steward_boundary.statements_wire import DATE_FORMATS, MAX_CELL, MAX_CELLS, MAX_LINES, MAX_PAGES
from steward_pdf.lines import (CELL_CHARS, CELLS_PER_LINE, LINES_PER_PAGE, SCAN_CHARS, is_scan,  # noqa: F401
                               line_text, mask, mask_cells, norm, page_lines)

FACTS = 60                    # page 1's lines above its first row, kept first (P13; the labels the facts need)
ROWS_PER_PAGE = 20            # dated lines kept from each page sent, so the headings near them always fit


def dated_amount(line: dict) -> bool:
    if not money.amounts(line_text(line)):
        return False
    return any(dates.parse(c["text"], f) is not None for c in line["cells"] for f in DATE_FORMATS)


def for_model(pages: list[dict]) -> list[dict]:
    """P13: page 1 plus the first 3 pages with at least 3 lines that hold a date and an amount; at most 150 lines, 16
    cells a line, 120 characters a cell. Kept first: page 1's lines above its first row (the facts' labels), then up
    to 20 rows a page, then the lines near rows (header, section titles, totals), then the rest."""
    if not pages:
        return []
    marks = {id(p): [dated_amount(ln) for ln in p["lines"]] for p in pages}
    chosen = [pages[0]] + [p for p in pages[1:] if sum(marks[id(p)]) >= 3][:MAX_PAGES - 1]
    ranked: list[tuple[int, int, int]] = []
    for pi, p in enumerate(chosen):
        m = marks[id(p)]
        first = next((i for i, x in enumerate(m) if x), len(m))
        near = {j for i, x in enumerate(m) if x for j in range(max(0, i - 3), min(len(m), i + 3))}
        rows = 0
        for i in range(len(m)):
            if pi == 0 and i < first and i < FACTS:
                rank = 0
            elif m[i] and rows < ROWS_PER_PAGE:
                rank, rows = 1, rows + 1
            elif not m[i] and i in near:
                rank = 2
            else:
                rank = 3
            ranked.append((rank, pi, i))
    keep = {(pi, i) for _, pi, i in sorted(ranked)[:MAX_LINES]}
    out = []
    for pi, p in enumerate(chosen):
        lines = [{"y": ln["y"], "cells": [{**c, "text": c["text"][:MAX_CELL]} for c in ln["cells"][:MAX_CELLS]]}
                 for i, ln in enumerate(p["lines"]) if (pi, i) in keep]
        if lines:
            out.append({"n": p["n"], "width": p["width"], "height": p["height"], "lines": lines})
    return out
