"""Lines of positioned cells from a page's words (PDF statements spec P10, P12, P14). page_lines runs in the sandbox
child, on whichever machine opens the PDF (remote-reading P56), so every cell is P14-masked before it leaves the
child; validation, reading and the fingerprint on the NAS all compare labels against the same masked text the model
saw.

P14 masking is best-effort: it trims the account numbers printed in the usual ways (digit groups split by one space,
NBSP, thin space, hyphen, en dash, dot, slash, middle dot or comma; non-ASCII digits; a run across cells), not every
possible format (digits interleaved with letters are out of scope). The real boundary is that pages never leave
the gateway's local model (spec decision 4)."""
from __future__ import annotations

import re
import statistics

# P14. A run is digit groups of any length joined by single separators (any whitespace, NBSP included, a hyphen or
# dash, a dot, a slash or a comma). A run with 9+ ASCII digits becomes "••" + its last 4; a run holding any non-ASCII
# digit (full-width, Arabic-Indic...) becomes "••" wholesale. Money and dates are kept first and break runs: a
# comma-grouped amount, a plain amount up to 9,999,999.99, a numeric date in an allowed format (checked: month 1-12,
# day 1-31), or two dates joined by one hyphen (a period). A kept span can't start right after a digit and a non-space
# separator, nor end right before one, so "2024-03-14-5678" and "03/14/2024/1234" aren't dates.
_SENT = "\x1f"                # joins a line's cells for mask_cells; whitespace, so a separator; never in a cleaned cell
_SEP = r"[\s\-./,·‐-―−]"            # \s holds NBSP and thin space; U+2013 is the en dash
_RUN = re.compile(rf"\d+(?:{_SEP}\d+)*")
_NUMDATE = r"[0-9]{1,4}(?:[-/.][0-9]{1,4}){1,2}"
_KEEP = re.compile(rf"(?<![0-9])(?<![0-9][-./,])(?:[0-9]{{1,3}}(?:,[0-9]{{3}})+(?:\.[0-9]{{2}})?|[0-9]{{1,7}}\.[0-9]{{2}}"
                   rf"|{_NUMDATE}(?:-{_NUMDATE})?)(?![0-9])(?![-./,][0-9])")
_D3 = re.compile(r"([0-9]{1,2})([-/.])([0-9]{1,2})\2(?:[0-9]{2}|[0-9]{4})")
_YMD = re.compile(r"[0-9]{4}([-/])([0-9]{1,2})\1([0-9]{1,2})")
_MD = re.compile(r"([0-9]{1,2})[-/]([0-9]{1,2})")
_PLAIN_MONEY = re.compile(r"[0-9]{1,7}\.[0-9]{2}")
_FOREIGN = re.compile(r"(?![0-9])\d")
LINES_PER_PAGE = 400
CELLS_PER_LINE = 32
CELL_CHARS = 200
SCAN_CHARS = 20               # P10


def _is_date(s: str) -> bool:
    if m := _D3.fullmatch(s):                                       # month- or day-first, with a year
        a, b = int(m[1]), int(m[3])
        return 0 < a <= 31 and 0 < b <= 31 and min(a, b) <= 12
    if m := _YMD.fullmatch(s):
        return 0 < int(m[2]) <= 12 and 0 < int(m[3]) <= 31
    if m := _MD.fullmatch(s):                                       # %m/%d, %m-%d
        return 0 < int(m[1]) <= 12 and 0 < int(m[2]) <= 31
    return False


def _kept(s: str) -> bool:
    if "," in s or _PLAIN_MONEY.fullmatch(s) or _is_date(s):
        return True
    return any(_is_date(s[:i]) and _is_date(s[i + 1:]) for i, ch in enumerate(s) if ch == "-")


def _hide(run: str) -> str:
    pieces = run.split(_SENT)                                       # one per cell the run spans
    if _FOREIGN.search(run):
        return _SENT.join(["••"] * len(pieces))
    digits = re.sub(r"[^0-9]", "", run)
    if len(digits) < 9:
        return run
    return _SENT.join(["••"] * (len(pieces) - 1) + ["••" + digits[-4:]])


def mask(text: str) -> str:
    shadow = list(text)
    for m in _KEEP.finditer(text):
        if _kept(m.group(0)):
            shadow[m.start():m.end()] = "\x00" * (m.end() - m.start())   # neither digit nor separator: breaks runs
    out, last = [], 0
    for m in _RUN.finditer("".join(shadow)):
        out += [text[last:m.start()], _hide(text[m.start():m.end()])]
        last = m.end()
    return "".join([*out, text[last:]])


def mask_cells(texts: list[str]) -> list[str]:
    """P14 across a line's cells: a run that continues from one cell into the next is masked as one, each cell's part
    becoming "••" and the last part "••" + the run's last 4."""
    return mask(_SENT.join(t.replace(_SENT, " ") for t in texts)).split(_SENT)


def norm(text: str) -> str:
    """'Opening/Closing Date:' -> 'opening closing date' (as positions._norm)."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def line_text(line: dict) -> str:
    return " ".join(c["text"] for c in line["cells"])


def _clean(text: str) -> str:
    return " ".join("".join(ch for ch in str(text) if ch.isprintable()).split())


def page_lines(words: list[dict]) -> list[dict]:
    """P12: words on the same baseline (± 2 pt) make a line; neighbours closer than 1.5 × the median character width
    make a cell. Capped at 400 lines, 32 cells and 200 characters (Engineering choice 17); masked."""
    words = [w for w in words if _clean(w.get("text", ""))]
    if not words:
        return []
    cw = statistics.median((w["x1"] - w["x0"]) / max(1, len(w["text"])) for w in words)
    words.sort(key=lambda w: (round(w["bottom"]), w["x0"]))
    groups: list[list[dict]] = []
    for w in words:
        for g in reversed(groups[-3:]):
            if abs(g[0]["bottom"] - w["bottom"]) <= 2:
                g.append(w)
                break
        else:
            groups.append([w])
    out = []
    for g in sorted(groups, key=lambda g: g[0]["bottom"])[:LINES_PER_PAGE]:
        g.sort(key=lambda w: w["x0"])
        cells: list[dict] = []
        for w in g:
            if cells and w["x0"] - cells[-1]["x1"] < 1.5 * cw:
                cells[-1]["text"] += " " + _clean(w["text"])
                cells[-1]["x1"] = w["x1"]
            else:
                cells.append({"x0": w["x0"], "x1": w["x1"], "text": _clean(w["text"])})
        texts = mask_cells([c["text"] for c in cells])                 # the whole line, before the cell cap
        out.append({"y": round(float(g[0]["top"]), 1),
                    "cells": [{"x0": round(float(c["x0"]), 1), "x1": round(float(c["x1"]), 1),
                               "text": t[:CELL_CHARS]} for c, t in zip(cells[:CELLS_PER_LINE], texts)]})
    return out


def is_scan(lines: list[dict], width: float, height: float, image_area: float) -> bool:
    """P10: fewer than 20 characters of text and an image covering at least half the page."""
    chars = sum(len(c["text"]) for ln in lines for c in ln["cells"])
    return chars < SCAN_CHARS and image_area >= 0.5 * width * height
