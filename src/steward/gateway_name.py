"""What Steward calls the gateway machine on its screens, in its CLI and in its log (spec 2026-11-05, section 7):
STEWARD_GATEWAY_NAME, "the gateway" when unset. create_app and the CLI set it from Settings at start (configure), as
clock.configure sets the time zone; fill() puts it into copy's {gateway}. A machine's name, not a person's, and never
sent to Claude (tests/advisor/test_gateway_name_stays_home.py)."""
from __future__ import annotations

import unicodedata

from steward_boundary.naming import DEFAULT_GATEWAY_NAME, name_in

MAX_NAME = 40
NAME_RULE = "STEWARD_GATEWAY_NAME must be up to 40 characters, with no braces or control characters."

_name = DEFAULT_GATEWAY_NAME


def clean(raw: str | None) -> str:
    """The name as Steward shows it: each run of spaces made one, and the default when nothing is left. ValueError
    for a name copy can't hold (braces would also break str.format in the statements' copy)."""
    name = " ".join((raw or "").split())
    if not name:
        return DEFAULT_GATEWAY_NAME
    if len(name) > MAX_NAME or "{" in name or "}" in name or any(unicodedata.category(c).startswith("C") for c in name):
        raise ValueError(NAME_RULE)
    return name


def configure(raw: str | None) -> str:
    global _name
    _name = clean(raw)
    return _name


def reset() -> None:
    global _name
    _name = DEFAULT_GATEWAY_NAME


def current() -> str:
    return _name


def fill(text: str) -> str:
    return name_in(text, _name)
