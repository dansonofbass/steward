"""Landlock for the sandbox child (remote-reading amendment P59). Just before confine's seccomp filter goes on (which
then refuses landlock_* for good), the child walls off every file but the runtime it needs, read-only: the interpreter
and its sys.path, the system library folders, fonts and its own empty folder. Seccomp sees a path only as a pointer;
Landlock sees the path. On the gateway this keeps
a child that a crafted PDF took over from opening the gateway's API key, pairing token, history key, grants and
ledger, which the same account owns, and on Steward's own machine from opening the book key and the books. Linux
x86_64 with Landlock (5.13+, enabled); anywhere else restrict() raises Unrestricted and no child reads a PDF there
(sandbox.main): Steward sends its PDFs to the gateway, or they wait. Landlock governs what a path holds, not its
metadata or a link's target: chmod, chown, utime, xattr and readlink are confine's to refuse, and stat-family calls still
show whether a path outside the wall exists and its metadata (confine's stated limit)."""
from __future__ import annotations

import ctypes
import os
import struct
import sys


class Unrestricted(Exception):
    pass


SYS_CREATE_RULESET, SYS_ADD_RULE, SYS_RESTRICT_SELF = 444, 445, 446
CREATE_RULESET_VERSION = 1
RULE_PATH_BENEATH = 1
EXECUTE, WRITE_FILE, READ_FILE, READ_DIR = 1 << 0, 1 << 1, 1 << 2, 1 << 3
ABI1_RIGHTS = (1 << 13) - 1                                     # execute … make_sym: every right ABI 1 knows
REFER, TRUNCATE, IOCTL_DEV = 1 << 13, 1 << 14, 1 << 15          # ABI 2, 3 and 5
DIR_READ = EXECUTE | READ_FILE | READ_DIR
FILE_READ = EXECUTE | READ_FILE
SYSTEM = ("/usr/lib", "/usr/lib64", "/lib", "/lib64", "/usr/local/lib", "/etc/ld.so.cache", "/usr/share/fonts",
          "/usr/local/share/fonts", "/usr/share/locale")


def _syscall(*args) -> int:
    fn = ctypes.CDLL(None, use_errno=True).syscall
    fn.restype, fn.argtypes = ctypes.c_long, None
    return fn(*args)


def abi() -> int:
    """Landlock's ABI version here, or 0 (not Linux x86_64, an older kernel, or Landlock off)."""
    if sys.platform != "linux" or os.uname().machine != "x86_64":
        return 0
    return max(0, _syscall(ctypes.c_long(SYS_CREATE_RULESET), None, ctypes.c_size_t(0),
                           ctypes.c_uint32(CREATE_RULESET_VERSION)))


def handled(version: int) -> int:
    """Every filesystem right this ABI knows: what isn't granted below is refused."""
    return ABI1_RIGHTS | (REFER if version >= 2 else 0) | (TRUNCATE if version >= 3 else 0) | \
        (IOCTL_DEV if version >= 5 else 0)


def runtime_paths() -> list[str]:
    """What the child may read: the interpreter (its prefixes and sys.path: stdlib, lib-dynload, site-packages, the
    project's src), the system library folders and fonts, and its own empty working folder."""
    seen = {sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix, os.getcwd(), *SYSTEM,
            *(p for p in sys.path if p)}
    return sorted(p for p in seen if os.path.exists(p))


def restrict(paths: list[str]) -> int:
    """Wall this process (and its threads) off from every file outside paths, read-only inside them, for good; the
    ABI used. Raises Unrestricted when Landlock isn't here or refuses."""
    version = abi()
    if version < 1:
        raise Unrestricted("landlock")
    attr = ctypes.create_string_buffer(struct.pack("=Q", handled(version)), 8)
    ruleset = _syscall(ctypes.c_long(SYS_CREATE_RULESET), attr, ctypes.c_size_t(8), ctypes.c_uint32(0))
    if ruleset < 0:
        raise Unrestricted("ruleset")
    try:
        for path in paths:
            try:
                fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            except OSError:
                continue
            try:
                rights = DIR_READ if os.path.isdir(path) else FILE_READ
                rule = ctypes.create_string_buffer(struct.pack("=Qi", rights, fd), 12)
                if _syscall(ctypes.c_long(SYS_ADD_RULE), ctypes.c_long(ruleset), ctypes.c_long(RULE_PATH_BENEATH),
                            rule, ctypes.c_uint32(0)) != 0:
                    raise Unrestricted("rule")
            finally:
                os.close(fd)
        if _syscall(ctypes.c_long(SYS_RESTRICT_SELF), ctypes.c_long(ruleset), ctypes.c_uint32(0)) != 0:
            raise Unrestricted("restrict")
    finally:
        os.close(ruleset)
    return version
