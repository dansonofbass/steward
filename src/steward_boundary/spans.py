"""Edits to a piece of text and the chips that show them (spec 4.3, 5.3). The NAS's exact pass, the masking rule and
the gateway's models each produce edits on the same plain text (normal.view's `plain`); apply() makes the new text
and the chips; shift() carries an earlier layer's chips through a later layer's edits.

Hardened in Task 2.5: overlapping edits merge into one edit covering all of them (the widest's label), so no part of
an identifier is left between two detections; edits are applied right to left on the text they were computed on and
must lie inside it; a later edit that overlaps an earlier chip is an error, never a silently wrong chip."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Edit:
    start: int
    end: int
    label: str
    layer: str


def merge(edits: Iterable[Edit]) -> list[Edit]:
    """Sorted and non-overlapping. Edits that overlap become one edit covering all of them, with the label and layer
    of the widest (the earliest on a tie). Touching edits stay apart; empty ones go."""
    groups: list[list[Edit]] = []
    end = -1
    for e in sorted((e for e in edits if e.end > e.start), key=lambda e: (e.start, e.end)):
        if groups and e.start < end:
            groups[-1].append(e)
            end = max(end, e.end)
        else:
            groups.append([e])
            end = e.end
    out = []
    for g in groups:
        widest = min(g, key=lambda e: (-(e.end - e.start), e.start))
        out.append(Edit(g[0].start, max(e.end for e in g), widest.label, widest.layer))
    return out


def apply(text: str, edits: Iterable[Edit]) -> tuple[str, list[dict]]:
    """The new text and its chips. The edits must lie inside `text`, the string they were computed on."""
    merged = merge(edits)
    for e in merged:
        if e.start < 0 or e.end > len(text):
            raise ValueError("an edit lies outside the text it is applied to")
    out = text
    for e in reversed(merged):                      # right to left, so earlier offsets stay put
        out = out[:e.start] + e.label + out[e.end:]
    chips, delta = [], 0
    for e in merged:
        start = e.start + delta
        chips.append({"start": start, "end": start + len(e.label), "label": e.label, "layer": e.layer})
        delta += len(e.label) - (e.end - e.start)
    return out, chips


def shift(chips: Sequence[dict], edits: Iterable[Edit]) -> list[dict]:
    """Earlier chips moved past later edits made on the text that holds them. A later edit may not overlap a chip:
    later layers skip what the NAS issued (aliases.protected_spans), so an overlap is a bug and raises."""
    merged = merge(edits)
    out = []
    for c in chips:
        if overlaps(c["start"], c["end"], [(e.start, e.end) for e in merged]):
            raise ValueError("a later edit overlaps an earlier chip")
        delta = sum(len(e.label) - (e.end - e.start) for e in merged if e.end <= c["start"])
        out.append({**c, "start": c["start"] + delta, "end": c["end"] + delta})
    return out


def overlaps(start: int, end: int, spans: Iterable[tuple[int, int]]) -> bool:
    return any(start < e and s < end for s, e in spans)


def outside(start: int, end: int, protected: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """The parts of [start, end) that no protected span covers. A detector span that runs into an issued alias is
    cut to these parts, never dropped whole, so an alias can't shield the name beside it."""
    parts, at = [], start
    for s, e in sorted(protected):
        if e <= at or s >= end:
            continue
        if s > at:
            parts.append((at, s))
        at = max(at, e)
    if at < end:
        parts.append((at, end))
    return parts
