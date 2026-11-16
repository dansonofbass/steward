"""The PDF child's seccomp filter, number by number (the 0.1.0 gate's ARG-1, ARG-2, ARG-3, ARG-6, ARG-7). The class:
a syscall the filter never names is let through. The guard: every number of the pinned x86_64 table has one class,
anything past the table answers ENOSYS, and the program is run here through a small cBPF interpreter so each verdict
is checked without a kernel. Then the confined child tries the escapes for real."""
import json
import os
import signal
import struct
import subprocess
import sys
import threading
from collections import Counter
from pathlib import Path

import pytest

from steward_pdf import confine as C
from steward_pdf import sandbox as S
from steward_pdf.x86_64 import NUMBERS

TABLE = Path(__file__).parent / "fixtures" / "syscall_64.tbl"
PID, PPID = 4242, 4241
ALLOW, EPERM, ENOSYS, KILL = C.RET_ALLOW, C.EPERM, C.ENOSYS, C.RET_KILL_PROCESS


def pinned() -> dict[int, str]:
    rows = (ln.split("\t") for ln in TABLE.read_text().splitlines() if ln and not ln.startswith("#"))
    return {int(nr): name for nr, name in rows}


def run(prog, nr: int, args=(), arch: int = C.AUDIT_ARCH_X86_64) -> int:
    """Classic BPF as the kernel runs a seccomp filter, for the instructions confine emits: the verdict."""
    a = [*args, *[0] * (6 - len(args))]
    data = struct.pack("<IIQ6Q", nr & 0xFFFFFFFF, arch, 0, *(x & (2 ** 64 - 1) for x in a))
    pc, acc = 0, 0
    while True:
        assert 0 <= pc < len(prog), "ran off the program"
        code, jt, jf, k = prog[pc]
        assert jt <= 255 and jf <= 255
        if code == 0x20:
            acc = struct.unpack_from("<I", data, k)[0]
            pc += 1
        elif code in (0x15, 0x35, 0x45):
            hit = acc == k if code == 0x15 else acc >= k if code == 0x35 else bool(acc & k)
            pc += 1 + (jt if hit else jf)
        elif code == 0x54:                                                      # BPF_ALU|BPF_AND|BPF_K
            acc &= k
            pc += 1
        elif code == 0x06:
            return k
        else:
            raise AssertionError(f"opcode {code:#x}")


PROG = C.program(PID)


def test_every_x86_64_syscall_is_classified():
    """A number nobody classified is the gap fchmodat2 was: the pinned table and the filter's agree, every name has
    exactly one class, and the first number past the table is where ENOSYS starts."""
    assert {nr: name for name, nr in NUMBERS.items()} == pinned()
    classes = Counter([*C.allowed(), *C.CHECKED, *C.NOSYS, *C.denied()])
    assert sorted(n for n, k in classes.items() if k > 1) == []
    assert set(classes) == set(NUMBERS)
    assert C.TABLE_END == max(NUMBERS.values()) + 1 == 470
    assert len(PROG) < 4096


def test_each_class_gets_its_verdict():
    for name in C.allowed():
        assert run(PROG, NUMBERS[name]) == ALLOW, name
    for name in C.denied():
        assert run(PROG, NUMBERS[name]) == EPERM, name
    for name in C.NOSYS:
        assert run(PROG, NUMBERS[name]) == ENOSYS, name
    holes = set(range(C.TABLE_END)) - set(NUMBERS.values())
    assert holes and all(run(PROG, nr) == EPERM for nr in holes)


def test_a_number_past_the_table_answers_enosys_and_foreign_ones_kill():
    for nr in (*range(C.TABLE_END, C.TABLE_END + 64), 1000, C.X32_BIT - 1):
        assert run(PROG, nr) == ENOSYS, nr
    assert run(PROG, C.X32_BIT | NUMBERS["getpid"]) == KILL
    assert run(PROG, NUMBERS["getpid"], arch=0x40000003) == KILL                 # AUDIT_ARCH_I386


