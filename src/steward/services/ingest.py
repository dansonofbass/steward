from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.orm import Session

from steward.business.rules import RuleSet
from steward.business.tagging import is_business_account
from steward.db.models import Account, AccountType, CategorySource, ImportBatch, Transaction
from steward.services.catchup import begin_wave
from steward.services.categorize import INVESTMENT_TYPES, NO_MATCH, Suggestion, model_suggestions, rule_suggestion
from steward.services.categorizer_client import ModelClient, NullModelClient
from steward.services.category_rules import example_rules
from steward.services.importers.base import ParsedRow
from steward.services.labels import apply_labels
from steward.services.reimburse_rules import apply_rules
from steward.services.transfers import pair_transfers


def rule_suggestions(db: Session, rows: list[ParsedRow], account_type: AccountType | None = None) -> list[Suggestion | None]:
    """Steps 1 and 2 for each row: the household's rules, then the built-ins; None where neither matched. Every row of an
    investment account gets an answer here, so none goes to the model."""
    return [rule_suggestion(db, r.raw_description, account_type, r.amount_cents) for r in rows]


def model_fill(model: ModelClient | None, rows: list[ParsedRow], found: list[Suggestion | None],
               examples: Sequence[tuple[str, str]] = ()) -> list[Suggestion]:
    """Step 3 for the rows no rule matched, with the household's examples (read before the caller's transaction
    ended). The model is a network call that can take half a minute, so call this with no transaction open: a book's
    write lock held meanwhile stalls every other request on the book."""
    out: list[Suggestion] = [s or NO_MATCH for s in found]
    misses = [i for i, s in enumerate(found) if s is None]
    for i, s in zip(misses, model_suggestions(model, [(rows[i].raw_description, rows[i].amount_cents) for i in misses],
                                              examples=examples)):
        out[i] = s or NO_MATCH
    return out


def teaching_examples(db: Session, model: ModelClient | None) -> list[tuple[str, str]]:
    """The household's examples for the model, or none (and no scan of every description) when no real model will see
    them: no model, the null one, or a gateway whose health doesn't list `examples` (HttpModelClient sends none then)."""
    if model is None or isinstance(model, NullModelClient) or "examples" not in getattr(model, "features", ()):
        return []
    return example_rules(db)


def suggest_rows(db: Session, rows: list[ParsedRow], model: ModelClient | None,
                 account_type: AccountType | None = None) -> list[Suggestion]:
    """Rules first, then the model for the rest: what ingest_rows does for itself when given no suggestions."""
    return model_fill(model, rows, rule_suggestions(db, rows, account_type), teaching_examples(db, model))


def ingest_rows(db: Session, account: Account, rows: list[ParsedRow], *, batch: ImportBatch | None,
                now: datetime, model: ModelClient | None, household: bool = True,
                suggestions: list[Suggestion] | None = None, feed_id: int | None = None) -> list[Transaction]:
    """Insert rows, categorize them, tag business by the household's rules (business plan ruling 3), and pair
    transfers; the one path import and sync share. Import and sync pass `suggestions` they computed with suggest_rows
    before taking the write lock; without them the model is asked here, inside the caller's transaction. `feed_id` is
    the SimpleFIN feed the rows came through (same-account spec); a file's rows have none."""
    acct_business = is_business_account(account, household)
    rules = RuleSet.load(db)
    begin_wave(db, now)
    found = suggestions if suggestions is not None else suggest_rows(db, rows, model, account.type)
    new: list[Transaction] = []
    for r, s in zip(rows, found):
        pct, source, line = rules.business_for(account.id, r.raw_description, r.amount_cents,
                                               legacy=s.is_business, owner_business=acct_business)
        t = Transaction(
            account_id=account.id, posted_at=r.posted_at, amount_cents=r.amount_cents,
            raw_description=r.raw_description, external_id=r.external_id,
            merchant=s.merchant, category=s.category, category_source=s.source,
            is_business=pct == 100, business_pct=pct, business_source=source, business_line=line,
            business_hint=s.business_hint if r.amount_cents < 0 else None,
            is_transfer=(s.category == "transfer"), imported_at=now,
            guess_category=s.guess, guess_pct=s.guess_pct, model_asked_at=now if s.asked else None,
            import_batch_id=batch.id if batch else None,
            feed_id=feed_id,
            statement_page=r.page,
        )
        if t.is_transfer:
            t.category_source = CategorySource.rule  # transfer rows are always rule-sourced
        db.add(t)
        new.append(t)
    db.flush()
    pair_transfers(db, [t.id for t in new])
    db.flush()
    if household and account.type not in INVESTMENT_TYPES:
        apply_labels(db, new, now)     # polish round P37: a rule's name and note reach the rows it matches
    if household:
        apply_rules(db, new)       # reimbursable spec: "always reimbursable" rules, and a repayment's payer
    return new
