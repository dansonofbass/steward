"""Money in nanodollars (10⁻⁹ $), so every price per million tokens is a whole number per token. The reservation is
the worst case (ruling 1): input at one token per 2 bytes of the request, all of it written to the cache, priced at the
dearest of the answer model and its fallbacks, plus max_tokens of output at that model's output price."""
from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

from steward_gateway.config import FALLBACK_MODELS, GatewayConfig, Price

ND_PER_CENT = 10_000_000
MIN_REQUEST_BYTES = 30_000   # a request the cap must still be able to hold for chat to stay open


def nd(price_per_mtok: Decimal, tokens: int) -> int:
    return int((price_per_mtok * tokens * 1000).to_integral_value(rounding=ROUND_CEILING))


def reserve_price(cfg: GatewayConfig, model: str) -> Price:
    ps = [cfg.prices[m] for m in (model, *FALLBACK_MODELS)]
    return Price(max(p.input for p in ps), max(p.output for p in ps), max(p.cache_write for p in ps),
                 max(p.cache_read for p in ps))


def estimate_nd(body_bytes: int, max_tokens: int, price: Price) -> int:
    input_tokens = -(-body_bytes // 2)
    return nd(price.cache_write, input_tokens) + nd(price.output, max_tokens)


def cost_nd(usage: dict, price: Price) -> int:
    return (nd(price.input, usage.get("input_tokens") or 0)
            + nd(price.cache_write, usage.get("cache_creation_input_tokens") or 0)
            + nd(price.cache_read, usage.get("cache_read_input_tokens") or 0)
            + nd(price.output, usage.get("output_tokens") or 0))


def settle_price(cfg: GatewayConfig, served_model: str, usage: dict) -> Price:
    """The served model's price; when a fallback ran in this request, the dearest price of the chain."""
    fell_back = any(isinstance(i, dict) and i.get("type") == "fallback_message" for i in usage.get("iterations") or [])
    if fell_back or served_model not in cfg.prices:
        return reserve_price(cfg, served_model if served_model in cfg.prices else cfg.default_model)
    return cfg.prices[served_model]


def cents(n: int) -> int:
    return n // ND_PER_CENT


def dollars(n: int) -> str:
    c = cents(n)
    return f"${c // 100:,}" if c % 100 == 0 else f"${c // 100:,}.{c % 100:02d}"
