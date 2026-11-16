"""A small JSON Schema validator for the subset the tool schemas and WebSocket frames use. Messages name the path and
the problem, never the value, so they can go to logs and book events."""
from __future__ import annotations

import math
import re
from collections.abc import Iterator
from typing import Any

from steward_boundary.schema import string_kind
from steward_boundary.text import ISO_DATE_RE


def validate(schema: dict, value: Any, path: str = "$") -> list[str]:
    if "anyOf" in schema:
        if any(not validate(s, value, path) for s in schema["anyOf"]):
            return []
        return [f"{path}: matches none of the allowed shapes"]
    t = schema.get("type")
    if t == "object":
        if not isinstance(value, dict):
            return [f"{path}: expected an object"]
        props = schema.get("properties")
        if props is None:
            return []
        errs = [f"{path}.{k}: missing" for k in schema.get("required", []) if k not in value]
        extra = 0
        for k, v in value.items():
            if k not in props:
                if schema.get("additionalProperties", True) is False:
                    extra += 1
                continue
            errs += validate(props[k], v, f"{path}.{k}")
        if extra:
            errs.append(f"{path}: has {extra} field(s) that aren't allowed")
        return errs
    if t == "array":
        if not isinstance(value, list):
            return [f"{path}: expected a list"]
        errs = [f"{path}: too many items"] if len(value) > schema.get("maxItems", math.inf) else []
        for i, v in enumerate(value):
            errs += validate(schema["items"], v, f"{path}[{i}]")
        return errs
    if t == "integer":
        return [] if isinstance(value, int) and not isinstance(value, bool) else [f"{path}: expected a whole number"]
    if t == "number":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        return [] if ok else [f"{path}: expected a number"]
    if t == "boolean":
        return [] if isinstance(value, bool) else [f"{path}: expected true or false"]
    if t == "null":
        return [] if value is None else [f"{path}: expected null"]
    if t == "string":
        if not isinstance(value, str):
            return [f"{path}: expected text"]
        if "enum" in schema and value not in schema["enum"]:
            return [f"{path}: not one of the allowed values"]
        if "pattern" in schema and re.fullmatch(schema["pattern"].strip("^$"), value) is None:
            return [f"{path}: doesn't match the allowed shape"]
        if len(value) > schema.get("maxLength", math.inf):
            return [f"{path}: too long"]
        if schema.get("format") == "date" and ISO_DATE_RE.fullmatch(value) is None:
            return [f"{path}: not a date"]
        return []
    return [f"{path}: unknown schema"]


def walk_strings(schema: dict, value: Any, path: str = "$") -> Iterator[tuple[str, str | None, str]]:
    """Every string in a value that validates, with the kind its schema gives it."""
    if "anyOf" in schema:
        for s in schema["anyOf"]:
            if not validate(s, value, path):
                yield from walk_strings(s, value, path)
                return
        return
    t = schema.get("type")
    if t == "object" and isinstance(value, dict):
        props = schema.get("properties") or {}
        for k, v in value.items():
            if k in props:
                yield from walk_strings(props[k], v, f"{path}.{k}")
    elif t == "array" and isinstance(value, list):
        for i, v in enumerate(value):
            yield from walk_strings(schema["items"], v, f"{path}[{i}]")
    elif t == "string" and isinstance(value, str):
        yield path, string_kind(schema), value


def untyped_string_paths(schema: dict, path: str = "$") -> list[str]:
    if "anyOf" in schema:
        return [p for s in schema["anyOf"] for p in untyped_string_paths(s, path)]
    t = schema.get("type")
    if t == "object":
        return [p for k, s in (schema.get("properties") or {}).items() for p in untyped_string_paths(s, f"{path}.{k}")]
    if t == "array":
        return untyped_string_paths(schema["items"], f"{path}[]")
    if t == "string" and string_kind(schema) is None:
        return [path]
    return []
