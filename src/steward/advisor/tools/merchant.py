"""merchant_detail (spec 4.4): transactions with their store or payee names, for a manager to approve; approved rows go
with the conversation's later questions. Names are put in the canonical normal form, masked to 4 digits by the strict stored-text path, and then put
through the exact pass with every identifier the book knows except its payee and institution names, which are what was
asked for (plan B ruling 4): a member's name in a Zelle line becomes [name]. The rows this returns are exactly what the
card shows and what is sent."""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import date

from sqlalchemy import select

from steward.advisor.aliases import Aliases, payee_label
from steward.advisor.identifiers import Identifier, load_identifiers
from steward.advisor.redact import APPROVABLE_KINDS, Refused, exact_redact, survives
from steward.advisor.tools import Ref, ToolEnv, ToolError, register
from steward.advisor.tools.common import clauses
from steward.db.models import Account, AdvisorAlias, Transaction
from steward.inventory.present import clean_account
from steward.watch.payees import payee
from steward_boundary import tools as T
from steward_boundary import vocab as V
from steward_boundary.aliases import number_of
from steward_boundary.normal import plain
from steward_boundary.text import is_stored_safe, stored_text

BAD_INPUT = "That input wasn't understood."
TOO_LONG = "That period is too long."
BRACKET = {"name": "[name]", "account": "[institution]", "email": "[email]", "phone": "[phone]",
           "address": "[address]", "number": "[account number]", "dob": "[date of birth]"}


def _day(value: object) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ToolError(BAD_INPUT) from None


def store_identifiers(env: ToolEnv) -> tuple[Identifier, ...]:
    aliases = Aliases(env.db, env.book, env.people, save=False)
    found = load_identifiers(env.db, env.book, env.people, env.directory, aliases, env.today)
    return tuple(replace(i, replacement=BRACKET[i.kind]) for i in found if i.kind not in APPROVABLE_KINDS)


STORE_CHARS = 60           # what a row shows and sends (plan B ruling 2)
RAW_CHARS = 400            # bank text read before cleaning; anything past it can't reach the 60 kept


def _cut(text: str) -> str:
    """At most 60 characters, never ending inside a word or a bracket token: "Samantha" is never left as "Sama", nor
    "[name]" as "[na"."""
    text = text.strip()
    if len(text) <= STORE_CHARS:
        return text
    cut = text[:STORE_CHARS]
    if text[STORE_CHARS].isalnum() or text[STORE_CHARS] in "]_":
        cut = re.sub(r"[\w\[\]•]+$", "", cut)                      # a word or token the cut went through
    if cut.rfind("[") > cut.rfind("]"):
        cut = cut[:cut.rfind("[")]
    return cut.strip()


def clean_store(name: str, identifiers: tuple[Identifier, ...]) -> str:
    """A store or payee name safe to show and send, or "[payee]" (Task 6.5 order). The canonical normaliser comes
    first (so look-alike letters, zero-width characters and full-width digits can't hide a name or a number), then
    mask_numbers (clean_account: at most 4 digits), then the strict stored-text path, then the exact pass over the
    whole name with its survivors check, and only then the 60-character cut, which can't split a known name or a
    token. What is left is checked again: no known identifier may survive and it must pass the stored-text rule."""
    text = stored_text(clean_account(plain(name or "")[:RAW_CHARS])).strip()
    if not text:
        return "[payee]"
    try:
        out, _ = exact_redact(text, identifiers)
    except Refused:
        return "[payee]"
    out = _cut(out)
    if not out or survives(out, identifiers) or not is_stored_safe(out):
        return "[payee]"
    return out


@register(T.MERCHANT)
def merchant_detail(inp: dict, env: ToolEnv) -> dict:
    start, end = _day(inp["start"]), _day(inp["end"])
    if end < start:
        raise ToolError(BAD_INPUT)
    if (end - start).days + 1 > T.MERCHANT_DAYS:
        raise ToolError(TOO_LONG)
    wanted = inp.get("payees") or []
    if any(not isinstance(p, str) or (number_of(p) or ("",))[0] != "Payee" for p in wanted):
        raise ToolError(BAD_INPUT)
    keys = {r.target: r.alias for r in env.db.scalars(
        select(AdvisorAlias).where(AdvisorAlias.kind == "payee", AdvisorAlias.alias.in_(wanted)))} if wanted else {}
    idents = store_identifiers(env)
    q = (select(Transaction.posted_at, Transaction.amount_cents, Transaction.category, Transaction.raw_description,
                Transaction.merchant, Transaction.account_id)
         .join(Account, Account.id == Transaction.account_id)
         .where(*clauses(env.book.kind), Transaction.posted_at >= start, Transaction.posted_at <= end)
         .order_by(Transaction.posted_at.desc(), Transaction.id.desc()))
    if inp.get("category"):
        q = q.where(Transaction.category == inp["category"])
    rows: list[dict] = []
    more = False
    if not wanted or keys:
        for posted, cents, category, raw, merchant, account_id in env.db.execute(q):
            p = payee(raw, merchant)
            if wanted and p.key not in keys:
                continue
            if len(rows) == T.MERCHANT_ROWS:
                more = True
                break
            rows.append({"date": posted.isoformat(), "amount_cents": cents,
                         "category": category if category in V.CATEGORIES else "uncategorized",
                         "merchant": clean_store(p.name or merchant or "", idents),
                         "account": Ref("account", account_id)})
    names = [{"payee": alias, "name": clean_store(payee_label(key), idents)}
             for key, alias in sorted(keys.items(), key=lambda kv: number_of(kv[1]) or ("", 0))]
    return {"rows": rows, "payees": names, "more": more}
