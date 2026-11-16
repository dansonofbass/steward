"""The supply chain (public issues #10 and #11). Dependabot proposes updates for every pinned image, action and package
each week; every OS package a Dockerfile installs is pinned to a version; and the upgrade guide pulls the digest cosign
verified, never a tag that can move after the check. Claim S8."""
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPENDABOT = ROOT / ".github" / "dependabot.yml"
UPGRADE = ROOT / "docs" / "guides" / "upgrade.md"
COMPOSE = ROOT / "deploy" / "compose.yml"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
SKIP = {"node_modules", "dist", "__pycache__", "test-results", "playwright-report"}
OURS = re.compile(r"^ghcr\.io/steward-money/(steward(?:-proxy|-gateway)?):\S+$")   # the images release.yml publishes


def walk():
    """Every folder in the tree, as a Dependabot directory ("/", "/deploy/proxy"), with its file names."""
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith("."))
        rel = Path(folder).relative_to(ROOT).as_posix()
        yield ("/" if rel == "." else f"/{rel}"), files


def dockerfile_folders() -> set[str]:
    return {d for d, files in walk() if any(re.fullmatch(r"Dockerfile(\.[\w-]+)?", f) for f in files)}


def dependabot() -> dict:
    return yaml.safe_load(DEPENDABOT.read_text())


def covered() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for u in dependabot()["updates"]:
        dirs = u.get("directories") or [u["directory"]]
        out.setdefault(u["package-ecosystem"], set()).update(dirs)
    return out


def test_dependabot_covers_the_images_the_actions_and_both_lockfiles():
    assert dependabot()["version"] == 2
    c = covered()
    assert set(c) == {"docker", "docker-compose", "github-actions", "uv", "npm"}
    assert c["github-actions"] == {"/"} and c["uv"] == {"/"} and c["npm"] == {"/web"}
    assert c["docker-compose"] == {"/deploy"}           # the third-party images in deploy/compose.yml
    assert (ROOT / "uv.lock").is_file() and (ROOT / "web" / "package-lock.json").is_file()


def test_every_folder_with_a_dockerfile_is_watched():
    found = dockerfile_folders()
    assert {"/", "/deploy/proxy", "/deploy/gateway"} <= found        # the walk sees the ones we know about
    assert covered()["docker"] == found


def test_every_watched_folder_exists():
    for eco, dirs in covered().items():
        for d in dirs:
            assert (ROOT / d.lstrip("/")).is_dir(), (eco, d)


def test_updates_come_weekly_with_minor_and_patch_grouped_per_ecosystem():
    for u in dependabot()["updates"]:
        eco = u["package-ecosystem"]
        assert u["schedule"]["interval"] == "weekly", eco
        groups = list(u["groups"].values())
        assert len(groups) == 1 and sorted(groups[0]["update-types"]) == ["minor", "patch"], eco
    names = [name for u in dependabot()["updates"] for name in u["groups"]]
    assert len(names) == len(set(names))                # one group name per ecosystem


def test_torch_comes_on_its_own_because_the_gateway_pins_it_by_hand_too():
    """deploy/gateway/torch-*.txt pin the locked torch with PyTorch's hashes. A grouped uv update that moved torch
    would stay red until those files were regenerated, and hold every other update back with it."""
    hand_pinned = set()
    for f in (ROOT / "deploy" / "gateway").glob("torch-*.txt"):
        for line in f.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                hand_pinned.add(re.match(r"[\w-]+", line)[0].removesuffix("-rocm"))
    locked = {p["name"] for p in tomllib.loads((ROOT / "uv.lock").read_text())["package"]}
    hand_pinned &= locked
    assert {"torch", "triton"} <= hand_pinned
    (uv,) = [u for u in dependabot()["updates"] if u["package-ecosystem"] == "uv"]
    (group,) = uv["groups"].values()
    assert hand_pinned <= set(group["exclude-patterns"]), hand_pinned
    assert "torch-rocm.txt" in DEPENDABOT.read_text()


# OS packages: a Dockerfile's apk or apt install takes whatever the mirror has that day unless it names a version.
INSTALL = re.compile(r"\b(?:apk add|apt-get install|apt install)\b((?:[^&;|\n\\]|\\\n)*)")


def unpinned_packages(text: str) -> list[str]:
    out = []
    for m in INSTALL.finditer(text):
        words = m[1].replace("\\\n", " ").split()
        out += [w for w in words if not w.startswith("-") and "=" not in w]
    return out


def test_the_install_check_finds_an_unpinned_package():
    assert unpinned_packages("RUN apk add --no-cache curl && adduser x") == ["curl"]
    assert unpinned_packages("RUN apt-get install -y \\\n    git=1:2.47.3-0 \\\n    jq\n") == ["jq"]
    assert unpinned_packages("RUN apk add --no-cache curl=8.23.0-r0 && adduser x") == []


def test_every_os_package_a_dockerfile_installs_names_its_version():
    hits = {}
    for d, files in walk():
        for f in files:
            if re.fullmatch(r"Dockerfile(\.[\w-]+)?", f):
                path = ROOT / d.lstrip("/") / f
                if bad := unpinned_packages(path.read_text()):
                    hits[path.relative_to(ROOT).as_posix()] = bad
    assert hits == {}


# The upgrade guide: cosign 3 reads the release's signatures (cosign 2 finds none), prints the digest it checked, and
# compose.override.yml pulls exactly that digest.
FENCED = re.compile(r"^ *```[^\n]*\n(.*?)^ *```", re.S | re.M)
DIGEST_OF = """| jq -r '.[0].critical.image."docker-manifest-digest"'"""


def guide() -> str:
    return UPGRADE.read_text()


def blocks() -> list[str]:
    return [m[1] for m in FENCED.finditer(guide())]


