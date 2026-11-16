"""The privacy docs say what the checks do (0.1.0 release gate, fix PR 16d). Each test runs the check a finding was
about, shows what it lets through, and then requires the docs to say so. The phrases the gate found false are kept out
of the docs and the in-app text by tests/test_doc_words.py; this file holds the cases that need the code beside them."""
import re

from steward.advisor.identifiers import PAYEE_DAYS, Identifier, _generic
from steward.advisor.redact import exact_redact
from steward.advisor import state
from steward_gateway.redact import names_nobody
from tests.public_docs import ROOT, flat, ledger_cells, section

PRIVACY = ROOT / "docs/explanations/privacy.md"
MISSES = "## What the checks can miss"


def misses() -> str:
    return flat(section(PRIVACY, MISSES))


def test_names_the_gateway_drops_on_purpose_are_listed_as_misses():
    """PRIV-3, part 2: a model hit whose every word is a state, a month or a money word is dropped by design, so the
    name goes as typed even when the model finds it. The model also looks only for people, street addresses and dates
    of birth, and it can miss a name outright."""
    for name in ("Virginia Roth", "Dakota Steward", "August"):
        assert names_nobody(name, "[name]"), name
    said = misses()
    assert "virginia roth" in said
    assert "a full name the book doesn't know" in said
    assert "employers, schools, towns" in said


def test_what_the_exact_pass_doesnt_match_is_listed_as_a_miss():
    """PRIV-4: the exact pass matches a name part alone only at 3 letters, drops a name made only of generic words,
    and matches a long address only on 5 tokens in a row. The docs say what it matches and list these gaps."""
    li = Identifier("Li Wei", "name", "Person 2", name=True)
    asked = "How much did Li spend on groceries?"
    assert exact_redact(asked, [li])[0] == asked
    home = Identifier("1234 North Elm Street Apt 5 Springfield IL 62704", "address", "[address]")
    asked = "We live at 1234 North Elm Street, can we refinance?"
    assert exact_redact(asked, [home])[0] == asked
    assert _generic("August")                       # load_identifiers drops it, so a child called August isn't matched
    said = misses()
    assert "a two-letter name" in said
    assert "without its unit, city or zip" in said
    assert "august" in said
    matched = flat(section(PRIVACY, "## What Steward replaces"))
    assert "3 letters or more" in matched and f"{PAYEE_DAYS} days" in matched


def test_the_docs_list_of_what_is_sent_matches_the_disclosure():
    """PRIV-8: the docs said Claude sees amounts, dates, categories and aliases; the tools also send ages, the state
    and tax facts, which the in-app disclosure already listed. Both now draw on one list."""
    sent = state.SENT_TO_CLAUDE
    joined = ", ".join(sent[:-1]) + " and " + sent[-1]
    assert joined in state.DISCLOSURE
    privacy = flat(PRIVACY.read_text(encoding="utf-8"))
    readme = flat(section(ROOT / "README.md", "### Private"))
    for kind in sent:
        assert kind in privacy, kind
        assert kind in readme, kind
    assert "an age is sent where a date of birth isn't" in privacy


def chat_copy(name: str) -> str:
    """One single-line constant of web/src/screens/chat/copy.ts."""
    text = (ROOT / "web/src/screens/chat/copy.ts").read_text(encoding="utf-8")
    m = re.search(rf"^export const {name} = (['\"])(.*)\1;$", text, re.M)
    assert m, name
    return m.group(2)


def test_the_in_app_privacy_lines_name_the_approved_rows_and_the_miss():
    """PRIV-2 and PRIV-3 in the app (TRI-2, the 16d re-check). A payee in rows a manager approves can be a person and
    goes to Claude (the approved payment-app payee test in tests/gateway/test_checks.py), and the gateway's model can
    miss a name. The disclosure shows once per person per book, so the Ask lede and the Settings › Chat lede, which stay
    on screen, each say both, as the disclosure does."""
    lines = {"LEDE": chat_copy("LEDE"), "SETTINGS_LEDE": chat_copy("SETTINGS_LEDE"), "DISCLOSURE": state.DISCLOSURE}
    for name, line in lines.items():
        said = flat(line)
        assert "a manager approves" in said, name
        assert "can miss one" in said, name
    assert "a payee can be a person" in flat(lines["SETTINGS_LEDE"])


def test_claude_codes_own_typing_is_said_to_go_around_steward():
    """PRIV-12: Steward checks what its tools return to Claude Code; what a person types there goes to Anthropic
    without passing through Steward."""
    guide = flat(section(ROOT / "docs/guides/gateway.md", "## Advanced: Claude Code"))
    assert "what you type into claude code doesn't pass through steward" in guide
    assert "claude code" in misses()
    # Settings › Chat's note says the same, and that the gateway's check on a lookup can miss a name (PRIV-3).
    note = flat(chat_copy("CC_NOTE"))
    assert "what you type into claude code doesn't pass through steward" in note
    assert "can miss one" in note


def test_p7_promises_every_part_of_your_data_not_everything():
    """PRIV-10: the request also carries the gateway's fixed instructions, its settings and Claude's own earlier
    replies, which aren't household data and aren't logged as text."""
    for text in (ledger_cells("P7")[1], section(ROOT / "README.md", "### Private"),
                 PRIVACY.read_text(encoding="utf-8")):
        assert "every part of your data that was sent" in flat(text)
