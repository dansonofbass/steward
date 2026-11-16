"""The two quick starts and the docs index: short numbered steps, the demo's real logins, compose's own commands, and a
link to every public page."""
import re

import pytest

from tests.public_docs import ROOT, public_docs

DEMO, INSTALL, INDEX = (ROOT / "docs/quickstart/demo.md", ROOT / "docs/quickstart/install.md", ROOT / "docs/README.md")


@pytest.mark.parametrize("page", [DEMO, INSTALL])
def test_a_quick_start_is_numbered_steps_with_no_tables_and_an_end(page):
    lines = page.read_text().splitlines()
    assert sum(1 for line in lines if re.match(r"\d+\. ", line)) >= 3
    assert not any(line.startswith("|") for line in lines)
    assert "## What you have now" in lines


def test_the_demo_logins_are_the_demos():
    from steward.demo import DEMO_LOGINS
    text = DEMO.read_text()
    assert all(username in text and password in text for username, _email, _name, password in DEMO_LOGINS)


def test_the_demo_runs_the_demo_compose():
    text = DEMO.read_text()
    assert text.startswith("# Try the demo in 5 minutes") and "docker compose -f compose.demo.yml up" in text


def test_install_runs_the_compose_header_commands():
    """compose.yml's header lines 2-5 each hold a command, then two or more spaces, then a note."""
    header = (ROOT / "deploy/compose.yml").read_text().splitlines()[1:5]
    commands = [re.split(r"\s{2,}", line.lstrip("# ").strip())[0] for line in header]
    assert len(commands) == 4
    assert [c for c in commands if c not in INSTALL.read_text()] == []


def test_install_shows_its_key_moments_and_the_requirements():
    text = INSTALL.read_text()
    assert text.startswith("# Install for your household")
    assert all(f"screenshots/{n}.png" in text for n in ("signin", "first-run", "ready", "home"))
    assert all(s in text for s in ("x86_64", "Docker Engine 24", "Compose 2.24", "2 GB", "4 GB", "Podman"))


def test_the_demo_names_the_compose_floor():
    assert "Compose 2.24" in DEMO.read_text()


def test_the_index_links_every_public_doc_and_names_the_gpu_guide():
    text = INDEX.read_text()
    want = [p for p in public_docs() if p.parent != ROOT and p != INDEX]
    assert [str(p) for p in want if p.relative_to(INDEX.parent).as_posix() not in text] == []
    assert "Speed up the gateway with a GPU" in text
