"""Spec 10: never "her", "she", "elder", "senior" or "patient" about a parent; "elder-law attorney" names the attorney.
The whole of every Care file is scanned, code and copy alike, so identifiers follow the rule too."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web/src/screens/care"
FILES = sorted([*(ROOT / "src/steward/care").glob("*.py"), ROOT / "src/steward/advisor/tools/care.py",
                ROOT / "src/steward/api/care.py", ROOT / "src/steward/demo_care.py",
                *(p for p in WEB.glob("*.ts*") if not p.name.endswith(".test.tsx"))])
BANNED = re.compile(r"\b(her|hers|herself|she|elder|elders|elderly|senior|seniors|patient|patients)\b", re.IGNORECASE)


def test_the_files_are_there():
    assert {"costs.py", "medi_cal.py", "scenarios.py", "views.py", "Care.tsx", "copy.ts"} <= {f.name for f in FILES}


def test_no_word_the_spec_rules_out():
    for f in FILES:
        hits = sorted({m.group(0) for m in BANNED.finditer(f.read_text().replace("elder-law attorney", ""))})
        assert not hits, f"{f.relative_to(ROOT)}: {hits}"


def test_no_exclamation_marks_in_the_screen_copy():
    assert "!" not in (WEB / "copy.ts").read_text()