def test_the_calls_the_gate_found_let_through_are_refused():
    """ARG-3 and ARG-7 by name: metadata calls Landlock doesn't cover, the new mount API, SysV IPC and POSIX queues,
    and scheduling another process."""
    found = """fchmodat2 mknod mknodat utime utimes futimesat utimensat setxattr lsetxattr fsetxattr getxattr lgetxattr
        fgetxattr listxattr llistxattr flistxattr removexattr lremovexattr fremovexattr setxattrat getxattrat
        listxattrat removexattrat open_tree move_mount fsopen fsconfig fsmount fspick mount_setattr open_tree_attr
        shmget shmat shmctl shmdt semget semop semctl semtimedop msgget msgsnd msgrcv msgctl mq_open mq_unlink
        mq_timedsend mq_timedreceive mq_notify mq_getsetattr ioprio_set file_setattr""".split()
    assert [n for n in found if run(PROG, NUMBERS[n]) != EPERM] == []


@pytest.mark.parametrize("name, args, verdict", [
    ("fcntl", (0, 1), ALLOW), ("fcntl", (0, 2, 1), ALLOW), ("fcntl", (0, 3), ALLOW), ("fcntl", (0, 4, 2048), ALLOW),
    ("fcntl", (0, 1030, 3), ALLOW),                                                  # F_DUPFD_CLOEXEC
    *(("fcntl", (0, v, PPID), EPERM) for v in C.FCNTL_REFUSED.values()),            # F_SETOWN, F_SETSIG, ... (ARG-2)
    ("fcntl", (1, 1031, 1 << 20), EPERM),                                            # F_SETPIPE_SZ
    *(("ioctl", (0, v), ALLOW) for v in C.IOCTL_ALLOWED.values()),                  # TCGETS (isatty), ...
    *(("ioctl", (0, v), EPERM) for v in C.IOCTL_ESCAPES.values()),                  # FIOSETOWN, TIOCSTI, ...
    ("ioctl", (0, 0x40086602), EPERM),                                               # FS_IOC_SETFLAGS: chattr
    ("ioctl", (0, 0x401C5820), EPERM),                                               # FS_IOC_FSSETXATTR
    ("ioctl", (0, 0x5401 | (1 << 32)), ALLOW),                                       # the kernel reads 32 bits
    ("ioctl", (0, 0), EPERM), ("ioctl", (0, 0x5402), EPERM),                         # TCSETS: not on the list
    *(("prctl", (v,), ALLOW) for v in C.PRCTL_ALLOWED.values()),                    # PR_GET_PDEATHSIG, ...
    *(("prctl", (v, 0), EPERM) for v in C.PRCTL_REFUSED.values()),                  # PR_SET_PDEATHSIG, PR_SET_PTRACER
    ("prctl", (15,), EPERM), ("prctl", (C.PR_GET_SECCOMP | (1 << 32),), ALLOW),     # PR_SET_NAME; the option is an int
    ("prctl", (0x59616D61, 0xFFFFFFFF), EPERM),                                      # PR_SET_PTRACER_ANY
    ("setpriority", (0, 0, 19), ALLOW), ("setpriority", (0, PPID, 19), EPERM), ("setpriority", (1, 0, 19), EPERM),
    ("setpriority", (2, 0, 19), EPERM),
    ("sched_setaffinity", (0,), ALLOW), ("sched_setaffinity", (PPID,), EPERM), ("sched_setparam", (PPID,), EPERM),
    ("sched_setscheduler", (PPID,), EPERM), ("sched_setattr", (PPID,), EPERM),
    ("kill", (PID, 0), ALLOW), ("kill", (PPID, 9), EPERM), ("kill", (0, 9), EPERM), ("kill", (-PID, 9), EPERM),
    ("tgkill", (PID, PID, 10), ALLOW), ("tgkill", (PPID, PPID, 10), EPERM), ("rt_sigqueueinfo", (PPID, 10), EPERM),
    ("tkill", (PID, 0), ALLOW), ("tkill", (PPID, 9), EPERM),                        # tkill names a tid: only the main
    #                                                                                 thread's (glibc signals with tgkill)
    ("prlimit64", (0, 4), ALLOW), ("prlimit64", (PPID, 4), EPERM),
    ("clone", (0x003D0F00,), ALLOW),                                                 # glibc's pthread_create flags
    ("clone", (0x01200011,), EPERM),                                                 # fork's: a new process
    ("clone", (C.CLONE_THREAD | 0x10000000,), EPERM),                                # a thread in a new user namespace
    ("clone", (0x003D0F00 | 0x00008000,), EPERM),                                    # CLONE_PARENT
    ("clone", (0x003D0F00 | 0x00004000,), EPERM),                                    # CLONE_VFORK
    ("clone", (0x003D0F00 | 0x00001000,), EPERM),                                    # CLONE_PIDFD
    ("clone", (0x003D0F00 | 0x80,), EPERM),                                          # CLONE_NEWTIME's bit: CSIGNAL here
    ("clone", (0x003D0F00 | 17,), EPERM),                                            # an exit signal (SIGCHLD)
    ("clone", (0x003D0F00 | (1 << 32),), EPERM),                                     # the high half
    ("clone", (0x003D0F00 | 0x00400000,), EPERM),                                    # CLONE_DETACHED: not glibc's
    ("clone", (C.CLONE_VM | C.CLONE_FS | C.CLONE_FILES,), EPERM),                    # shared memory, no thread: a process
    ("clone", (C.CLONE_THREAD,), EPERM), ("clone", (0,), EPERM),
    ("open", (0, os.O_RDONLY), ALLOW), ("open", (0, os.O_WRONLY), EPERM), ("openat", (-100, 0, os.O_RDONLY), ALLOW),
    ("openat", (-100, 0, os.O_RDONLY | os.O_CREAT), EPERM), ("openat", (-100, 0, os.O_APPEND), EPERM),
    ("openat", (-100, 0, C.O_TMPFILE | os.O_RDWR), EPERM), ("openat", (-100, 0, C.O_TMPFILE | os.O_WRONLY), EPERM),
    ("openat", (-100, 0, C.O_TMPFILE), ALLOW),                                       # read-only O_TMPFILE: EINVAL
])
def test_checked_calls_by_their_arguments(name, args, verdict):
    assert run(PROG, NUMBERS[name], args) == verdict


