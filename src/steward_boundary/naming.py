"""The gateway's name in copy (spec 2026-11-05, section 7). Copy names the gateway machine through GATEWAY_SLOT. The NAS
fills it with STEWARD_GATEWAY_NAME (steward/gateway_name.py, "the gateway" when unset); the gateway's own CLI and its
errors for its own operator fill it with THIS_MACHINE. A line the gateway sends the NAS keeps the slot, and the NAS
fills it with its name."""
from __future__ import annotations

import re

GATEWAY_SLOT = "{gateway}"
DEFAULT_GATEWAY_NAME = "the gateway"
THIS_MACHINE = "this machine"
_AT_START = re.compile(r"(^|[.!?]\s+|\n\s*)\{gateway\}")


def name_in(text: str, name: str) -> str:
    """text with every {gateway} filled with name, capitalized where it starts the text or a sentence."""
    cap = name[:1].upper() + name[1:]
    return _AT_START.sub(lambda m: m.group(1) + cap, text).replace(GATEWAY_SLOT, name)
