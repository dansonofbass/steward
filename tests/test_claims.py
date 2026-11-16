"""docs/CLAIMS.md, the claims ledger (spec 2026-11-05, section 3). Every claim the docs make has a row, every row's
proof exists, every bullet under the README's tagline section carries an ID, and every proven row is cited. Pending
rows are allowed until the release gate: `uv run pytest tests/test_claims.py --release` fails on any. CI doesn't pass
--release. A doc cites a pending row as planned, its link followed by `(planned)`, and the line itself says "planned"
or "before 0.1.0" in words."""
import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.public_docs import public_docs

ROOT = Path(__file__).resolve().parents[1]
TAGLINE = "## Secure, Private, Thoughtful"
PILLARS = {"S": "Secure", "P": "Private", "T": "Thoughtful"}
KINDS = {"test", "file", "review"}
STATUS = re.compile(r"(proven|pending \(PR \d+\))(, internal)?")
ROW_ID = re.compile(r'<a id="([a-z]\d+)"></a>([A-Z]\d+)')
PROOF = re.compile(r"`([^`]+)`")
CITE = re.compile(r"\[([A-Z]\d+)\]\(([^)#\s]*CLAIMS\.md)#([a-z0-9]+)\)")
TITLE = re.compile(r"""\b(?:test|it|describe)(?:\.\w+)*\(\s*(['"`])(.*?)\1""")
BULLET = re.compile(r"\s*[-*] ")
PLANNED = " (planned)"
SAYS_PLANNED = re.compile(r"\bplanned\b|\bbefore 0\.1\.0\b", re.IGNORECASE)


def says_planned(text: str, at: int) -> bool:
    """The words on the line before the link say "planned" or "before 0.1.0"; an earlier link's suffix doesn't count."""
    return bool(SAYS_PLANNED.search(text[text.rfind("\n", 0, at) + 1:at].replace(PLANNED, "")))


@dataclass
class Row:
    id: str
    line: int
    pillar: str
    proofs: list[str]
    kind: str
    status: str

    @property
    def pending(self) -> bool:
        return self.status.startswith("pending")

    @property
    def internal(self) -> bool:
        return self.status.endswith(", internal")


def citing_docs(root: Path) -> list[Path]:
    """The public docs (tests/public_docs.py) whose claims cite the ledger: all of them but the ledger itself."""
    ledger = (root / "docs" / "CLAIMS.md").resolve()
    return [p for p in public_docs(root) if p.resolve() != ledger]


def read_ledger(root: Path) -> tuple[dict[str, Row], list[str]]:
    ledger = root / "docs" / "CLAIMS.md"
    if not ledger.is_file():
        return {}, ["docs/CLAIMS.md is missing"]
    rows, found = {}, []
    for n, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("| <a id="):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 6:
            found.append(f"CLAIMS.md:{n}: {len(cells)} cells, not 6 (ID, claim, pillar, proof, kind, status)")
            continue
        m = ROW_ID.fullmatch(cells[0])
        if not m or m[1] != m[2].lower():
            found.append(f'CLAIMS.md:{n}: the ID cell is <a id="p3"></a>P3, the anchor the ID in lower case')
            continue
        if m[2] in rows:
            found.append(f"CLAIMS.md:{n}: {m[2]} is listed twice")
            continue
        rows[m[2]] = Row(m[2], n, cells[2], PROOF.findall(cells[3]), cells[4], cells[5])
    return rows, found


