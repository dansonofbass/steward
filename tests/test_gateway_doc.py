"""docs/guides/gateway.md: the headings other docs link to, the models and their licenses, the pairing command and the
warning that comes with Claude Code. (tests/test_compose_files.py pins the compose commands the guide gives.)"""
from tests.public_docs import ROOT, headings, section

GUIDE = ROOT / "docs" / "guides" / "gateway.md"
H2 = ("What the gateway does", "What works without it", "On the same box, with compose",
      "On another machine on your tailnet", "The Claude API key", "Pairing", "Models and their licenses",
      "Reading PDFs", "Advanced: Claude Code")


def test_the_guide_has_both_placements_and_the_pointed_sections():
    found = headings(GUIDE)
    assert [text for _, level, text in found if level == 1] == ["Pair the gateway and Ask Claude"]
    have = [text for _, level, text in found if level == 2]
    assert [h for h in H2 if h not in have] == []
    assert [h for h in have if h in H2] == list(H2), "the sections are out of order"


def test_the_models_and_their_licenses_are_named():
    text = section(GUIDE, "## Models and their licenses")
    for needle in ("Qwen", "GLiNER", "Gemma Terms of Use", "https://ai.google.dev/gemma/terms",
                   "steward-gateway eval categorizer"):
        assert needle in text, needle
    assert text.count("Apache-2.0") >= 2


def test_pairing_shows_the_compose_command():
    text = section(GUIDE, "## Pairing")
    assert "docker compose exec gateway steward-gateway pair" in text
    assert "steward advisor pair" in text
    assert "[S10](../CLAIMS.md#s10)" in text


def test_claude_code_comes_with_its_warning():
    text = section(GUIDE, "## Advanced: Claude Code")
    assert "[S15](../CLAIMS.md#s15)" in text
    assert "mcp = true" in text and "off" in text.lower()
    assert "Anyone" in text or "anything that runs as you" in text.lower()


def test_the_tailnet_section_names_no_one_machine():
    text = section(GUIDE, "## On another machine on your tailnet")
    assert "/etc/steward-gateway" in text and "tag:" in text and "8430" in text
    assert "MagicDNS" in text or "100." in text
    for word in ("WSL", "Windows", "PowerShell"):
        assert word not in text, word
