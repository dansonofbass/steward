from decimal import Decimal

from steward_gateway.config import GatewayConfig
from steward_gateway.prices import cents, cost_nd, dollars, estimate_nd, nd, reserve_price, settle_price


def test_nanodollars():
    assert nd(Decimal("4.00"), 1) == 4000
    assert nd(Decimal("0.20"), 3) == 600
    assert nd(Decimal("5.00"), 1_000_000) == 5_000_000_000         # $5
    assert nd(Decimal("0.20"), 1) == 200


def test_the_reservation_is_the_worst_case(tmp_path):
    cfg = GatewayConfig(tmp_path, tmp_path)
    p = reserve_price(cfg, "claude-opus-5-5")
    assert (p.input, p.output, p.cache_write, p.cache_read) == (Decimal("5.00"), Decimal("25.00"), Decimal("6.25"), Decimal("0.50"))
    # 30,000 bytes is 15,000 tokens at the cache-write price, plus 16,000 output tokens (ruling 1)
    assert estimate_nd(30_000, 16_000, p) == 15_000 * 6250 + 16_000 * 25_000


def test_the_real_cost_uses_every_usage_field(tmp_path):
    cfg = GatewayConfig(tmp_path, tmp_path)
    usage = {"input_tokens": 1000, "cache_creation_input_tokens": 4500, "cache_read_input_tokens": 9000,
             "output_tokens": 2500}
    p = settle_price(cfg, "claude-opus-5-5", usage)
    assert cost_nd(usage, p) == 1000 * 4000 + 4500 * 5000 + 9000 * 200 + 2500 * 20_000


def test_a_fallback_is_priced_at_the_dearer_model(tmp_path):
    cfg = GatewayConfig(tmp_path, tmp_path)
    usage = {"input_tokens": 10, "output_tokens": 10, "iterations": [{"type": "fallback_message"}]}
    assert settle_price(cfg, "claude-opus-5", usage).output == Decimal("25.00")
    assert settle_price(cfg, "claude-opus-5-5", {"input_tokens": 1}).output == Decimal("20.00")


def test_dollars_and_cents():
    assert dollars(3_120_000_000) == "$3.12" and dollars(10_000_000_000) == "$10" and cents(3_129_999_999) == 312
