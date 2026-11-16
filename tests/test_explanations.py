"""The explanation pages under docs/explanations/: what each one must cite, and the limits it must own up to."""
import re

from tests.public_docs import ROOT, section
from tests.test_claims import CITE, read_ledger

DIR = ROOT / "docs" / "explanations"
PRIVACY = DIR / "privacy.md"

PRIVACY_CITES = {"## What reaches Claude": {"P3", "P6"},
                 "## What never reaches Claude": {"P3", "P4", "P5", "P8", "P11", "P12", "P13"},
                 "## What stays on your machines": {"P1", "P2", "P9", "P10", "P14", "P15"}}
ASK_CITES = {"P4", "P6", "P7", "P14"}


def cited(text: str) -> set[str]:
    return {m[1] for m in CITE.finditer(text)}


def test_privacy_cites_its_claims_by_section():
    for heading, wanted in PRIVACY_CITES.items():
        missing = wanted - cited(section(PRIVACY, heading))
        assert not missing, f"{heading} doesn't cite {sorted(missing)}"


def test_privacy_names_the_limits():
    s = section(PRIVACY, "## What the checks can miss")
    assert "birth" in s and "4 or fewer digits" in s and "AB12CD34" in s


def test_privacy_links_claudes_terms():
    s = section(PRIVACY, "## Claude's own terms")
    assert re.search(r"\]\(https://[^)]*anthropic\.com[^)]*\)", s)


def test_privacy_says_the_sample_book_stays_home():
    s = section(PRIVACY, "## The Sample book")
    assert "S11" in cited(s)
    assert "made up" in s and "nothing from it reaches Claude" in s


def test_privacy_says_where_the_sent_log_is():
    text = PRIVACY.read_text(encoding="utf-8")
    assert "Settings › Chat" in text and "Everything sent so far" in text


def test_ask_walks_one_question_and_cites_its_claims():
    text = (DIR / "ask.md").read_text(encoding="utf-8")
    assert ASK_CITES <= cited(text)
    assert "privacy.md" in text
    assert len(re.findall(r"^\d+\. ", text, re.M)) >= 6, "Ask's page is a numbered walk through one question"


def test_architecture_keeps_the_strings_a_private_test_pins():
    text = (DIR / "architecture.md").read_text(encoding="utf-8")
    for needle in ("/api/b/<slug>/", "directory.db", "/invite?token=", "accept"):
        assert needle in text


def test_the_threat_model_cites_every_secure_row():
    """Every S row in docs/CLAIMS.md that isn't pending is cited in threat-model.md."""
    rows, _ = read_ledger(ROOT)
    secure = {r.id for r in rows.values() if r.id.startswith("S") and not r.pending}
    assert secure, "the ledger has no Secure rows"
    missing = secure - cited((DIR / "threat-model.md").read_text(encoding="utf-8"))
    assert not missing, f"threat-model.md doesn't cite {sorted(missing)}"


def test_the_threat_model_has_an_out_of_scope_section_that_security_md_links_to():
    assert section(DIR / "threat-model.md", "## Out of scope").strip()
