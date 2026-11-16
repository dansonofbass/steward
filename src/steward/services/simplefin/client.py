import base64
import binascii
from dataclasses import dataclass, field
import json
import logging
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx2

from steward import clock

DEFAULT_HOSTS = ("bridge.simplefin.org", "beta-bridge.simplefin.org")
_PLAIN_HTTP_OK = {"testserver"}


log = logging.getLogger(__name__)


class SimplefinError(RuntimeError):
    pass


UNREACHABLE = "Couldn't reach SimpleFIN. Steward will try again at the next sync."


def _allowed(url: str, allowed_hosts) -> bool:
    p = urlsplit(url)
    host = p.hostname
    if host is None or host not in allowed_hosts:
        return False
    return p.scheme == "https" or (p.scheme == "http" and host in _PLAIN_HTTP_OK)


def _cents(text: str) -> int:
    try:
        d = Decimal(str(text).strip())
        if not d.is_finite() or d != d.quantize(Decimal("0.01")):
            raise ValueError(f"not whole cents: {text!r}")
        return int(d * 100)
    except ArithmeticError:  # InvalidOperation, e.g. "1e30" overflows the quantize
        raise ValueError(f"not an amount: {text!r}") from None


@dataclass(frozen=True)
class Connection:
    conn_id: str; name: str; org_id: str


@dataclass(frozen=True)
class SfTxn:
    id: str; posted_at: date; amount_cents: int; description: str


@dataclass(frozen=True)
class SfError:
    code: str; msg: str; conn_id: str | None; account_id: str | None


@dataclass(frozen=True)
class SfHolding:
    symbol: str | None; description: str; shares_milli: int; market_value_cents: int; cost_basis_cents: int | None


@dataclass
class SfAccount:
    id: str; name: str; conn_id: str; currency: str
    balance_cents: int; balance_date: date
    transactions: list[SfTxn] = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    holdings: list[SfHolding] | None = None   # None: the account sent no holdings list


@dataclass
class AccountSet:
    connections: list[Connection]
    accounts: list[SfAccount]
    errors: list[SfError]


