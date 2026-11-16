"""The boundary's vocabularies repeat values from steward; this keeps them equal."""
import re
from pathlib import Path

from steward.api.facts import FILING_STATUSES, STATE_CODES
from steward.care import vocab as CV
from steward.db.models import CATEGORIES, FLAG_CHECKS, AccountType
from steward.engine.checklist import ChecklistInputs, savings_checklist
from steward.inventory import kinds as K
from steward.services.spending import LABELS
from steward_boundary import vocab as V


def test_vocab_matches_steward():
    assert V.ACCOUNT_TYPES == tuple(t.value for t in AccountType)
    assert V.CATEGORIES == CATEGORIES
    assert V.FLAG_CHECKS == FLAG_CHECKS
    assert V.FILING_STATUSES == FILING_STATUSES
    assert set(V.STATES) == STATE_CODES
    assert V.ITEM_KINDS == tuple(K.KIND_LABELS)
    assert V.INCOME_SOURCES == tuple(t[0] for t in K.INCOME_SOURCES)
    assert V.INSURANCE_TYPES == tuple(t[0] for t in K.INSURANCE_TYPES)
    assert V.FREQUENCIES == tuple(K.FREQUENCIES)
    assert V.TOTAL_GROUPS == tuple(k for k, _ in K.TOTALS)
    assert set(V.ITEM_TYPES) == {t[0] for types in K.TYPES_BY_KIND.values() for t in types}
    assert V.CARE_LEVELS == CV.LEVELS
    assert V.MEDI_CAL_STATUSES == CV.MEDI_CAL_STATUSES
    assert V.CARE_ROOMS == CV.ROOMS


def test_checklist_keys_match_the_engine():
    ci = ChecklistInputs(0, 0, None, None, None, False, None, False, None, (), frozenset(), None)
    assert V.CHECKLIST_ITEMS == tuple(i.key for i in savings_checklist(ci))


def test_every_account_type_has_a_tax_treatment_for_ask():
    from steward.advisor.tools.common import TAX
    assert set(TAX) == {t.value for t in AccountType}


def test_the_gateway_knows_every_college_level_the_engine_takes():
    from steward.engine.inputs import COST_LEVELS
    from steward_boundary import vocab
    assert vocab.COLLEGE_LEVELS == COST_LEVELS


ROOT = Path(__file__).resolve().parents[2]


def test_category_words_match_spending_and_the_web():
    """Ask about this P14: the about line's category words are the ones Steward shows."""
    assert {k: V.CATEGORY_WORDS[k] for k in LABELS} == LABELS
    block = (ROOT / "web/src/lib/categories.ts").read_text().split("export const CATEGORY_LABELS", 1)[1].split("};", 1)[0]
    assert dict(re.findall(r"^\s+(\w+): '([^']+)',$", block, re.M)) == V.CATEGORY_WORDS


def test_the_chips_check_words_are_the_watching_labels():
    """Ask about this, Engineering choice 5: the panel's chip words for flag checks; "Unusual for {name}" reads
    "Unusual", since the chip names nobody."""
    from steward.watch.vocab import CHECK_LABELS
    block = (ROOT / "web/src/screens/chat/copy.ts").read_text().split("export const CHECK_WORDS", 1)[1].split("};", 1)[0]
    assert dict(re.findall(r"(\w+): '([^']+)'", block)) == {k: v.replace(" for {name}", "") for k, v in CHECK_LABELS.items()}
