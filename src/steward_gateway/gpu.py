"""The gateway's start-up checks (PR 13b). A GPU image (STEWARD_GATEWAY_GPU set) needs its vendor's license accepted
before anything else and says plainly when it sees no GPU; a gateway without STEWARD_GATEWAY_GPU (the CPU image, the
systemd one) skips both. Every gateway with network = "compose", the CPU image included, refuses to serve when two
gateways answer as "gateway", so whichever of two starts second stops."""
from __future__ import annotations

import socket
import string
from collections.abc import Callable, Mapping

VENDORS = {"nvidia": "NVIDIA", "amd": "AMD"}
LIBRARIES = {"nvidia": "CUDA", "amd": "ROCm"}
GUIDE_LICENSES = 'docs/guides/gpu.md, "Licenses"'
OLLAMA_SERVICES = {"nvidia": "ollama-nvidia", "amd": "ollama-amd"}     # deploy/compose.yml's Ollama beside each image
BAD_IMAGE ="STEWARD_GATEWAY_GPU must be nvidia or amd."
TWO_GATEWAYS = ('Two gateways answer as "gateway" on this compose network. Use one of gateway, gateway-nvidia and '
                "gateway-amd in COMPOSE_PROFILES.")
NO_GPU = {
    "nvidia": ("This gateway image is for an NVIDIA GPU, but torch can't see one, so redaction runs on the CPU. Check "
               "the host's driver and the NVIDIA Container Toolkit (docs/guides/gpu.md, \"NVIDIA\")."),
    "amd": ("This gateway image is for an AMD GPU, but torch can't see one, so redaction runs on the CPU. Check "
            "/dev/kfd, /dev/dri and STEWARD_RENDER_GID (docs/guides/gpu.md, \"AMD\").")}


_SPACE = string.whitespace                      # what [[:space:]] matches in sh's C locale: space, \t, \n, \r, \v, \f
_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)          # as tr 'A-Z' 'a-z' does


def _trim(value: str) -> str:
    return value.strip(_SPACE)


def _norm(value: str) -> str:
    """The rule the GPU Dockerfiles' build gate follows too: trim whitespace from both ends, lowercase A to Z, keep
    inner spaces ("n vidia" is not "nvidia"). tests/gateway/license_values.py holds the cases both are tested on."""
    return _trim(value).translate(_LOWER)


def license_problem(environ: Mapping[str, str]) -> str | None:
    """Why a GPU image must not start, or None. Only an absent STEWARD_GATEWAY_GPU skips the gate: a present but
    empty one is refused, so an empty override is no way past it."""
    if "STEWARD_GATEWAY_GPU" not in environ:
        return None
    image = _norm(environ["STEWARD_GATEWAY_GPU"])
    if image not in VENDORS:
        return BAD_IMAGE
    name = VENDORS[image]
    accepted = environ.get("STEWARD_GPU_LICENSE_ACCEPTED", "")
    if not _trim(accepted):
        return (f"This gateway image includes {name}'s {LIBRARIES[image]} libraries, which come under {name}'s own "
                f"licenses. Read them ({GUIDE_LICENSES}), then set STEWARD_GPU_LICENSE_ACCEPTED={image} in .env and "
                "start again.")
    if _norm(accepted) != image:
        return (f'STEWARD_GPU_LICENSE_ACCEPTED says "{_trim(accepted)}", but this gateway image is for {name}. Read '
                f"{name}'s licenses ({GUIDE_LICENSES}), then set STEWARD_GPU_LICENSE_ACCEPTED={image}.")
    return None


def ollama_service(environ: Mapping[str, str], network: str) -> str | None:
    """The compose service that runs Ollama beside this GPU image (it starts only once the gateway is healthy), or
    None for the CPU image and for a gateway outside compose (the systemd one)."""
    if network != "compose" or "STEWARD_GATEWAY_GPU" not in environ:
        return None
    return OLLAMA_SERVICES.get(_norm(environ["STEWARD_GATEWAY_GPU"]))


def no_gpu_line(environ: Mapping[str, str], available: Callable[[], str]) -> str | None:
    """The line for a GPU image whose torch sees no GPU. Asks `available` only when STEWARD_GATEWAY_GPU is set."""
    if "STEWARD_GATEWAY_GPU" not in environ:
        return None
    image = _norm(environ["STEWARD_GATEWAY_GPU"])
    if image not in NO_GPU or available() != "cpu":
        return None
    return NO_GPU[image]


def two_gateways(resolve: Callable | None = None) -> bool:
    """More than one distinct address under the name "gateway" in one address family (a gateway with both an A and an
    AAAA record is still one gateway). A failed lookup is False. serve asks it for every gateway in compose mode, CPU
    or GPU, and never outside compose."""
    resolve = resolve or socket.getaddrinfo
    try:
        found = resolve("gateway", 8430)
    except OSError:
        return False
    by_family: dict[int, set[str]] = {}
    for family, _type, _proto, _canon, sockaddr in found:
        by_family.setdefault(family, set()).add(sockaddr[0])
    return any(len(addresses) > 1 for addresses in by_family.values())