def override_block() -> str:
    found = [b for b in blocks() if b.lstrip().startswith("services:")]
    assert len(found) == 1, found
    return found[0]


def test_the_guide_asks_for_cosign_3_and_says_what_cosign_2_does():
    text = " ".join(guide().split())
    assert "cosign 3 or newer" in text
    assert '"no signatures found"' in text


def test_the_guide_verifies_with_the_release_identity_and_prints_the_digest():
    verify = [b for b in blocks() if b.startswith("cosign verify ")]
    assert len(verify) == 1
    regexp = re.search(r"--certificate-identity-regexp '([^']+)'", RELEASE.read_text())[1]
    assert f"--certificate-identity-regexp '{regexp}'" in verify[0]
    assert "--certificate-oidc-issuer https://token.actions.githubusercontent.com" in verify[0]
    assert verify[0].rstrip().endswith(DIGEST_OF)


def test_the_guide_never_reads_the_piped_check_by_its_exit_status():
    """A pipeline exits with its last command's status: jq's, which is 0 when cosign fails and prints nothing. So the
    guide says the digest is the result, and that a script needs both -e and pipefail to stop on a failed check."""
    text = " ".join(guide()[guide().index("## Verify the images"):].split())
    assert not re.search(r"\b(?:exits?|returns?)(?: with)?(?: status| code)? 0\b", text, re.I), "the exit status is jq's"
    assert "prints a digest only when the image was built by that workflow from a version tag" in text
    assert "No digest means the image failed the check." in text
    assert "`set -eo pipefail`" in text


def test_a_failed_cosign_check_still_exits_0_through_the_pipe():
    """What the guide warns about, run for real: without pipefail the pipe's status hides cosign's failure, and
    pipefail alone doesn't stop the script. `set -eo pipefail`, the guide's advice, stops it before the next line."""
    if shutil.which("jq") is None:
        pytest.skip("no jq here")
    fail = f"""sh -c 'echo "Error: no matching signatures" >&2; exit 1' {DIGEST_OF}"""
    plain = subprocess.run(["bash", "--noprofile", "--norc", "-c", fail], capture_output=True, text=True)
    assert plain.returncode == 0 and plain.stdout == ""
    piped = subprocess.run(["bash", "--noprofile", "--norc", "-c", f"set -o pipefail; {fail}"], capture_output=True)
    assert piped.returncode != 0

    def script(opts: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", "--noprofile", "--norc", "-c", f"{opts}; d=$({fail}); echo after"],
                              capture_output=True, text=True)

    assert "after" in script("set -o pipefail").stdout, "pipefail alone lets the script go on"
    stopped = script("set -eo pipefail")
    assert stopped.returncode != 0 and "after" not in stopped.stdout


def pulled_images() -> dict[str, str]:
    """Each compose service that pulls one of Steward's images, with that image's name."""
    out = {}
    for name, s in yaml.safe_load(COMPOSE.read_text())["services"].items():
        if (m := OURS.match(s.get("image", ""))) and "build" not in s:
            out[name] = m[1]
    return out


def test_the_override_pins_every_service_that_pulls_a_steward_image_by_digest():
    services = yaml.safe_load(override_block())["services"]
    assert set(services) == set(pulled_images()) == {"steward", "proxy", "proxy-lan", "gateway"}
    for name, image in pulled_images().items():
        assert services[name] == {"image": f"ghcr.io/steward-money/{image}:<version>@<{image}'s digest>"}, name
    assert "compose.override.yml" in guide()


def test_compose_pulls_the_override_digest(tmp_path):
    if shutil.which("docker") is None or subprocess.run(["docker", "compose", "version"], capture_output=True).returncode:
        pytest.skip("no docker compose here")
    shutil.copy(COMPOSE, tmp_path / "compose.yml")
    shutil.copy(ROOT / "deploy" / ".env.example", tmp_path / ".env")
    digests = {"steward": "a" * 64, "steward-proxy": "b" * 64, "steward-gateway": "c" * 64}
    text = override_block().replace("<version>", VERSION)
    for image, hexes in digests.items():
        text = text.replace(f"<{image}'s digest>", f"sha256:{hexes}")
    (tmp_path / "compose.override.yml").write_text(text)
    p = subprocess.run(["docker", "compose", "--profile", "domain", "--profile", "lan", "--profile", "gateway",
                        "config", "--format", "json"],
                       cwd=tmp_path, env={**os.environ, "COMPOSE_PROFILES": ""}, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    got = {n: s["image"] for n, s in yaml.safe_load(p.stdout)["services"].items() if n in pulled_images()}
    assert got == {
        "steward": f"ghcr.io/steward-money/steward:{VERSION}@sha256:{'a' * 64}",
        "proxy": f"ghcr.io/steward-money/steward-proxy:{VERSION}@sha256:{'b' * 64}",
        "proxy-lan": f"ghcr.io/steward-money/steward-proxy:{VERSION}@sha256:{'b' * 64}",
        "gateway": f"ghcr.io/steward-money/steward-gateway:{VERSION}@sha256:{'c' * 64}"}


def test_an_upgrade_moves_a_gpu_gateway_with_git_pull_and_a_rebuild():
    """The GPU gateways build from the clone (deploy/compose.yml's context is ..), so the clone is what an upgrade moves.
    No commit or tag to copy by hand (public issue #11)."""
    step = guide()[guide().index("\n2. "):guide().index("\n3. ")]
    text = " ".join(step.split())
    assert "If you use a GPU gateway, run `git pull` in the clone" in text
    assert "the source the GPU gateway is built from" in text
    for vendor in ("nvidia", "amd"):
        assert f"docker compose --profile gateway-{vendor} build" in step, vendor
    assert "context:" not in guide() and "commit" not in guide()
