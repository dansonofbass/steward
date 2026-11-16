"""The task guides under docs/guides/: each one is one task, and the few facts a wrong page would get dangerous are pinned."""
import pytest

from tests.public_docs import ROOT, headings, section

GUIDES = ("access", "email", "backups", "bank-data", "encryption-key", "upgrade", "move")


def guide(name: str):
    return ROOT / "docs" / "guides" / f"{name}.md"


@pytest.mark.parametrize("name", GUIDES)
def test_each_guide_is_one_task(name):
    found = headings(guide(name))
    assert found and found[0][0] == 1 and found[0][1] == 1, "a guide opens with its H1"
    assert sum(1 for _n, level, _t in found if level == 1) == 1


def test_the_address_comes_before_any_passkey():
    s = section(guide("access"), "## Passkeys and the address")
    assert "STEWARD_BASE_URL" in s and "before anyone registers a passkey" in s


def test_access_has_the_headings_the_code_points_at():
    names = {text for _n, level, text in headings(guide("access")) if level == 2}
    assert {"Tailscale", "Your own domain", "LAN only", "On this machine only", "Passkeys and the address"} <= names


def test_upgrading_backs_up_before_it_pulls():
    text = guide("upgrade").read_text()
    assert text.index("steward backup") < text.index("docker compose pull")
    assert "## Verify the images" in text


def test_restore_covers_the_check_and_the_hand_restore():
    text = guide("backups").read_text()
    assert "steward restore-check" in text and "steward-<slug>-" in text


def test_moving_keeps_the_key_and_the_address():
    text = guide("move").read_text()
    assert "steward.key" in text and "STEWARD_BASE_URL" in text