def parse_setup_token(token: str, allowed_hosts=DEFAULT_HOSTS) -> str:
    try:
        url = base64.b64decode(token.strip(), validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        raise ValueError("That setup token isn't valid.") from None
    if not url.startswith(("http://", "https://")):
        raise ValueError("That setup token isn't valid.")
    if not _allowed(url, allowed_hosts):
        raise SimplefinError("That setup token isn't valid.")
    return url


def claim(http, claim_url: str, allowed_hosts=DEFAULT_HOSTS) -> str:
    if not _allowed(claim_url, allowed_hosts):
        raise SimplefinError("That setup token isn't valid.")
    try:
        r = http.post(claim_url)
    except httpx2.HTTPError:
        raise SimplefinError(UNREACHABLE) from None
    if r.status_code == 403:
        raise SimplefinError("That setup token was already used or has expired. Make a new one at SimpleFIN.")
    if r.status_code != 200:
        raise SimplefinError(f"SimpleFIN didn't accept the setup token (HTTP {r.status_code}).")
    access_url = r.text.strip()
    if not _allowed(access_url, allowed_hosts):
        raise SimplefinError("That SimpleFIN address isn't allowed.")
    return access_url


def split_access_url(access_url: str) -> tuple[str, str, str]:
    p = urlsplit(access_url)
    if p.hostname is None:
        raise SimplefinError("That SimpleFIN address isn't valid.")
    base = urlunsplit((p.scheme, p.hostname + (f":{p.port}" if p.port else ""), p.path, "", "")).rstrip("/")
    return base, unquote(p.username or ""), unquote(p.password or "")


def _household_date(epoch: int) -> date:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(clock.household_tz()).date()


def _rounded_cents(text: object) -> int:
    """A holding's money, which brokers send with more than two decimals: rounded half up to whole cents."""
    d = Decimal(str(text).strip().replace(",", ""))
    if not d.is_finite():
        raise ValueError(f"not an amount: {text!r}")
    return int((d * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _parse_holdings(a: dict) -> list[SfHolding] | None:
    """SimpleFIN's optional holdings list (id, created, currency, cost_basis, description, market_value,
    purchase_price, shares, symbol). None when the account sends none. A holding that can't be read (no market value,
    or one that isn't a number) is skipped and logged; the account never is."""
    raw = a.get("holdings")
    if not isinstance(raw, list):
        return None
    out: list[SfHolding] = []
    for h in raw:
        if not isinstance(h, dict):
            continue
        try:
            value = _rounded_cents(h["market_value"])
            shares = h.get("shares")
            milli = 0 if shares in (None, "") else int((Decimal(str(shares).replace(",", "")) * 1000)
                                                       .to_integral_value(rounding=ROUND_HALF_UP))
            basis = h.get("cost_basis")
            basis_cents = None if basis in (None, "") else _rounded_cents(basis)
        except (KeyError, ValueError, TypeError, ArithmeticError):
            log.warning("SimpleFIN sent a holding Steward couldn't read on account %s", a.get("id", "?"))
            continue
        symbol = h.get("symbol")
        symbol = symbol.strip() if isinstance(symbol, str) and symbol.strip() else None
        out.append(SfHolding(symbol, str(h.get("description") or "").strip(), milli, value, basis_cents))
    return out


def _parse_account(a: dict) -> SfAccount:
    txns = []
    for t in a.get("transactions", []):
        if t.get("pending") or not t.get("posted"):
            continue
        try:
            txns.append(SfTxn(str(t["id"]), _household_date(int(t["posted"])), _cents(t["amount"]),
                              str(t.get("description", ""))))
        except (KeyError, ValueError, TypeError, ArithmeticError, OSError):
            raise ValueError(f"A transaction ({t.get('id', 'no id')}) on account "
                             f"{a.get('name', a.get('id', '?'))} could not be read.") from None
    try:
        return SfAccount(str(a["id"]), a["name"], a["conn_id"], a.get("currency", "USD"),
                         _cents(a["balance"]), _household_date(int(a["balance-date"])), txns, a,
                         holdings=_parse_holdings(a))
    except (KeyError, ValueError, TypeError, ArithmeticError, OSError):
        raise ValueError(f"Account {a.get('name', a.get('id', '?'))} could not be read.") from None


def fetch_accounts(http, access_url: str, start: datetime | None, pending: bool = False,
                   allowed_hosts=DEFAULT_HOSTS) -> AccountSet:
    if start is not None and start.tzinfo is None:
        raise ValueError("start must be timezone-aware")
    if not _allowed(access_url, allowed_hosts):
        raise SimplefinError("That SimpleFIN address isn't allowed.")
    base, user, pw = split_access_url(access_url)
    params: dict[str, str] = {"version": "2"}
    if start is not None:
        params["start-date"] = str(int(start.timestamp()))
    if pending:
        params["pending"] = "1"
    try:
        r = http.get(f"{base}/accounts", auth=(user, pw), params=params)
    except httpx2.HTTPError:
        raise SimplefinError(UNREACHABLE) from None
    if r.status_code == 402:
        raise SimplefinError("SimpleFIN says the subscription needs payment.")
    if r.status_code == 403:
        raise SimplefinError("SimpleFIN access was revoked. Link it again in Settings.")
    if r.status_code != 200:
        raise SimplefinError(f"SimpleFIN returned HTTP {r.status_code}.")
    try:
        body = r.json()
    except (ValueError, json.JSONDecodeError):
        body = None
    if not isinstance(body, dict):
        raise SimplefinError("SimpleFIN sent a reply that could not be read.")
    conns = [Connection(c["conn_id"], c["name"], c.get("org_id", "")) for c in body.get("connections", [])]
    errors = [SfError(e.get("code", "?"), e.get("msg", ""), e.get("conn_id"), e.get("account_id"))
              for e in body.get("errlist", [])]
    # Deprecated v1 shape: a plain list of strings, none tied to a connection.
    errors += [SfError("gen", e, None, None) for e in body.get("errors", []) if isinstance(e, str)]
    accounts: list[SfAccount] = []
    for a in body.get("accounts", []):
        try:
            accounts.append(_parse_account(a))
        except ValueError as e:
            errors.append(SfError("steward.parse", str(e), a.get("conn_id"), a.get("id")))
    return AccountSet(conns, accounts, errors)
