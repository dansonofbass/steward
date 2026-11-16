"""The one way a value becomes bytes: for hashes in the log of what was sent, the gateway's sent list, MACs and tool
results inside requests. Sorted keys keep the prompt prefix and every hash stable (spec 8.3)."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()
