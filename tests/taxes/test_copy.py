"""Copy rules for part 5 (spec 10; plan Global Constraints): no words about a parent the spec rules out, no exclamation
marks in copy, and the "never pays or files" line in place."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = [*sorted((ROOT / "src/steward/taxes").glob("*.py")), ROOT / "src/steward/engine/tax/estimates.py",
         ROOT / "src/steward/engine/decisions.py", ROOT / "src/steward/api/taxes.py",
         *sorted((ROOT / "web/src/screens/taxes").glob("*.ts*")), ROOT / "web/src/screens/home/forYouRows.ts",
         ROOT / "web/src/screens/plan/PlanTabs.tsx"]
BANNED = re.compile(r"\b(her|she|elder|senior|patient)\b", re.IGNORECASE)


def test_no_banned_words():
    for f in FILES:
        for n, line in enumerate(f.read_text().splitlines(), 1):
            assert not BANNED.search(line), f"{f.relative_to(ROOT)}:{n}: {line.strip()}"


def test_no_exclamation_marks_in_copy():
    copy = (ROOT / "web/src/screens/taxes/copy.ts").read_text()
    assert "!" not in copy
    for f in sorted((ROOT / "src/steward/taxes").glob("*.py")):
        for s in re.findall(r'"([^"\n]*)"', f.read_text()):
            assert not s.rstrip().endswith("!"), f"{f.name}: {s}"


def test_steward_never_pays_or_files():
    from steward.taxes.quarterly import NEVER
    assert NEVER == "Steward never pays or files anything."
