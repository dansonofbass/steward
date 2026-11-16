"""Building blocks for the tool schemas (spec 4.2). Result strings carry a kind: an enum, an alias, an ISO date or
month, a ticker symbol, or free_text. Input schemas are sent to Anthropic with strict: true, so they use only what strict tool use
accepts (types, enum, anyOf, optional properties, additionalProperties false, format "date"); ranges are checked by
the tools."""
from __future__ import annotations

from collections.abc import Sequence

from steward_boundary.aliases import ALIAS_PATTERN

INT = {"type": "integer"}
NUM = {"type": "number"}
BOOL = {"type": "boolean"}
NULL = {"type": "null"}
ALIAS = {"type": "string", "pattern": ALIAS_PATTERN, "x-kind": "alias"}
DATE = {"type": "string", "pattern": r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])$", "x-kind": "date"}
MONTH = {"type": "string", "pattern": r"^[0-9]{4}-(?:0[1-9]|1[0-2])$", "x-kind": "month"}
IN_DATE = {"type": "string", "format": "date"}
# A holding's ticker: letters only, as the NAS sends it (plan ruling 25). Proven by its shape, so the model pass never
# reads it (privacy approach review, 2026-10-24).
SYMBOL_PATTERN = r"^[A-Z]{1,5}$"
SYMBOL = {"type": "string", "pattern": SYMBOL_PATTERN, "x-kind": "symbol"}
STRING_KINDS = ("enum", "alias", "date", "month", "symbol", "free_text")


def enum(values: Sequence[str]) -> dict:
    return {"type": "string", "enum": list(values)}


def free_text(max_length: int) -> dict:
    return {"type": "string", "maxLength": max_length, "x-kind": "free_text"}


def nullable(s: dict) -> dict:
    return {"anyOf": [s, NULL]}


def obj(props: dict, optional: Sequence[str] = ()) -> dict:
    """Every property is required unless named in `optional`, which strict tool use lets the model leave out. Anthropic
    refuses a request with more than 16 union-typed parameters (nullable is a union) and caps optional ones at about
    24 across all strict schemas, so optional is kept for fields where leaving one out has a plain meaning."""
    unknown = set(optional) - set(props)
    if unknown:
        raise ValueError(f"optional names fields the object doesn't have: {sorted(unknown)}")
    return {"type": "object", "properties": props, "required": [k for k in props if k not in optional],
            "additionalProperties": False}


def arr(items: dict, max_items: int | None = None) -> dict:
    out = {"type": "array", "items": items}
    if max_items is not None:
        out["maxItems"] = max_items
    return out


def string_kind(s: dict) -> str | None:
    if "enum" in s:
        return "enum"
    return s.get("x-kind")
