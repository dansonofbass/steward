"""Lever values over the API (spec 3.6): plain-word type checks, server-side clamping, data-derived try values
that keep following the vault until pinned, and the JSON a saved plan keeps."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from typing import Any

from steward.engine import LEVERS, Household, Levers, ObservedTry, clamp, default_try
from steward.engine.levers import CLAIM_AGE, CONSULTING, GIFT, SAVE_MORE, SPENDING, SPOUSE_EARNINGS

FIELD_LABELS: dict[str, str] = {
    "save_more_monthly_cents": "Save more each month",
    "spending_pct": "Spending in retirement",
    "consulting_cents": "Consulting income",
    "consulting_until_age": "The age consulting stops",
    "gift_cents": "Yearly gift",
    "gift_until_year": "The gift's last year",
    "spouse_earnings_cents": "Spouse's earnings",
    "spouse_start_year": "Spouse's first year of earnings",
    "spouse_stop_age": "The age spouse's earnings stop",
    "jr_claim_age": "{person1}'s claiming age",
    "spouse_claim_age": "Spouse's claiming age",
    "college_levels": "College types",
    "full_ss_benefits": "Full Social Security benefits",
}
LEVER_KEYS: tuple[str, ...] = tuple(spec.key for spec in LEVERS)
SCALES = {"save_more": SAVE_MORE, "spending": SPENDING, "consulting": CONSULTING, "gift": GIFT,
          "spouse_earnings": SPOUSE_EARNINGS, "jr_claim": CLAIM_AGE, "spouse_claim": CLAIM_AGE}
NUMBER_LIMIT = 10**12
NOT_UNDERSTOOD = "The lever values weren't understood."


class LeverError(ValueError):
    """A lever value of the wrong type. The message is shown as is."""


def parse_levers(data: Any, base: Levers) -> Levers:
    if data is None:
        return base
    if not isinstance(data, dict):
        raise LeverError(NOT_UNDERSTOOD)
    changes: dict[str, Any] = {}
    for key, value in data.items():
        label = FIELD_LABELS.get(key)
        if label is None:
            raise LeverError(f"There's no lever called {key}.")
        if key == "full_ss_benefits":
            if not isinstance(value, bool):
                raise LeverError(f"{label} must be on or off.")
        elif key == "college_levels":
            if value is not None:
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    raise LeverError(f"{label} must be a list with one level per child.")
                value = tuple(value)          # unknown level names or the wrong count: clamp uses each child's own
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not value.is_integer()):
                raise LeverError(f"{label} must be a whole number.")
            value = int(value)
            if abs(value) > NUMBER_LIMIT:
                raise LeverError(f"{label} is too large.")
        changes[key] = value
    return replace(base, **changes)


def levers_dict(lv: Levers) -> dict[str, Any]:
    d = asdict(lv)
    d["college_levels"] = list(lv.college_levels) if lv.college_levels is not None else None
    return d


@dataclass(frozen=True)
class LeverState:
    assumed: Levers
    trial: Levers
    pinned: frozenset[str] = frozenset()


def _pinned(value: Any) -> frozenset[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise LeverError("The pinned levers weren't understood.")
    for v in value:
        if v not in LEVER_KEYS:
            raise LeverError(f"There's no lever called {v}.")
    return frozenset(value)


def resolve_state(body: dict, saved: LeverState | None, hh: Household, observed: ObservedTry) -> tuple[LeverState, dict[str, str]]:
    for key in body:
        if key not in ("assumed", "try", "pinned"):
            raise LeverError(f"Unknown field: {key}.")
    assumed = clamp(parse_levers(body.get("assumed"), saved.assumed if saved else Levers()), hh)
    defaults, notes = default_try(hh, assumed, observed)
    try_data = body.get("try")
    typed = parse_levers(try_data, saved.trial if saved else defaults)
    pinned = _pinned(body["pinned"]) if "pinned" in body else (saved.pinned if saved else frozenset())
    if isinstance(try_data, dict):
        pinned = pinned | {spec.key for spec in LEVERS if any(f in try_data for f in spec.fields)}
    chosen: dict[str, Any] = {}
    for spec in LEVERS:
        source = typed if spec.key in pinned else defaults
        for f in spec.fields:
            chosen[f] = getattr(source, f)
    trial = clamp(replace(defaults, **chosen), hh)
    no_history = {n.split(":")[0]: "No history yet" for n in notes}
    return LeverState(assumed, trial, frozenset(pinned)), {k: v for k, v in no_history.items() if k not in pinned}


def state_json(state: LeverState) -> str:
    return json.dumps({"assumed": levers_dict(state.assumed), "try": levers_dict(state.trial),
                       "pinned": sorted(state.pinned)}, sort_keys=True)


def state_from_json(text: str) -> LeverState | None:
    try:
        d = json.loads(text)
        pinned = d.get("pinned", [])
        if not isinstance(pinned, list) or any(p not in LEVER_KEYS for p in pinned):
            return None
        return LeverState(parse_levers(d["assumed"], Levers()), parse_levers(d["try"], Levers()), frozenset(pinned))
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def display_label(label: str, names: dict[str, str]) -> str:
    return (label.replace("Spouse's", f"{names['spouse']}'s").replace("Spouse claims", f"{names['spouse']} claims")
            .replace("{person1}", names["jr"]))


def lever_specs(names: dict[str, str]) -> list[dict]:
    out = []
    for spec in LEVERS:
        scale = SCALES.get(spec.key)
        out.append({"key": spec.key, "label": display_label(spec.label, names), "kind": spec.kind, "fields": list(spec.fields),
                    "scale": None if scale is None else {"lo": scale.lo, "hi": scale.hi, "step": scale.step}})
    return out
