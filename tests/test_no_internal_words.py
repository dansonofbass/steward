"""Text a person reads names people by their label and the app by the words the app uses (release gate 16h: PRIV-1,
TRI-1, THO-15, THO-16).

- The owner's initials are not a personal term (the ruling is written beside the term list, tests/personal_strings.py),
  but no install should show them: Person 1 is the household's first person, named by their label ({person1}).
- The person keys (jr, spouse) are storage keys. A message never lists them.
- "The vault" is the code's word for the server, and "the household network" is wrong for a Tailscale install. The
  app says "your home server".

Docstrings and comments are not scanned: they are for whoever reads the code."""
import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "steward"
WEB = REPO / "web" / "src"

INITIALS = re.compile(r"\bJR\b")
# The lowercase key as a word in prose: not a quoted SQL value ('jr'), a dotted fact key (jr.dob) or a field (jr_age).
KEY_IN_PROSE = re.compile(r"(?<!['\"])\bjr\b(?![._\]'\"])")
INTERNAL_WORDS = re.compile(r"\bvaults?\b|household network", re.IGNORECASE)
# Operator text: the command line and the start-up guard speak to whoever runs the server, not to the household.
OPERATOR_FILES = {"cli.py", "auth/demo_guard.py"}


def shown_strings(path: Path) -> list[tuple[int, str]]:
    """Every string literal in a Python file that isn't a docstring or a bare string statement, f-string parts too."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bare = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in bare]


def python_hits(pattern: re.Pattern, *, prose_only=False, skip=frozenset()) -> list[str]:
    hits = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in skip:
            continue
        hits += [f"{rel}:{n}: {s[:80]!r}" for n, s in shown_strings(path)
                 if (not prose_only or " " in s) and pattern.search(s)]
    return hits


COMMENT = re.compile(r"/\*.*?\*/|(?<![:\w'\"])//[^\n]*", re.S)


def web_hits(pattern: re.Pattern) -> list[str]:
    """Each web source line (tests and fixtures aside) that holds the pattern once comments are taken out."""
    hits = []
    for path in sorted([*WEB.rglob("*.ts"), *WEB.rglob("*.tsx")]):
        name = path.name
        if ".test." in name or name.startswith("fixtures") or name.endswith(".d.ts"):
            continue
        code = COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), path.read_text(encoding="utf-8"))
        hits += [f"{path.relative_to(REPO).as_posix()}:{n}" for n, line in enumerate(code.splitlines(), 1)
                 if pattern.search(line)]
    return hits


def test_no_string_steward_shows_holds_the_owners_initials():
    assert python_hits(INITIALS) == []


def test_no_message_lists_the_internal_person_keys():
    assert python_hits(KEY_IN_PROSE, prose_only=True) == []


def test_no_string_steward_shows_says_vault_or_household_network():
    assert python_hits(INTERNAL_WORDS, skip=OPERATOR_FILES) == []


def test_no_web_string_says_vault_or_household_network():
    assert web_hits(INTERNAL_WORDS) == []


def test_the_scans_see_what_they_look_for(tmp_path):
    """The scans read f-string parts and skip docstrings, and the web scan skips comments but not strings."""
    py = tmp_path / "planted.py"
    py.write_text('"""JR, a docstring."""\nlabel = "x"\nraise_it = f"{label} JR"\nmsg = "Say: jr or spouse."\n'
                  'sql = "person IN (\'jr\', \'spouse\')"\nkey = "jr.dob"\n', encoding="utf-8")
    found = shown_strings(py)
    assert [n for n, s in found if INITIALS.search(s)] == [3]
    assert [n for n, s in found if " " in s and KEY_IN_PROSE.search(s)] == [4]
    ts = 'const URL = "https://x.test/a"; // the vault\n/* the vault */\nexport const M = "reach the vault";\n'
    code = COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), ts)
    assert [n for n, line in enumerate(code.splitlines(), 1) if INTERNAL_WORDS.search(line)] == [3]
    assert "https://x.test/a" in code
