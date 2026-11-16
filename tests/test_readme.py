import re

from tests.public_docs import ROOT

README = ROOT / "README.md"
TAGLINE = "**Steward: secure, private, thoughtful. For you, and the people you look after.**"
PITCH = "Ask AI about your money without handing it your money."
OTHER_APPS = ("Monarch", "YNAB", "Rocket Money", "Simplifi", "Copilot Money", "Personal Finance in Claude")


def test_the_readme_opens_with_the_tagline_and_the_pitch():
    lines = README.read_text().splitlines()
    assert lines[0] == "# Steward" and TAGLINE in lines[:4] and PITCH in lines[:10]


def test_the_front_door_leads_to_the_quick_starts_and_the_index():
    text = README.read_text()
    assert all(p in text for p in ("docs/quickstart/demo.md", "docs/quickstart/install.md", "docs/README.md"))


def test_the_readme_shows_three_or_four_screenshots():
    assert 3 <= len(re.findall(r"docs/screenshots/[\w-]+\.png", README.read_text())) <= 4


def test_the_readme_says_what_it_isnt():
    text = README.read_text().lower()
    assert "not financial or tax advice" in text and "not affiliated with anthropic" in text
    assert "agpl-3.0-or-later" in text


def test_the_readme_names_no_other_money_app():
    assert [n for n in OTHER_APPS if n.lower() in README.read_text().lower()] == []
