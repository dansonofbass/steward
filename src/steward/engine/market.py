"""Market history (spec section 3.1): Damodaran's annual series in real terms, stitched into
histories by a stationary block bootstrap with a mean run of eight years, under a fixed seed."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from steward.engine.datafiles import MarketData
from steward.engine.inputs import Mix

N_HISTORIES = 2000
SEED = 20261013
MEAN_BLOCK_YEARS = 8


@dataclass(frozen=True)
class RealReturns:
    years: np.ndarray
    stock: np.ndarray
    bond: np.ndarray
    cash: np.ndarray


def real_returns(md: MarketData) -> RealReturns:
    real = lambda r: (1.0 + r) / (1.0 + md.cpi) - 1.0  # noqa: E731
    return RealReturns(years=md.years, stock=real(md.stock), bond=real(md.tbond), cash=real(md.tbill))


def block_bootstrap_indices(n_hist: int, n_years: int, n_source: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """Stationary block bootstrap: continue the previous source year (wrapping) with probability
    1 - 1/mean_block, otherwise jump to a fresh random year. Block lengths are geometric with mean mean_block."""
    starts = rng.integers(0, n_source, size=(n_hist, n_years), dtype=np.int64)
    jump = rng.random((n_hist, n_years)) < 1.0 / mean_block
    idx = np.empty((n_hist, n_years), dtype=np.int64)
    idx[:, 0] = starts[:, 0]
    for t in range(1, n_years):
        idx[:, t] = np.where(jump[:, t], starts[:, t], (idx[:, t - 1] + 1) % n_source)
    return idx


@dataclass(frozen=True)
class Histories:
    stock: np.ndarray         # (H, Y) real returns
    bond: np.ndarray
    cash: np.ndarray
    source_index: np.ndarray  # (H, Y) index into the source series
    cpi: np.ndarray | None = None   # (H, Y) inflation in each simulated year; None: no inflation (fixed-dollar amounts keep their value)


def sample_histories(md: MarketData, n_hist: int, n_years: int, rng: np.random.Generator) -> Histories:
    rr = real_returns(md)
    idx = block_bootstrap_indices(n_hist, n_years, len(rr.years), MEAN_BLOCK_YEARS, rng)
    return Histories(stock=rr.stock[idx], bond=rr.bond[idx], cash=rr.cash[idx], source_index=idx, cpi=md.cpi[idx])


def mix_return(hist: Histories, mix: Mix) -> np.ndarray:
    return mix.stock * hist.stock + mix.bond * hist.bond + mix.cash * hist.cash - mix.fee_bp / 10_000
