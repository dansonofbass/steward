"""The license, the notice for what Steward ships from others, and the security and contributing pages."""
import json
import re
import tomllib

from tests.public_docs import ROOT

NOTICED = {"sqlcipher3-binary": "uv", "pypdfium2": "uv", "certifi": "uv", "tqdm": "uv",
           "@fontsource-variable/newsreader": "npm", "@fontsource/source-sans-3": "npm"}
NOTICE_WORDS = ("SQLCipher", "OpenSSL", "PDFium", "SIL OPEN FONT LICENSE", "Newsreader", "Source Sans 3",
                "Mozilla Public License")


def test_the_license_is_the_agpl():
    text = (ROOT / "LICENSE").read_text()
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in text.splitlines()[0]
    assert "Version 3, 19 November 2007" in text and "END OF TERMS AND CONDITIONS" in text


def test_both_packages_declare_it():
    assert tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["license"] == "AGPL-3.0-or-later"
    pkg = json.loads((ROOT / "web/package.json").read_text())
    assert pkg["license"] == "AGPL-3.0-or-later" and pkg["private"] is True


def test_notice_names_each_package_and_each_is_still_a_dependency():
    notice = (ROOT / "NOTICE").read_text()
    lock = (ROOT / "uv.lock").read_text()
    pkg = json.loads((ROOT / "web/package.json").read_text())
    npm = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    for name, where in NOTICED.items():
        assert name in notice, f"NOTICE does not name {name}"
        if where == "uv":
            assert f'name = "{name}"' in lock, f"{name} is no longer in uv.lock; drop it from NOTICE"
        else:
            assert name in npm, f"{name} is no longer in web/package.json; drop it from NOTICE"
    for word in NOTICE_WORDS:
        assert word in notice, f"NOTICE does not say {word}"


def test_notice_names_every_data_source_host():
    sources = (ROOT / "src/steward/engine/data/SOURCES.md").read_text()
    table = [line for line in sources.splitlines() if line.startswith("|")]
    hosts = {m[1] for line in table for m in re.finditer(r"https://([^/\s,)`]+)", line)}
    assert hosts, "no hosts found in SOURCES.md's table"
    notice = (ROOT / "NOTICE").read_text()
    assert [h for h in sorted(hosts) if h not in notice] == []


def test_security_says_where_and_how_soon():
    s = (ROOT / "SECURITY.md").read_text()
    assert all(w in s for w in ("security/advisories/new", "security@stewardmoney.app", "7 days"))


def test_contributing_asks_for_a_sign_off():
    c = (ROOT / "CONTRIBUTING.md").read_text()
    assert "Signed-off-by" in c and "best effort" in c
