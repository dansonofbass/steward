"""P44: every category has a label on the server, word for word the web's (web/src/lib/categories.ts)."""
import re
from pathlib import Path

from steward.db.models import CATEGORIES
from steward.services.category_labels import CATEGORY_LABELS, label

WEB = Path(__file__).resolve().parents[1] / "web" / "src" / "lib" / "categories.ts"


def test_every_category_has_a_label():
    assert set(CATEGORY_LABELS) == set(CATEGORIES)


def test_the_labels_match_the_web():
    text = WEB.read_text()
    block = text[text.index("export const CATEGORY_LABELS"):]
    block = block[:block.index("};")]
    assert dict(re.findall(r"(\w+): '([^']*)'", block)) == CATEGORY_LABELS


def test_an_unknown_key_reads_as_itself():
    assert (label("dining"), label("mystery")) == ("Eating out", "mystery")
