"""Pairing (spec 3.2, ruling 14). `steward-gateway pair <code>` arms a 10-minute window with the code's hash; the NAS,
polling POST /v1/pair with the code it printed, gets a fresh 32-byte token once. Five wrong codes end the window."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta

from steward_boundary.pairing import normalize
from steward_gateway.config import GatewayConfig
from steward_gateway.secrets import read_private, write_private

WINDOW_S = 600
TRIES = 5


class PairRefused(Exception):
    def __init__(self, status: int, message: str, tries_left: int | None = None):
        super().__init__(message)
        self.status, self.message, self.tries_left = status, message, tries_left


def _digest(code: str) -> str:
    return hashlib.sha256(normalize(code).encode()).hexdigest()


def arm(cfg: GatewayConfig, code: str, now: datetime) -> None:
    write_private(cfg.pending_pair_path, json.dumps({"code_sha256": _digest(code), "tries": 0,
                                                     "expires": (now + timedelta(seconds=WINDOW_S)).isoformat()}))


def claim(cfg: GatewayConfig, code: str, now: datetime) -> str:
    raw = read_private(cfg.pending_pair_path)
    waiting = "No pairing is waiting. Run steward-gateway pair on this machine."
    if raw is None:
        raise PairRefused(404, waiting)
    pending = json.loads(raw)
    if now >= datetime.fromisoformat(pending["expires"]):
        os.remove(cfg.pending_pair_path)
        raise PairRefused(404, waiting)
    if not secrets.compare_digest(pending["code_sha256"], _digest(code)):
        pending["tries"] += 1
        if pending["tries"] >= TRIES:
            os.remove(cfg.pending_pair_path)
        else:
            write_private(cfg.pending_pair_path, json.dumps(pending))
        raise PairRefused(403, "That code doesn't match the one given to steward-gateway pair.",
                          tries_left=TRIES - pending["tries"])
    token = secrets.token_hex(32)
    write_private(cfg.token_path, token)
    os.remove(cfg.pending_pair_path)
    return token
