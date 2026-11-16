"""docs/guides/gpu.md (PR 13b): the steps in order, every NVIDIA package of the CUDA image under a named license, the
vendors' own install pages, and AMD marked untested."""
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "guides" / "gpu.md"
HEADINGS = ("## Find out what you have", "## Licenses", "## The one-time build", "## NVIDIA", "## AMD",
            "## Check it worked", "## Intel GPUs and NPUs")


def section(doc: str, heading: str) -> str:
    start = doc.index(f"\n{heading}\n")
    nxt = doc.find("\n## ", start + 1)
    return doc[start: nxt if nxt != -1 else len(doc)]


def test_the_guide_walks_the_steps_in_order():
    doc = GUIDE.read_text()
    assert doc.startswith("# Speed up the gateway with a GPU\n")
    assert [doc.index(f"\n{h}\n") for h in HEADINGS] == sorted(doc.index(f"\n{h}\n") for h in HEADINGS)


def test_every_nvidia_package_in_the_cuda_image_is_under_a_named_license():
    lock = tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    licenses = section(GUIDE.read_text(), "## Licenses")
    for name in sorted(p["name"] for p in lock if re.match(r"nvidia-|cuda-", p["name"])):
        assert f"`{name}`" in licenses, name
    for link in ("https://docs.nvidia.com/cuda/eula/", "https://rocm.docs.amd.com/"):
        assert link in licenses, link
    assert "Deep Learning Container" in licenses and "doesn't apply" in licenses
    assert "you download" in licenses and "Steward never redistributes" in licenses


OLLAMA_LICENSE = "https://github.com/ollama/ollama/blob/main/LICENSE"


def test_the_license_gate_is_described_as_what_it_covers():
    """The gate stops Steward building or running its GPU gateway. Ollama's images come from Ollama under its own
    license, Compose may pull them before the gateway build is refused, and even the CPU one carries GPU libraries."""
    licenses = section(GUIDE.read_text(), "## Licenses")
    assert ("Until `.env` says you accept them (`STEWARD_GPU_LICENSE_ACCEPTED`, set in the steps below), Steward won't "
            "build or run its GPU gateway.") in licenses
    assert f"Ollama distributes them from its own registry, under [Ollama's license]({OLLAMA_LICENSE})" in licenses
    assert "`STEWARD_GPU_LICENSE_ACCEPTED` doesn't cover them" in licenses
    assert "Compose may download a GPU profile's Ollama image before it refuses to build the gateway" in licenses
    assert "carries GPU runtime libraries even when it runs on the CPU" in licenses


# A sentence saying nothing is downloaded until the license is accepted: untrue while Compose can pull Ollama's images.
OVERCLAIM = re.compile(r"\b(no|nothing|none)\b[^.\n]{0,80}\bdownload\w*[^.\n]{0,40}\buntil\b", re.I)


def test_no_doc_or_comment_says_nothing_is_downloaded_before_acceptance():
    files = [*sorted((ROOT / "docs" / "guides").glob("*.md")), ROOT / "deploy" / "compose.yml",
             ROOT / "deploy" / ".env.example", *sorted((ROOT / "deploy" / "gateway").glob("Dockerfile*")),
             ROOT / "src" / "steward_gateway" / "gpu.py"]
    for f in files:
        assert not OVERCLAIM.search(f.read_text()), f
    assert OVERCLAIM.search("No NVIDIA or AMD package is downloaded until you accept.")    # the guard catches it


def test_the_build_says_what_it_takes_and_what_it_downloads():
    build = section(GUIDE.read_text(), "## The one-time build")
    for line in ("docker compose --profile gateway-nvidia build", "docker compose --profile gateway-amd build",
                 "10 to 20 minutes", "several GB", "steward-gateway-cuda:local", "Steward never publishes",
                 "docker compose pull", "from the Steward source in your clone", "`git pull` the clone"):
        assert line in build, line


def test_the_vendor_steps_link_the_vendors_own_pages_and_accept_the_license():
    doc = GUIDE.read_text()
    nvidia, amd = section(doc, "## NVIDIA"), section(doc, "## AMD")
    assert "https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/" in nvidia
    assert "STEWARD_GPU_LICENSE_ACCEPTED=nvidia" in nvidia and "COMPOSE_PROFILES=tailscale,gateway-nvidia" in nvidia
    assert "https://rocm.docs.amd.com/projects/install-on-linux/" in amd and "STEWARD_RENDER_GID" in amd
    assert "STEWARD_GPU_LICENSE_ACCEPTED=amd" in amd and "not yet tested on real hardware" in amd


@pytest.mark.parametrize("vendor", ["nvidia", "amd"])
def test_after_the_switch_the_gateway_guides_commands_use_the_gpu_service_names(vendor):
    """docs/guides/gateway.md says `docker compose exec gateway ...` and `... exec ollama ollama pull`; under a GPU
    profile those services aren't running, so each vendor's steps say which names to use instead."""
    steps = section(GUIDE.read_text(), "## NVIDIA" if vendor == "nvidia" else "## AMD")
    assert "[gateway guide](gateway.md)" in steps
    assert f"use `gateway-{vendor}` and `ollama-{vendor}` in place of `gateway` and `ollama`" in steps
    assert f"`docker compose exec ollama-{vendor} ollama pull <model>`" in steps


def test_detection_runs_from_the_clone_and_is_checked_where_it_runs():
    """From the clone the GPU gateway builds from (public issue #11): no download from a tag, which can be moved to
    other code after the guide was read."""
    doc = GUIDE.read_text()
    find = section(doc, "## Find out what you have")
    assert "`deploy/gateway/detect-gpu.sh`" in find and "From the `deploy` folder" in find
    assert "less gateway/detect-gpu.sh\nsh gateway/detect-gpu.sh" in find
    assert (ROOT / "deploy" / "gateway" / "detect-gpu.sh").is_file()
    assert not re.search(r"\b(curl|wget)\b|raw\.githubusercontent|https://github\.com/steward-money", doc)
    assert "| sh" not in find                               # read first, never piped into a shell
    check = section(GUIDE.read_text(), "## Check it worked")
    assert "steward-gateway hardware" in check and "Runs on an NVIDIA GPU." in check


def test_no_word_the_docs_avoid():
    doc = GUIDE.read_text().lower()
    assert "stranger" not in doc and " he " not in doc and " she " not in doc
