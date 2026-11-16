"""What the gateway runs redaction on, for /v1/health: "cpu", "cuda" or "rocm" (ROCm torch also calls its device
"cuda", so torch.version.hip tells them apart), or None when the models didn't load."""
from __future__ import annotations

from collections.abc import Callable, Sequence

ACCELERATORS = ("cpu", "cuda", "rocm")


def name(device: str | None, hip: str | None) -> str | None:
    if device is None:
        return None
    if device == "cpu":
        return "cpu"
    return "rocm" if hip else "cuda"


def torch_hip() -> str | None:
    """torch.version.hip, or None. Imported lazily: the NAS image has no torch. A torch that fails to import for any
    reason gives None; a health field must not stop start-up."""
    try:
        import torch
        return torch.version.hip
    except Exception:
        return None


def available() -> str:
    """What torch could run on right now: "cuda", "rocm" or "cpu" (also when torch isn't installed or won't import)."""
    try:
        import torch
        if torch.cuda.is_available():
            return "rocm" if torch.version.hip else "cuda"
    except Exception:
        pass
    return "cpu"


def of_detectors(detectors: Sequence[object], *, hip: Callable[[], str | None] = torch_hip) -> str | None:
    if not detectors:
        return None
    device = next((d for d in (getattr(x, "device", None) for x in detectors) if d), "cpu")
    # Only a device that could be a GPU needs the torch import.
    return name(device, hip() if device != "cpu" else None)
