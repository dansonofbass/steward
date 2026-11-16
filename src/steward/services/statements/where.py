"""Where statement PDFs are opened (remote-reading amendment P54). auto, the default, asks the sandbox's child once at
startup: Steward opens PDFs itself only when the child installs its seccomp filter and its Landlock wall and reads the
canary inside both (can_wall, the gateway's own rule), and otherwise sends them to the gateway. local and gateway force
it. A forced local on a kernel without both fails closed: the child refuses every PDF."""
from __future__ import annotations

import logging
from collections.abc import Callable

from steward import gateway_name
from steward_pdf.sandbox import can_wall, confinement

log = logging.getLogger(__name__)
PLACES = ("local", "gateway")


def resolve(setting: str, *, probe: bool, check: Callable[[], dict] = confinement) -> str:
    """The place for this process. probe is False under tests (no child is started for it; auto is local)."""
    if setting in PLACES:
        if setting == "local" and probe and not can_wall(check()):
            log.warning("statement_reading is local, but the sandbox can't confine itself here (it needs a seccomp "
                        "filter and a Landlock wall): every PDF is refused")
        return setting
    if not probe:
        return "local"
    place = "local" if can_wall(check()) else "gateway"
    log.info("PDF statements are opened %s", "on this machine" if place == "local" else gateway_name.fill("on {gateway}"))
    return place
