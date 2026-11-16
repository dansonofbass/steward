"""Code that named a private doc names the public one coming in its place (spec 2026-11-05, section 10, PR 3), and the
taxes e2e shots go to an ignored folder instead of the design folder."""
import re
from pathlib import Path

import pytest

from tests.public_docs import NOT_YET, ROOT, headings
PRIVATE_DOC = re.compile(r"deploy/(?!(?:proxy|tailscale|gateway)/)[\w-]+/|deploy/deploy\.sh|docs/(superpowers|deploy-day|feedback|perf|design|"
                         r"leftovers|model-choice)|model-choice-2026-10\.md")
FIXED = ("src/steward/books/registry.py", "src/steward/inventory/files.py",
         "src/steward/db/alembic/versions/0009_inventory.py", "src/steward_gateway/cli.py",
         "src/steward/engine/decisions.py", "src/steward/settings.py", "tests/test_proxy_files.py",
         "tests/gateway/test_cli.py", "tests/gateway/test_eval_answers.py", "tests/gateway/test_gliner_pin.py",
         "web/e2e/taxes.spec.ts",
         "deploy/compose.yml", "deploy/compose.demo.yml", "deploy/.env.example",
         "deploy/tailscale/tailscale.env.example", "deploy/proxy/proxy.env.example",
         "deploy/proxy/start.sh", "deploy/proxy/Dockerfile",
         "deploy/proxy/Caddyfile.dns-cloudflare", "deploy/proxy/Caddyfile.http", "deploy/proxy/Caddyfile.internal",
         "deploy/gateway/Dockerfile", "deploy/gateway/gateway.toml", "deploy/gateway/torch-cpu.txt", "deploy/gateway/detect-gpu.sh",
         "deploy/gateway/Dockerfile.cuda", "deploy/gateway/Dockerfile.rocm", "deploy/gateway/torch-rocm.txt",
         "docs/guides/gateway.md", "docs/guides/gpu.md",
         ".github/workflows/ci.yml", ".github/workflows/release.yml")


@pytest.mark.parametrize("rel", FIXED)
def test_no_pointer_to_a_private_doc(rel):
    lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
    assert [f"{rel}:{n}" for n, line in enumerate(lines, 1) if PRIVATE_DOC.search(line)] == []


def test_the_taxes_shots_go_to_an_ignored_folder():
    spec = (ROOT / "web/e2e/taxes.spec.ts").read_text(encoding="utf-8")
    assert "path: `e2e/screenshots-taxes/taxes-${size.width}x${size.height}.png`" in spec
    assert "web/e2e/screenshots-taxes/" in (ROOT / ".gitignore").read_text().splitlines()


MOVED = {"docs/INSTALL.md", "docs/CONFIGURATION.md", "docs/PRIVACY.md", "docs/GATEWAY.md", "docs/ARCHITECTURE.md",
         "docs/security/threat-model.md"}
POINTER = re.compile(r"(docs/[\w/.-]+?\.md)(?:, \\?[\"'\u201c]?([A-Z][A-Za-z ]*[a-z]))?")
PUBLIC = ("docs/README.md", "docs/CLAIMS.md", "docs/quickstart/", "docs/guides/", "docs/reference/", "docs/explanations/")
POINTED_FROM = ("src", "web/src", "deploy/compose.yml", "deploy/compose.demo.yml", "deploy/.env.example",
                "deploy/proxy", "deploy/tailscale", "deploy/gateway", ".github", "tests")
SKIP = {"tests/test_doc_pointers.py", "tests/test_export.py"}
SUFFIXES = {".py", ".ts", ".tsx", ".yml", ".sh", ".example", ".toml"}


def _scanned(rel: str) -> bool:
    name = Path(rel).name
    return Path(rel).suffix in SUFFIXES or name.startswith(("Caddyfile", "Dockerfile"))


def pointers() -> list[tuple[str, int, str, str | None]]:
    """(file, line, doc path, heading or None) for each POINTER match in the .py, .ts, .tsx, .yml, .sh, .example, .toml,
    Caddyfile* and Dockerfile* files under POINTED_FROM, skipping node_modules and SKIP."""
    found = []
    for base in POINTED_FROM:
        start = ROOT / base
        files = [start] if start.is_file() else sorted(p for p in start.rglob("*") if p.is_file())
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            if rel in SKIP or "node_modules" in path.parts or not _scanned(rel):
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for m in POINTER.finditer(line):
                    found.append((rel, n, m[1], m[2]))
    return found


def test_no_code_names_a_doc_that_moved():
    assert [f"{f}:{n}: {doc}" for f, n, doc, _ in pointers() if doc in MOVED] == []


def test_every_public_doc_a_pointer_names_exists_with_its_section():
    """A pointer into a PUBLIC path names a page that exists (or is in NOT_YET), and its heading, if any, is a
    #, ## or ### line of that page (a heading that wraps in a comment is matched by its start)."""
    bad = []
    for f, n, doc, heading in pointers():
        if not doc.startswith(PUBLIC):
            continue
        page = ROOT / doc
        if not page.is_file():
            if doc not in NOT_YET:
                bad.append(f"{f}:{n}: {doc} does not exist")
            continue
        if heading and not any(level <= 3 and text.startswith(heading) for _l, level, text in headings(page)):
            bad.append(f"{f}:{n}: {doc} has no heading {heading!r}")
    assert bad == []


def test_the_guard_reads_escaped_quotes_and_wrapped_headings():
    assert POINTER.search('see (docs/guides/gateway.md, \\"Reading PDFs\\").').groups() == ("docs/guides/gateway.md", "Reading PDFs")
    assert POINTER.search("(docs/guides/gateway.md, \"On the same box, with").group(2) == "On the same box"
