"""Remembered statement layouts' fingerprint (spec P24). Anchors are the table's header cells and the section titles,
normalized as positions._norm does, every digit removed, each at most 60 characters; a two-line header cell is one
anchor, its words joined. The key is "p:" + sha256 of the sorted anchors joined by "\\x1f". A new file matches when
every anchor's words are in its text and its header cells sit within 3% of the page width of where they were; the
layout with the most anchors wins, then the most recently used. A fingerprint holds wording, never data."""
from __future__ import annotations

import hashlib
import json
import re

from steward.services.statements.extract import line_text, norm
from steward.services.statements.rules import header_cells

MIN_ANCHORS = 3
TOLERANCE = 0.03
ANCHOR_CHARS = 60
UNDER = 12.0                  # a header's second line sits within this many points under its first


def _anchor(text: str) -> str:
    return " ".join(re.sub(r"\d", " ", norm(text)).split())[:ANCHOR_CHARS]


def _below(lines: list[dict], i: int, cell: dict, titles: list[str]) -> str:
    """The header cell's second line: only a true continuation, never a data row or a section title that sits close
    under the header on a tightly leaded page (a fingerprint holds wording, never data)."""
    if i + 1 >= len(lines) or lines[i + 1]["y"] - lines[i]["y"] > UNDER:
        return ""
    nxt = line_text(lines[i + 1])
    if re.search(r"\d", nxt) or any(norm(nxt).startswith(t) for t in titles if t):
        return ""
    return " ".join(c["text"] for c in lines[i + 1]["cells"]
                    if min(c["x1"], cell["x1"]) - max(c["x0"], cell["x0"]) > 0)


def _header(rules: dict, pages: list[dict]) -> tuple[dict, int, list[dict]] | None:
    cols = (rules.get("table") or rules["holdings"])["columns"]
    for p in pages:
        for i, ln in enumerate(p["lines"]):
            found = header_cells(cols, ln)
            if found is not None:
                return p, i, found
    return None


def anchors(rules: dict, pages: list[dict]) -> dict | None:
    block = rules.get("table") or rules.get("holdings")
    if block is None:                                         # a loan: its labels, no header positions
        labels = [_anchor(x) for x in (rules["account_label"], rules["period"]["label"], rules["opening"]["label"],
                                       rules["closing"]["label"])]
        out = {"header": [], "sections": [x for x in labels if x]}
        return out if len(out["sections"]) >= MIN_ANCHORS else None
    hit = _header(rules, pages)
    if hit is None:
        return None
    p, i, found = hit
    titles = [norm(s["title"]) for s in rules["table"]["sections"]] if rules.get("table") else [norm(block["total_label"])]
    header = [{"text": _anchor(f"{c['text']} {_below(p['lines'], i, c, titles)}"), "x": round(c["x0"] / p["width"], 4)}
              for c in found]
    sections = [_anchor(t) for t in ([s["title"] for s in rules["table"]["sections"]] if rules.get("table")
                                     else [block["total_label"]])]
    out = {"header": [h for h in header if h["text"]], "sections": [s for s in sections if s]}
    return out if len(out["header"]) + len(out["sections"]) >= MIN_ANCHORS else None


def _texts(a: dict) -> list[str]:
    return [h["text"] for h in a["header"]] + list(a["sections"])


def key_of(a: dict) -> str:
    return "p:" + hashlib.sha256("\x1f".join(sorted(_texts(a))).encode()).hexdigest()


def matches(a: dict, rules: dict, pages: list[dict]) -> bool:
    words = {w for p in pages for ln in p["lines"] for w in _anchor(line_text(ln)).split()}
    if not all(set(t.split()) <= words for t in _texts(a)):
        return False
    if not a["header"]:                                      # a loan: its labels are all there is
        return True
    hit = _header(rules, pages)
    if hit is None or len(hit[2]) != len(a["header"]):
        return False
    p, _, found = hit
    return all(abs(c["x0"] / p["width"] - h["x"]) <= TOLERANCE for c, h in zip(found, a["header"]))


def best(candidates, pages: list[dict]):
    """The matching remembered layout with the most anchors, then the most recently used; None when none matches."""
    hits = []
    for c in candidates:
        a, rules = json.loads(c.anchors), json.loads(c.rules)
        if matches(a, rules, pages):
            hits.append((len(_texts(a)), c.last_used_at or c.created_at, c))
    return max(hits, key=lambda h: (h[0], h[1]))[2] if hits else None
