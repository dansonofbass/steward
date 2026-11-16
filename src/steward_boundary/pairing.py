"""The pairing code's alphabet and shapes, shared by the gateway and Steward (guided setup spec 6). Stdlib only."""
from __future__ import annotations

import secrets

PAIR_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"    # 31 characters: no 0, O, 1, I or L


def normalize(code: str) -> str:
    return "".join(c for c in code.upper() if c.isalnum())


def short_code() -> str:
    """Six characters in two groups, like K7M-4QX: short enough to type from a screen."""
    raw = "".join(secrets.choice(PAIR_ALPHABET) for _ in range(6))
    return f"{raw[:3]}-{raw[3:]}"
