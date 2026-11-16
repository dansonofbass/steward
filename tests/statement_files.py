"""The synthetic statements for the NAS's tests, built once a session in memory (never written to disk)."""
from __future__ import annotations

import copy
from datetime import date
from functools import lru_cache

from steward_gateway.evals.statement_set import Truth, build


@lru_cache(maxsize=None)
def pdf(sid: str, variant: str | None = None, end: date | None = None) -> tuple[bytes, Truth]:
    return build(sid, end, variant)


@lru_cache(maxsize=None)
def _pages(sid: str, variant: str | None) -> list[dict]:
    from steward_pdf.sandbox import read_pdf            # in-process: the child's own function
    return read_pdf(pdf(sid, variant)[0])["pages"]


def pages(sid: str, variant: str | None = None) -> list[dict]:
    """The statement's extracted pages, a fresh copy each call so no test changes another's."""
    return copy.deepcopy(_pages(sid, variant))
