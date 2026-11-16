"""The real GLiNER-PII and Presidio against the PII and keep sets (spec 11.2, 11.3).
Run on the gateway by the gateway's deploy script, or anywhere with the models group:
uv sync --group models && uv run pytest -q -m models tests/gateway/test_models_eval.py
About 2 minutes on CPU. Known identifiers are the NAS exact pass's job (tests/advisor/test_pii_sets.py); here every
identifier the book doesn't know must be gone, with no exceptions on the committed set.
The GPU budget is tests/perf/test_redaction_gpu_budgets.py."""
import pytest

from steward_boundary.normal import view
from steward_boundary.spans import apply
from steward_boundary.text import dob_edits, outgoing_text, plain
from steward_gateway.redact import load_real_detectors, redact
from tests.advisor.identities import leaks
from tests.advisor.pii_set.make_sets import HERE, read_jsonl

pytestmark = [pytest.mark.models, pytest.mark.timeout(900)]     # minutes of real model work (about 2 on CPU)
PII = read_jsonl(HERE / "questions.jsonl")
KEEP = read_jsonl(HERE / "keep.jsonl")


def production_text(text: str) -> str:
    """What reaches the models in production: the date-of-birth replacement and the outgoing question rule have
    already run on the NAS (preflight ruling 7). The question rule includes the spelled-digits rule (ruling 28), which
    moved into steward_boundary on 2026-10-24, so the eval sees what the NAS sends."""
    v = view(text)
    return outgoing_text(apply(v.plain, dob_edits(v))[0])


@pytest.fixture(scope="module")
def detectors():
    found, problem = load_real_detectors()
    assert found, problem
    return found


def test_every_identifier_the_book_doesnt_know_is_removed(detectors):
    misses = []
    for r in PII:
        for s in (s for s in r["spans"] if not s["known"]):
            out = outgoing_text(redact(production_text(plain(r["text"])), detectors).text)
            if leaks(out, s["kind"], s["value"]):
                misses.append((r["id"], s["kind"], out))
    assert misses == [], f"{len(misses)} misses; fix with a recognizer or rule, then add the case to the set"


def test_no_more_than_3_percent_of_the_keep_set_changes(detectors):
    changed = [r["text"] for r in KEEP if redact(production_text(r["text"]), detectors).text != production_text(r["text"])]
    assert len(changed) <= 6, changed


def test_the_second_pass_doesnt_stop_a_question_the_first_pass_cleaned(detectors):
    """Check 3 re-reads the redacted question with the gateway's own brackets issued, and the per-turn context: a
    clean redaction must not stop the turn (found 2026-10-24: "my brother [name]" stopped 29 PII questions)."""
    from datetime import date, timedelta

    from steward_boundary.aliases import BRACKETS
    from steward_gateway.checks import Part, Stopped, check_parts
    from steward_gateway.prompt import context_text
    stopped = []
    for r in KEEP + PII:
        red = redact(production_text(plain(r["text"])), detectors)
        issued = {e.label for e in red.edits if e.label in BRACKETS}
        try:
            check_parts([Part("question", {"text": red.text})], detectors=detectors, salt="1" * 32,
                        hashes=frozenset(), issued=issued)
        except Stopped:
            stopped.append(r["id"])
    for i in range(0, 366, 7):
        for kind, asker in (("household", "Person 1"), ("parent", "Person 2")):
            ctx = context_text({"today": (date(2026, 1, 1) + timedelta(days=i)).isoformat(), "book_kind": kind,
                                "asker": asker})
            try:
                check_parts([Part("system", {"text": ctx})], detectors=detectors, salt="1" * 32, hashes=frozenset(),
                            issued={asker})
            except Stopped:
                stopped.append(ctx)
    assert stopped == []
