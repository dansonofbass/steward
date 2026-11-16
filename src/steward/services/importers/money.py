import re
from datetime import date, datetime
from decimal import Decimal

_NUMBER = r"(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?|\.\d{1,2})"
# Optional sign, optional "$", then digits (proper thousands grouping, up to two decimals).
_AMOUNT = re.compile(rf"(?P<sign>[+-])?\s*\$?\s*(?P<num>{_NUMBER})", re.ASCII)
_PARENS = re.compile(rf"\(\s*\$?\s*(?P<num>{_NUMBER})\s*\)", re.ASCII)


def parse_cents(text: str) -> int:
    s = text.strip()
    if not s:
        raise ValueError("empty amount")
    if m := _PARENS.fullmatch(s):
        neg = True
    elif m := _AMOUNT.fullmatch(s):
        neg = m.group("sign") == "-"
    else:
        raise ValueError(f"not a money amount: {text!r}")
    cents = int((Decimal(m.group("num").replace(",", "")) * 100).to_integral_value())
    return -cents if neg else cents


def parse_date(text: str, formats: tuple[str, ...]) -> date:
    s = text.strip()
    for f in formats:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    raise ValueError(f"not a date: {text!r}")
