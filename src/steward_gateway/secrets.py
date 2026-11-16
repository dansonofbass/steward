"""Files only the gateway's user may read (spec 9.5): the env file with the API key, the pairing token and the history
key. The gateway refuses a file anyone else can read. Nothing here logs a value."""
from __future__ import annotations

import os
from pathlib import Path

from steward_gateway.config import GatewayConfig


class SecretFileError(RuntimeError):
    """A secret file is readable by others or belongs to someone else. The message says how to fix it."""


def _check_private(path: Path) -> None:
    st = path.stat()
    if st.st_mode & 0o077:
        raise SecretFileError(f"{path} is readable by others. Run: chmod 600 {path}")
    if st.st_uid != os.getuid():
        raise SecretFileError(f"{path} belongs to another user. It must belong to the user the gateway runs as.")


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    _check_private(path)
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def api_key(cfg: GatewayConfig) -> str | None:
    return read_env_file(cfg.env_path).get("ANTHROPIC_API_KEY") or None


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".new")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def read_private(path: Path) -> str | None:
    if not path.exists():
        return None
    _check_private(path)
    return path.read_text().strip() or None
