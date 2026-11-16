"""History MACs (ruling 2). Every message the gateway sends to or receives from Anthropic is MAC'd with a key only
the gateway holds; the NAS stores the MAC beside the message and sends both back next turn. A message whose MAC doesn't
verify is refused, so history the NAS changed (or a bug that wrote real names into it) can't be sent."""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path

from steward_boundary.canonical import canonical
from steward_gateway.secrets import read_private, write_private


def load_or_create_key(path: Path) -> bytes:
    existing = read_private(path)
    if existing:
        return bytes.fromhex(existing)
    key = os.urandom(32)
    write_private(path, key.hex())
    return key


def mac(key: bytes, message: dict) -> str:
    return hmac.new(key, canonical(message), hashlib.sha256).hexdigest()


def verify(key: bytes, message: dict, tag: str) -> bool:
    return isinstance(tag, str) and hmac.compare_digest(mac(key, message), tag)
