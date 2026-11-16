"""Validating a layout proposal on the NAS (spec P16), after the wire's shape check: every label, header cell, section
title and skip label occurs verbatim in the lines that were sent (the exact characters, case kept, whitespace runs
collapsed; ruling F5); a header cell printed on two lines is accepted when all its words are on neighbouring lines
(H1); each field at most once; amount or debit and credit, never both; a date, a description and money for a bank or
card; the header cells all on one line, so the bands can be derived; a section title starts a line that isn't the
header line (normalized). A proposal that fails counts as no answer, so a statement's own text can't steer what
Steward reads.

Labels are words, not fragments, matched by labels.py, the one matcher reading uses too: at least 3 letters,
something left after normalizing, at word boundaries in the masked text, case kept, so "a", ":" or "ate" (inside
"Date") never pass; a section title or total must start a line, and a skip label start a line or be a whole cell,
exactly as rules.py applies them."""
from __future__ import annotations

from steward.services.statements import labels
from steward.services.statements.extract import line_text, norm
from steward.services.statements.labels import MIN_LETTERS
from steward.services.statements.rules import header_cells
from steward_boundary.statements_wire import shape_errors


def errors(p, sent: list[dict]) -> list[str]:
    errs = shape_errors(p)
    if errs:
        return errs
    lines = [(pi, ln) for pi, pg in enumerate(sent) for ln in pg["lines"]]
    texts = [norm(line_text(ln)) for _, ln in lines]
    exact = [line_text(ln) for _, ln in lines]

    def has(label: str) -> bool:
        return any(labels.occurs(label, t) for t in exact)

    def check(label: str, what: str) -> None:
        if labels.short(label):
            errs.append(f"{what} needs at least {MIN_LETTERS} letters")
        elif not has(label):
            errs.append(f"{what} isn't in the lines sent")

    for what, label in (("period", p["period"]["label"]), ("opening", p["opening"]["label"]),
                        ("closing", p["closing"]["label"]), ("account", p["account_label"])):
        check(label, f"the {what} label")
    if p["account_marker"]:
        check(p["account_marker"], "the account marker")
    if p["kind"] == "loan":                               # a loan gives its principal only (spec decision 2)
        if p["table"] is not None or p["holdings"] is not None:
            errs.append("a loan statement gives its balance only")
        return errs
    if p["kind"] in ("investment", "retirement"):
        if p["table"] is not None:
            errs.append("an investment statement gives holdings, not a table")
        return errs + _holdings(p["holdings"], lines, exact, texts, has)
    if p["holdings"] is not None:
        errs.append("a bank or card statement gives a table, not holdings")
    t = p["table"]
    if t is None:
        return [*errs, "a bank or card statement needs a table"]
    fields = [c["field"] for c in t["columns"]]
    for f in sorted(set(fields) - {"ignore"}):
        if fields.count(f) > 1:
            errs.append(f"{f} is given more than once")
    if "amount" in fields and {"debit", "credit"} & set(fields):
        errs.append("one amount column or debit and credit columns, not both")
    if not {"date", "post_date"} & set(fields):
        errs.append("no date column")
    if "description" not in fields:
        errs.append("no description column")
    if "amount" not in fields and not {"debit", "credit"} <= set(fields):
        errs.append("no money column")
    head_at = {i for i, (_, ln) in enumerate(lines) if header_cells(t["columns"], ln) is not None}
    if not head_at:
        errs.append("the header cells aren't on one line")
    for c in t["columns"]:
        if labels.short(c["header"]):
            errs.append(f"a header cell needs at least {MIN_LETTERS} letters")
        elif not has(c["header"]) and not _two_lines(norm(c["header"]), lines, texts):
            errs.append("a header cell isn't in the lines sent")
    for s in t["sections"]:
        check(s["title"], "a section title")
        if not any(labels.starts(s["title"], exact[i]) for i in range(len(exact)) if i not in head_at):
            errs.append("a section title doesn't start a line")
        if s["total_label"]:
            check(s["total_label"], "a total label")
            if has(s["total_label"]) and not any(labels.starts(s["total_label"], x) for x in exact):
                errs.append("a total label doesn't start a line")
    for label in t["skip"]:
        check(label, "a skip label")
        if has(label) and not any(labels.opens(label, ln) for _, ln in lines):
            errs.append("a skip label doesn't start a line or fill a cell")
    return errs


def _holdings(h, lines, exact, texts, has) -> list[str]:
    """P16 for an investment statement: value and a symbol or name; each field at most once; the header cells on one
    line; every header, the total, the ending and each cash label verbatim in the lines sent, the total starting a line."""
    if h is None:
        return ["an investment statement needs holdings"]
    errs = []
    fields = [c["field"] for c in h["columns"]]
    for f in sorted(set(fields) - {"ignore"}):
        if fields.count(f) > 1:
            errs.append(f"{f} is given more than once")
    if "value" not in fields or not {"symbol", "name"} & set(fields):
        errs.append("holdings need a value and a symbol or a name")
    if not any(header_cells(h["columns"], ln) is not None for _, ln in lines):
        errs.append("the holdings header cells aren't on one line")
    for c in h["columns"]:
        if labels.short(c["header"]):
            errs.append(f"a holdings header cell needs at least {MIN_LETTERS} letters")
        elif not has(c["header"]) and not _two_lines(norm(c["header"]), lines, texts):
            errs.append("a holdings header cell isn't in the lines sent")
    for what, label in (("total", h["total_label"]), ("ending", h["ending"]["label"]),
                        *(("cash", x) for x in h["cash_labels"])):
        if labels.short(label):
            errs.append(f"a holdings {what} label needs at least {MIN_LETTERS} letters")
        elif not has(label):
            errs.append(f"a holdings {what} label isn't in the lines sent")
    if has(h["total_label"]) and not any(labels.starts(h["total_label"], x) for x in exact):
        errs.append("the holdings total label doesn't start a line")
    return errs


def _two_lines(head: str, lines: list[tuple[int, dict]], texts: list[str]) -> bool:
    words = set(head.split())
    if not words:
        return False                                      # the empty set is a subset of every line: never a header
    for i in range(len(lines) - 1):
        if lines[i][0] == lines[i + 1][0] and words <= set(texts[i].split()) | set(texts[i + 1].split()):
            return True
    return False