def proof_problem(root: Path, proof: str) -> str | None:
    path, _, name = proof.partition("::")
    file = root / path
    if not file.is_file():
        return f"{path} doesn't exist"
    if not name or name == "*":
        return None
    text = file.read_text(encoding="utf-8")
    if file.suffix == ".py":
        defs = {d.name for d in ast.walk(ast.parse(text))
                if isinstance(d, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        return None if all(part in defs for part in name.split("::")) else f"{path} has no {name}"
    return None if name in {m[2] for m in TITLE.finditer(text)} else f"{path} has no test titled {name!r}"


def tagline_problems(root: Path) -> list[str]:
    readme = root / "README.md"
    lines = readme.read_text(encoding="utf-8").splitlines() if readme.is_file() else []
    if TAGLINE not in lines:
        return [f"README.md has no '{TAGLINE}' section"]
    start = lines.index(TAGLINE) + 1
    bullets, current = [], None
    for n, line in enumerate(lines[start:], start + 1):
        if line.startswith("## "):
            break
        if BULLET.match(line):
            current = [n, line]
            bullets.append(current)
        elif current and line.startswith(" ") and line.strip():
            current[1] += " " + line.strip()           # a bullet wrapped onto the next line
        else:
            current = None
    return [f"README.md:{n}: a bullet in '{TAGLINE}' with no claim ID" for n, text in bullets if not CITE.search(text)]


def problems(root: Path) -> list[str]:
    rows, found = read_ledger(root)
    for r in rows.values():
        if PILLARS.get(r.id[0]) != r.pillar:
            found.append(f"{r.id}: pillar {r.pillar!r}, but {r.id[0]} IDs are {PILLARS.get(r.id[0], 'unknown')}")
        if r.kind not in KINDS:
            found.append(f"{r.id}: kind {r.kind!r} isn't test, file or review")
        if not STATUS.fullmatch(r.status):
            found.append(f"{r.id}: status {r.status!r} isn't 'proven' or 'pending (PR n)' "
                         "(then ', internal' if no doc cites it)")
        if not r.proofs:
            found.append(f"{r.id}: no proof in backticks")
        if not r.pending:
            found += [f"{r.id}: {p}" for proof in r.proofs if (p := proof_problem(root, proof))]
    ledger, cited = (root / "docs" / "CLAIMS.md").resolve(), set()
    for doc in citing_docs(root):
        rel = doc.relative_to(root).as_posix()
        text = doc.read_text(encoding="utf-8")
        for m in CITE.finditer(text):
            rid, link, anchor = m.groups()
            cited.add(rid)
            if rid not in rows:
                found.append(f"{rel} cites {rid}, which has no row in docs/CLAIMS.md")
            else:
                planned = text[m.end():m.end() + len(PLANNED)] == PLANNED
                if rows[rid].pending and not planned:
                    found.append(f"{rel} cites {rid}, which is pending: say it as planned and follow the link with '(planned)'")
                elif rows[rid].pending and not says_planned(text, m.start()):
                    found.append(f"{rel} cites {rid}, which is pending: the line must say 'planned' or 'before 0.1.0' "
                                 "in words, not state it as true")
                elif planned and not rows[rid].pending:
                    found.append(f"{rel}: {rid} is proven now: drop '(planned)' and say it plainly")
            if (doc.parent / link).resolve() != ledger:
                found.append(f"{rel}: [{rid}]({link}#{anchor}) doesn't lead to docs/CLAIMS.md")
            if anchor != rid.lower():
                found.append(f"{rel}: [{rid}] links to #{anchor}, not #{rid.lower()}")
    found += tagline_problems(root)
    found += [f"{r.id}: no doc cites it; cite it, or end its status with ', internal'"
              for r in rows.values() if r.id not in cited and not r.pending and not r.internal]
    return found


def pending(root: Path) -> list[str]:
    return [r.id for r in read_ledger(root)[0].values() if r.pending]


def test_the_ledger_and_the_docs_agree():
    assert problems(ROOT) == []


MODEL_EVAL = "tests/gateway/test_models_eval.py"
EVAL_RUN = re.compile(r"ran `tests/gateway/test_models_eval\.py` on (\d{4}-\d{2}-\d{2}) at `([0-9a-f]{7,40})`: (\d+) passed")


def test_p4_and_p11_cite_the_real_model_eval_and_record_its_run():
    """Gate finding PRIV-3: the other proofs run stand-in detectors, so the rows that rest on the gateway's model cite
    the eval of the real one, which the default run leaves out, and the ledger records when it last ran."""
    rows, _ = read_ledger(ROOT)
    assert [rid for rid in ("P4", "P11") if MODEL_EVAL not in rows[rid].proofs] == []
    run = EVAL_RUN.search((ROOT / "docs" / "CLAIMS.md").read_text(encoding="utf-8"))
    assert run and int(run[3]) > 0, "record the eval's run: ran `tests/gateway/test_models_eval.py` on DATE at `SHA`: N passed"


def test_s5_cites_the_test_that_proves_the_lockout():
    """Gate finding SEC-8: tests/test_limits.py is about contribution limits and tests/test_rate_limits.py about the
    per-device doors, so neither fails when the lockout is deleted."""
    proofs = read_ledger(ROOT)[0]["S5"].proofs
    assert "tests/test_auth_api.py::test_bad_password_and_lockout_messages" in proofs
    assert "tests/test_limits.py" not in proofs


def test_no_claim_is_pending_at_the_release_gate(request):
    if not request.config.getoption("--release"):
        pytest.skip("the release gate runs this: uv run pytest tests/test_claims.py --release")
    assert pending(ROOT) == [], "prove these, or take them out of the docs, before the release"


# The check itself, on small made-up trees.

HEADER = "# Claims\n\n| ID | Claim | Pillar | Proof | Kind | Status |\n|---|---|---|---|---|---|\n"
S1 = '| <a id="s1"></a>S1 | Encrypted. | Secure | `tests/test_keys.py::test_one`; `web/e2e/a.spec.ts::opens the page` | test | proven |'
README = "# App\n\n## Secure, Private, Thoughtful\n\n- Encrypted. [S1](docs/CLAIMS.md#s1)\n\n## Next\n\n- a bullet with no ID\n"


def site(root, *rows, readme=README, docs=None):
    (root / "docs").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "web/e2e").mkdir(parents=True)
    (root / "tests/test_keys.py").write_text("def test_one():\n    pass\n")
    (root / "web/e2e/a.spec.ts").write_text("test('opens the page', async ({ page }) => {});\n")
    (root / "docs/CLAIMS.md").write_text(HEADER + "\n".join(rows or (S1,)) + "\n")
    (root / "README.md").write_text(readme)
    for rel, text in (docs or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


def test_a_good_ledger_has_no_problems(tmp_path):
    assert problems(site(tmp_path)) == []


def test_a_tagline_bullet_needs_an_id_even_when_it_wraps(tmp_path):
    readme = ("## Secure, Private, Thoughtful\n\n- Encrypted. [S1](docs/CLAIMS.md#s1)\n- Wrapped onto\n"
              "  two lines. [S1](docs/CLAIMS.md#s1)\n- No ID here.\n")
    assert problems(site(tmp_path, readme=readme)) == [
        "README.md:6: a bullet in '## Secure, Private, Thoughtful' with no claim ID"]


def test_a_readme_without_the_tagline_section_fails(tmp_path):
    found = problems(site(tmp_path, readme="# App\n\n- Encrypted. [S1](docs/CLAIMS.md#s1)\n"))
    assert found == ["README.md has no '## Secure, Private, Thoughtful' section"]


def test_a_doc_citing_an_id_with_no_row_fails(tmp_path):
    found = problems(site(tmp_path, docs={"docs/explanations/privacy.md": "Safe. [P9](../CLAIMS.md#p9)\n"}))
    assert found == ["docs/explanations/privacy.md cites P9, which has no row in docs/CLAIMS.md"]


def test_a_link_must_lead_to_the_ledger_and_its_own_anchor(tmp_path):
    found = problems(site(tmp_path, docs={"docs/explanations/privacy.md": "A. [S1](CLAIMS.md#s1) B. [S1](../CLAIMS.md#s2)\n"}))
    assert found == ["docs/explanations/privacy.md: [S1](CLAIMS.md#s1) doesn't lead to docs/CLAIMS.md",
                     "docs/explanations/privacy.md: [S1] links to #s2, not #s1"]


@pytest.mark.parametrize("proof,problem", [
    ("`tests/nope.py`", "S1: tests/nope.py doesn't exist"),
    ("`tests/test_keys.py::test_two`", "S1: tests/test_keys.py has no test_two"),
    ("`web/e2e/a.spec.ts::closes the page`", "S1: web/e2e/a.spec.ts has no test titled 'closes the page'"),
])
def test_every_proof_must_exist(tmp_path, proof, problem):
    row = f'| <a id="s1"></a>S1 | Encrypted. | Secure | {proof} | test | proven |'
    assert problems(site(tmp_path, row)) == [problem]


def test_a_proven_row_no_doc_cites_fails_unless_internal(tmp_path):
    s2 = '| <a id="s2"></a>S2 | Also. | Secure | `tests/test_keys.py` | test | proven |'
    assert problems(site(tmp_path / "a", S1, s2)) == ["S2: no doc cites it; cite it, or end its status with ', internal'"]
    assert problems(site(tmp_path / "b", S1, s2.replace("| proven |", "| proven, internal |"))) == []


def test_a_pending_row_may_name_a_proof_still_to_come_but_fails_at_release(tmp_path):
    s2 = '| <a id="s2"></a>S2 | Signed. | Secure | `tests/test_later.py` | test | pending (PR 11) |'
    root = site(tmp_path, S1, s2)
    assert problems(root) == [] and pending(root) == ["S2"]


@pytest.mark.parametrize("row,problem", [
    ('| <a id="s1"></a>S1 | Encrypted. | Private | `tests/test_keys.py` | test | proven |',
     "S1: pillar 'Private', but S IDs are Secure"),
    ('| <a id="s1"></a>S1 | Encrypted. | Secure | `tests/test_keys.py` | proof | proven |',
     "S1: kind 'proof' isn't test, file or review"),
    ('| <a id="s1"></a>S1 | Encrypted. | Secure | `tests/test_keys.py` | test | done |',
     "S1: status 'done' isn't 'proven' or 'pending (PR n)' (then ', internal' if no doc cites it)"),
    ('| <a id="s1"></a>S1 | Encrypted. | Secure | tests/test_keys.py | test | proven |', "S1: no proof in backticks"),
    ('| <a id="s2"></a>S1 | Encrypted. | Secure | `tests/test_keys.py` | test | proven |',
     'CLAIMS.md:5: the ID cell is <a id="p3"></a>P3, the anchor the ID in lower case'),
])
def test_a_malformed_row_is_named(tmp_path, row, problem):
    assert problem in problems(site(tmp_path, row))


S2_PENDING = '| <a id="s2"></a>S2 | Signed. | Secure | `tests/test_later.py` | test | pending (PR 11) |'


def test_a_pending_claim_is_cited_as_planned(tmp_path):
    bare = README.replace("\n\n## Next", "\n- Signed. [S2](docs/CLAIMS.md#s2)\n\n## Next")
    assert problems(site(tmp_path / "a", S1, S2_PENDING, readme=bare)) == [
        "README.md cites S2, which is pending: say it as planned and follow the link with '(planned)'"]
    marked = README.replace("\n\n## Next", "\n- Signed, planned. [S2](docs/CLAIMS.md#s2) (planned)\n\n## Next")
    assert problems(site(tmp_path / "b", S1, S2_PENDING, readme=marked)) == []


def test_a_pending_claim_says_planned_in_words_not_only_in_the_suffix(tmp_path):
    true = README.replace("\n\n## Next", "\n- Signed. [S2](docs/CLAIMS.md#s2) (planned)\n\n## Next")
    assert problems(site(tmp_path / "a", S1, S2_PENDING, readme=true)) == [
        "README.md cites S2, which is pending: the line must say 'planned' or 'before 0.1.0' in words, not state it as true"]
    later = README.replace("\n\n## Next", "\n- Signing before 0.1.0. [S2](docs/CLAIMS.md#s2) (planned)\n\n## Next")
    assert problems(site(tmp_path / "b", S1, S2_PENDING, readme=later)) == []


def test_a_proven_claim_never_says_planned(tmp_path):
    readme = README.replace("[S1](docs/CLAIMS.md#s1)", "[S1](docs/CLAIMS.md#s1) (planned)")
    assert problems(site(tmp_path, readme=readme)) == ["README.md: S1 is proven now: drop '(planned)' and say it plainly"]


def test_private_docs_never_count_as_citing(tmp_path):
    root = site(tmp_path, docs={"docs/superpowers/specs/x.md": "e.g. [P9](docs/CLAIMS.md#p9)\n"})
    assert problems(root) == []
