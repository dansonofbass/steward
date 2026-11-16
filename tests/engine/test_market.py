import numpy as np
import pytest

from steward.engine import datafiles, market
from steward.engine.inputs import Mix


def test_constants_match_the_spec():
    assert (market.N_HISTORIES, market.MEAN_BLOCK_YEARS) == (2000, 8) and isinstance(market.SEED, int)


def test_real_returns_strip_inflation():
    rr = market.real_returns(datafiles.market())
    i = list(rr.years).index(2022)
    assert rr.stock[i] == pytest.approx((1 - 0.180375) / 1.064544 - 1)
    assert rr.bond[i] == pytest.approx((1 - 0.178282) / 1.064544 - 1)
    i = list(rr.years).index(1980)
    assert rr.cash[i] == pytest.approx(1.113919 / 1.125163 - 1)
    assert rr.stock.shape == rr.bond.shape == rr.cash.shape == (98,)
    assert 0.05 < np.mean(rr.stock) < 0.10 and -0.01 < np.mean(rr.cash) < 0.02   # sanity: real equity premium exists


def test_bootstrap_indices_are_runs_of_consecutive_years():
    rng = np.random.default_rng(1)
    idx = market.block_bootstrap_indices(2000, 50, 98, 8, rng)
    assert idx.shape == (2000, 50) and idx.dtype == np.int64 and idx.min() >= 0 and idx.max() < 98
    step = idx[:, 1:]
    prev = idx[:, :-1]
    continued = step == (prev + 1) % 98
    jumped = ~continued
    assert 0.10 < jumped.mean() < 0.15                  # one jump in eight years on average -> mean block about 8
    assert continued.any(axis=1).all()                  # every history has at least one continued year


def test_sample_histories_is_deterministic_and_shaped():
    md = datafiles.market()
    a = market.sample_histories(md, 300, 40, np.random.default_rng(market.SEED))
    b = market.sample_histories(md, 300, 40, np.random.default_rng(market.SEED))
    assert np.array_equal(a.stock, b.stock) and np.array_equal(a.source_index, b.source_index)
    assert a.stock.shape == a.bond.shape == a.cash.shape == (300, 40)
    c = market.sample_histories(md, 300, 40, np.random.default_rng(market.SEED + 1))
    assert not np.array_equal(a.stock, c.stock)
    rr = market.real_returns(md)
    assert np.array_equal(a.stock, rr.stock[a.source_index])   # histories are the real series re-ordered


def test_mix_return_weights_and_subtracts_fees():
    hist = market.Histories(stock=np.full((2, 3), 0.10), bond=np.full((2, 3), 0.02), cash=np.zeros((2, 3)),
                            source_index=np.zeros((2, 3), dtype=np.int64))
    out = market.mix_return(hist, Mix(0.6, 0.4, 0.0, fee_bp=20))
    assert np.allclose(out, 0.6 * 0.10 + 0.4 * 0.02 - 0.002)
    assert np.allclose(market.mix_return(hist, Mix(0.0, 0.0, 1.0)), 0.0)
