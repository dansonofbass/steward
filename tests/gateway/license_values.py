"""STEWARD_GPU_LICENSE_ACCEPTED values and whether each accepts a vendor (PR 13b). The GPU Dockerfiles' build gate
(tests/test_gateway_image.py runs it in sh) and the gateway's start-up gate (tests/gateway/test_gpu_mode.py) read this
one table, so both follow one rule: trim whitespace from both ends, lowercase A to Z, and keep inner spaces."""
from __future__ import annotations

# (value, vendor, accepted)
LICENSE_VALUES: list[tuple[str, str, bool]] = [
    ("nvidia", "nvidia", True),
    ("NVIDIA", "nvidia", True),
    (" nvidia\t", "nvidia", True),
    ("\tNVIDIA \r\n", "nvidia", True),
    ("\nnvidia", "nvidia", True),
    ("n vidia", "nvidia", False),
    ("nvi\ndia", "nvidia", False),
    ("", "nvidia", False),
    (" \t", "nvidia", False),
    ("amd", "nvidia", False),
    ("nvidia amd", "nvidia", False),
    ("yes", "nvidia", False),
    ("NVİDIA", "nvidia", False),          # a dotted capital I is not an I
    ("amd", "amd", True),
    ("AMD", "amd", True),
    (" amd\t", "amd", True),
    ("a md", "amd", False),
    ("nvidia", "amd", False),
    ("", "amd", False),
]