def _ioc(direction: int, kind: int, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (kind << 8) | nr


def test_ioctl_lets_through_only_the_listed_commands():
    """ioctl was a denylist of six commands, so FS_IOC_SETFLAGS (chattr), FS_IOC_FSSETXATTR and every other command
    nobody listed passed. Swept over the terminal, file-attribute, xfs, socket and btrfs command families, in each
    direction and size, only IOCTL_ALLOWED gets through."""
    allowed = set(C.IOCTL_ALLOWED.values())
    commands = {_ioc(d, kind, nr, size) for kind in (ord("T"), ord("f"), ord("X"), ord("v"), 0x89, 0x94)
                for nr in range(64) for d, size in ((0, 0), (1, 4), (1, 8), (2, 4), (2, 8), (2, 44), (3, 8))}
    commands |= allowed | {0x5401 + i for i in range(0x60)} | {0x8901 + i for i in range(0x60)}
    passed = {cmd for cmd in commands if run(PROG, NUMBERS["ioctl"], (0, cmd)) == ALLOW}
    assert passed == allowed


def test_the_second_round_found_let_through_are_refused():
    """Argon's second round by name: readlink reads a link's target past the wall; landlock_* and seccomp were left on
    after setup; the deadline's timer could be moved or deleted."""
    found = """readlink readlinkat seccomp landlock_create_ruleset landlock_add_rule landlock_restrict_self timer_create
        timer_settime timer_delete""".split()
    assert [n for n in found if run(PROG, NUMBERS[n]) != EPERM] == []


def test_fcntl_and_prctl_let_through_only_their_lists():
    """fcntl and prctl were denylists, so F_SETPIPE_SZ, PR_SET_PTRACER, PR_SET_MEMORY_MERGE, PR_SCHED_CORE and every
    command or option nobody listed passed. Swept, only FCNTL_ALLOWED and PRCTL_ALLOWED get through."""
    fcntl = {cmd for cmd in [*range(2048), *C.FCNTL_REFUSED.values()] if run(PROG, NUMBERS["fcntl"], (0, cmd)) == ALLOW}
    assert fcntl == set(C.FCNTL_ALLOWED.values())
    options = [*range(128), *C.PRCTL_REFUSED.values(), 0x59616D61, 0x53564D41, 0x41555856, 1 << 31]
    prctl = {opt for opt in options if run(PROG, NUMBERS["prctl"], (opt,)) == ALLOW}
    assert prctl == set(C.PRCTL_ALLOWED.values())


def test_clone_lets_through_only_glibcs_pthread_flags():
    """clone checked only that CLONE_THREAD was set and no namespace flag was, so CLONE_PARENT, CLONE_VFORK, CLONE_PIDFD,
    an exit signal and the high half passed. Now glibc's set passes, and adding any one other bit, or dropping CLONE_VM,
    CLONE_SIGHAND or CLONE_THREAD, is refused."""
    glibc = C.CLONE_PTHREAD
    assert glibc == 0x003D0F00 and run(PROG, NUMBERS["clone"], (glibc,)) == ALLOW
    for bit in range(64):
        if not glibc & (1 << bit):
            assert run(PROG, NUMBERS["clone"], (glibc | (1 << bit),)) == EPERM, bit
    for needed in (C.CLONE_VM, C.CLONE_SIGHAND, C.CLONE_THREAD):
        assert run(PROG, NUMBERS["clone"], (glibc & ~needed,)) == EPERM, needed


# ---- the confined child, for real (this machine has seccomp and Landlock: tests/test_pdf_wall.py)

def test_the_child_tries_each_escape_and_each_is_refused():
    """The selfcheck's escapes run inside the filter and the wall; unconfined, each succeeds or answers otherwise."""
    got = S.selfcheck()
    assert got["escapes"] == {**{k: "EPERM" for k in got["escapes"]}, "past_the_table": "ENOSYS"}
    assert {"fcntl_setown", "fchmodat2", "mknodat", "utimensat", "setxattr", "shmget", "msgget", "mq_open",
            "setpriority_parent", "prctl_pdeathsig", "ioctl_fs_ioc_setflags", "ioctl_fs_ioc_fssetxattr",
            "prctl_ptracer", "prctl_memory_merge", "prctl_subreaper", "prctl_sched_core_parent", "fcntl_setpipe_sz",
            "o_tmpfile", "readlink", "readlinkat", "seccomp", "landlock_create_ruleset", "timer_settime_deadline",
            "timer_delete_deadline"} <= set(got["escapes"])
    assert got["pdeathsig"] == signal.SIGKILL                       # ARG-1: it dies with its parent, and can't undo it
    # its own SIGKILL clock, set before the filter, still there after the probes tried to move and delete it
    assert 0 < got["deadline_after"] <= got["deadline"] <= S.DEADLINE_S
    # clone: a thread with glibc's flags, nothing else (each would be EINVAL unconfined: no CLONE_VM)
    assert {k: got["probes"][k] for k in ("thread", "clone3", "clone_newuser", "clone_parent", "clone_exit_signal",
                                          "clone_high_half")} == {"thread": "ok", "clone3": "ENOSYS",
                                                                  **dict.fromkeys(("clone_newuser", "clone_parent",
                                                                                   "clone_exit_signal",
                                                                                   "clone_high_half"), "EPERM")}
    assert got["memfd"] == {"write": "EFBIG", "ftruncate": "EPERM", "size": 0}   # RLIMIT_FSIZE 0 keeps it empty


def _orphan(tmp_path, args: list[str]) -> int:
    """The child started as a parent that died at once leaves it: nothing reads its stdout, and its stdin holds the
    whole input, already at its end."""
    r, w = os.pipe()
    os.close(r)
    try:
        proc = subprocess.Popen([sys.executable, "-I", "-B", "-m", S.MODULE, *args], stdin=subprocess.PIPE, stdout=w,
                                stderr=subprocess.DEVNULL, env={}, cwd=tmp_path, close_fds=True)
    finally:
        os.close(w)
    proc.stdin.write(S.canary_pdf())
    proc.stdin.close()
    return proc.wait()


def test_a_child_whose_parent_is_already_gone_kills_itself(tmp_path):
    """Argon's PDEATHSIG race: a parent that dies before the child asks for PR_SET_PDEATHSIG never sends it, and the
    PDF may already sit whole in the stdin pipe. The child checks that something still reads its stdout and sends
    itself SIGKILL when nothing does, before it reads stdin. Without the check it reads the PDF and fails only on the
    write (exit 1 or 120)."""
    assert _orphan(tmp_path, []) == -signal.SIGKILL
    assert _orphan(tmp_path, ["--confined"]) == -signal.SIGKILL


DEADLINE = """
import os, signal
from steward_pdf import confine
never_r, never_w = os.pipe()          # both ends held here, so the read below never returns: only the kill ends it
confine.deadline(1)
confine.install()
assert confine.probe_escapes(os.getppid())["timer_delete_deadline"] == "EPERM"
signal.pthread_sigmask(signal.SIG_BLOCK, set(signal.Signals) - {signal.SIGKILL, signal.SIGSTOP})
os.read(never_r, 1)
"""


def test_the_deadline_kills_a_child_that_blocks_every_signal(tmp_path):
    """The child's own clock: a taken-over child can't delete the timer, and blocking every signal doesn't stop
    SIGKILL. Here the deadline is 1 s and the child then blocks on a read that never returns: the kill ends it."""
    proc = subprocess.run([sys.executable, "-I", "-B", "-c", DEADLINE], cwd=tmp_path, env={}, capture_output=True,
                          timeout=60, check=False)
    assert proc.returncode == -signal.SIGKILL, proc.stderr


def test_a_confined_child_cant_signal_its_parent_through_a_files_owner(tmp_path):
    """ARG-2 as triage ran it: the child makes the parent the owner of its stdin with SIGUSR1 and O_ASYNC; the parent
    then writes to that pipe. Let through, the kernel signals the parent during the write."""
    got = []
    old = signal.signal(signal.SIGUSR1, lambda *_a: got.append(1))
    try:
        proc = subprocess.Popen([sys.executable, "-I", "-B", "-m", S.MODULE, "--selfcheck", "sigio"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env={},
                                cwd=tmp_path, close_fds=True)
        assert proc.stdout.readline() == b"ready\n"
        proc.stdin.write(b"x" * 4096)
        proc.stdin.flush()
        proc.stdin.close()
        rest = proc.stdout.read()
        assert proc.wait() == 0
    finally:
        signal.signal(signal.SIGUSR1, old)
    assert (got, json.loads(rest)) == ([], {"F_SETOWN": "EPERM", "F_SETSIG": "EPERM", "O_ASYNC": "ok"})


def test_metadata_calls_cant_touch_a_file_outside_the_childs_folder(tmp_path):
    """ARG-3 as triage ran it: fchmodat2 changed a 0600 file outside the folder to 0644 with the wall up. Landlock
    doesn't govern chmod, utime or xattr, so only the filter stands in the way."""
    key = tmp_path / "steward.key"
    key.write_bytes(b"k" * 32)
    key.chmod(0o600)
    os.utime(key, (1_000_000_000, 1_000_000_000))
    before = key.stat()
    out, code, _ = S._run(["--selfcheck", "outside", str(key)], b"", subprocess.Popen, threading.Timer, S.WALL_S,
                          S.OUT_CAP)
    assert code == 0 and json.loads(out) == {"fchmodat2": "EPERM", "chmod": "EPERM", "utimensat": "EPERM",
                                             "setxattr": "EPERM", "readlink": "EPERM",
                                             "newfstatat": "ok", "open": "EACCES"}   # the stated limit: a stat answers
    #                                                                                  outside the wall, an open doesn't
    after = key.stat()
    assert (after.st_mode, after.st_mtime_ns) == (before.st_mode, before.st_mtime_ns)
    assert os.listxattr(key) == []


class Broken:
    """A child's stdin whose reader went away: every write breaks, and so does the flush on close."""
    def __init__(self):
        self.closed = False

    def write(self, _b):
        raise BrokenPipeError()

    def close(self):
        self.closed = True
        raise BrokenPipeError()


def test_the_feeder_closes_the_pipe_when_the_child_stops_reading():
    """ARG-6 (1): a broken pipe skipped close(), leaving the fd to the garbage collector."""
    stream = Broken()
    S._feed(stream, b"x" * 10)
    assert stream.closed
