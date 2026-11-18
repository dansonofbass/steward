"""The sandbox child's seccomp filter (spec P8). Installed by the child after its rlimits, its parent-death signal, its
deadline, its import of the PDF libraries (no input read yet) and the Landlock wall, and before it reads stdin:
`prctl(PR_SET_NO_NEW_PRIVS)`, the wall (landlock.restrict), then a hand-built classic-BPF program through `seccomp(2)`
with TSYNC. The filter goes on
last, so it can refuse landlock_* and seccomp themselves. Linux on x86_64 only (the NAS builds `linux/amd64`;
deploy.sh): anywhere else, or if the kernel refuses, install raises Unconfined and the child refuses the PDF.

It is an allowlist over the whole x86_64 table (x86_64.NUMBERS, Linux 6.18). Every number in the table has one class:
- ALLOW: what the child does to itself (memory, its threads and signals, time, the files it already holds or may open
  read-only, facts about itself), each group with its reason;
- CHECKED: allowed only with arguments the filter reads (see program): clone only with glibc's pthread flags (a thread,
  never a process, a namespace, CLONE_PARENT, CLONE_VFORK or CLONE_PIDFD); open and openat with no write flag; signals
  and prlimit64 only to itself; fcntl only with the commands in FCNTL_ALLOWED; ioctl only with the commands in
  IOCTL_ALLOWED (isatty, and facts about or flags of its own descriptors); prctl only with the PR_GET_* options in
  PRCTL_ALLOWED; setpriority and the sched_set* calls only on itself;
- NOSYS: clone3 and openat2, whose flags sit behind a pointer the filter can't read (glibc falls back to clone);
- DENY: everything else, answered EPERM, each group with its reason.
A number past the table answers ENOSYS, so a newer kernel's call (as fchmodat2 once was) is refused until it's classified
here, and glibc falls back as it does for clone3. A foreign arch (AUDIT_ARCH_I386, where socketcall would bundle the
socket calls, or any other) and x32 numbers (0x40000000 set) kill the process. tests/test_pdf_syscalls.py fails on a
number of the pinned table with no class.

Landlock doesn't cover metadata: chmod, chown, utime and xattr calls reach any path Steward's user owns, wall or no
wall, and file attributes (file_setattr by path, FS_IOC_SETFLAGS and FS_IOC_FSSETXATTR on a descriptor) reach any
file of that user's the child can open. For those this filter is the only defence: the calls are denied by name, and
the ioctls fall outside IOCTL_ALLOWED. readlink and readlinkat are denied for the same reason: Landlock lets them read
a link's target anywhere. mknod is denied here too, and the wall also refuses it. Landlock covers what seccomp can't: a
path's contents. Seccomp sees a path only as a pointer, so `open(path, O_RDONLY)` passes this filter whatever the
path; the child reads a PDF only once the Landlock wall is up too (sandbox.main).

A stated limit: stat, lstat, newfstatat, statx, access, faccessat, faccessat2 and statfs stay allowed, because Python's
imports and the PDF libraries need them, and Landlock doesn't cover them either. So a taken-over child can learn
whether a path outside the wall exists, and its metadata (type, size, owner, mode, times), but never what a file holds
or where a link points."""
from __future__ import annotations

import ctypes
import errno
import os
import signal
import struct
import sys

from steward_pdf.x86_64 import NUMBERS


class Unconfined(Exception):
    pass


AUDIT_ARCH_X86_64 = 0xC000003E
X32_BIT = 0x40000000
PR_SET_NO_NEW_PRIVS = 38
PR_SET_PDEATHSIG, PR_GET_PDEATHSIG, PR_GET_DUMPABLE, PR_GET_NAME, PR_GET_SECCOMP = 1, 2, 3, 16, 21
PR_GET_NO_NEW_PRIVS = 39
SYS_SECCOMP = NUMBERS["seccomp"]
SECCOMP_SET_MODE_FILTER = 1
SECCOMP_FILTER_FLAG_TSYNC = 1
RET_KILL_PROCESS = 0x80000000
RET_ERRNO = 0x00050000
RET_ALLOW = 0x7FFF0000
EPERM, ENOSYS = RET_ERRNO | errno.EPERM, RET_ERRNO | errno.ENOSYS
CLONE_VM, CLONE_FS, CLONE_FILES, CLONE_SIGHAND = 0x00000100, 0x00000200, 0x00000400, 0x00000800
CLONE_THREAD, CLONE_SYSVSEM, CLONE_SETTLS = 0x00010000, 0x00040000, 0x00080000
CLONE_PARENT_SETTID, CLONE_CHILD_CLEARTID = 0x00100000, 0x00200000
# What glibc's pthread_create passes to clone once clone3 answers ENOSYS (traced: 0x003D0F00). Nothing else passes:
# not the exit-signal byte (CSIGNAL, 0xFF), CLONE_PARENT, CLONE_VFORK, CLONE_PIDFD, a namespace flag, or a high bit.
CLONE_PTHREAD = (CLONE_VM | CLONE_FS | CLONE_FILES | CLONE_SIGHAND | CLONE_THREAD | CLONE_SYSVSEM | CLONE_SETTLS
                 | CLONE_PARENT_SETTID | CLONE_CHILD_CLEARTID)
CLONE_NEEDED = CLONE_VM | CLONE_SIGHAND | CLONE_THREAD                # a thread of this process, never a new one
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
TABLE_END = max(NUMBERS.values()) + 1                               # 470: the first number the table doesn't know
_LD, _JEQ, _JGE, _JSET, _RET = 0x20, 0x15, 0x35, 0x45, 0x06       # BPF_LD|W|ABS, BPF_JMP|{JEQ,JGE,JSET}|K, BPF_RET|K
_AND = 0x54                                                         # BPF_ALU|BPF_AND|BPF_K
_NR, _ARCH = 0, 4                                                   # offsets in struct seccomp_data


def _arg(i: int) -> int:
    return 16 + 8 * i                                               # the low 32 bits of args[i] (little-endian); each
    #                                                                 argument checked is an int in the kernel, except
    #                                                                 clone's flags, whose high half is checked too


def _arg_high(i: int) -> int:
    return 20 + 8 * i                                               # the high 32 bits of args[i]


def _names(text: str) -> tuple[str, ...]:
    return tuple(text.split())


ALLOW: dict[str, tuple[str, ...]] = {
    "memory, its own": _names("""brk mmap mprotect munmap mremap msync mincore madvise mlock munlock mlockall munlockall
        mlock2 pkey_mprotect pkey_alloc pkey_free membarrier get_mempolicy map_shadow_stack mseal memfd_create"""),
    # memfd_create: freed at exit, and RLIMIT_FSIZE 0 keeps it empty (ARG-7)
    "threads, signals and waiting, within itself": _names("""rt_sigaction rt_sigprocmask rt_sigreturn rt_sigpending
        rt_sigtimedwait rt_sigsuspend sigaltstack pause restart_syscall set_tid_address set_robust_list futex futex_waitv
        futex_wake futex_wait futex_requeue gettid rseq arch_prctl exit exit_group wait4 waitid sched_yield getcpu"""),
    # wait4, waitid: it has no child to wait for (no fork, and clone makes only threads), so they answer ECHILD
    "time and its own timers": _names("""nanosleep clock_nanosleep gettimeofday time clock_gettime clock_getres
        getitimer setitimer alarm timer_gettime timer_getoverrun timerfd_create timerfd_settime timerfd_gettime"""),
    "the files it holds: stdout, its pipes, and files it opened read-only": _names("""read write close fstat lseek
        pread64 pwrite64 readv writev preadv pwritev preadv2 pwritev2 dup dup2 dup3 close_range getdents getdents64
        readahead fadvise64 fsync fdatasync sync_file_range sendfile splice tee vmsplice copy_file_range cachestat poll
        select pselect6 ppoll epoll_create epoll_create1 epoll_ctl epoll_wait epoll_pwait epoll_pwait2 eventfd eventfd2
        signalfd signalfd4 pipe pipe2"""),
    # a write needs a writable fd: every open is read-only (CHECKED), so that's stdout and its own pipes; RLIMIT_FSIZE 0
    "paths, read only (what a path holds is the wall's; its metadata isn't: the stated limit above)":
        _names("stat lstat newfstatat statx access faccessat faccessat2 getcwd chdir fchdir statfs fstatfs umask"),
    "facts about itself, and lowering its own limits": _names("""getpid getppid getuid geteuid getgid getegid getgroups
        getresuid getresgid getpgrp getpgid getsid getpriority getrlimit setrlimit getrusage times sysinfo uname capget
        sched_getparam sched_getscheduler sched_get_priority_max sched_get_priority_min sched_rr_get_interval
        sched_getaffinity sched_getattr ioprio_get getrandom"""),
    # setrlimit: the child sets every limit it cares about with soft == hard, so it can only go lower
}
CHECKED = _names("""clone open openat kill tkill tgkill rt_sigqueueinfo rt_tgsigqueueinfo prlimit64 fcntl ioctl prctl
    setpriority sched_setaffinity sched_setparam sched_setscheduler sched_setattr""")
NOSYS = _names("clone3 openat2")
DENY: dict[str, tuple[str, ...]] = {
    "the network": _names("""socket socketpair connect bind listen accept accept4 shutdown getsockname getpeername
        setsockopt getsockopt sendto recvfrom sendmsg recvmsg sendmmsg recvmmsg io_uring_setup io_uring_enter
        io_uring_register"""),                                     # io_uring's ops would get round the socket rules
    "running programs": _names("fork vfork execve execveat"),
    "reading a link's target (Landlock doesn't cover readlink; no read or render reads one once the filter is on)":
        _names("readlink readlinkat"),
    "narrowing itself: the wall goes up before the filter, so nothing is left to add once it's on":
        _names("seccomp landlock_create_ruleset landlock_add_rule landlock_restrict_self"),
    "moving or removing its deadline (a POSIX timer that sends SIGKILL, set before the filter: sandbox._limit)":
        _names("timer_create timer_settime timer_delete"),
    "other processes": _names("""ptrace process_vm_readv process_vm_writev process_madvise process_mrelease kcmp
        pidfd_open pidfd_getfd pidfd_send_signal get_robust_list setpgid setsid ioprio_set migrate_pages move_pages"""),
    "identity": _names("setuid setgid setreuid setregid setgroups setresuid setresgid setfsuid setfsgid capset"),
    "mounts and namespaces": _names("""mount umount2 pivot_root chroot unshare setns open_tree open_tree_attr move_mount
        fsopen fsconfig fsmount fspick mount_setattr name_to_handle_at open_by_handle_at"""),
    "changing files, their metadata included (Landlock doesn't cover chmod, chown, utime, xattr)": _names("""creat
        unlink unlinkat rename renameat renameat2 rmdir link linkat symlink symlinkat mkdir mkdirat mknod mknodat chmod
        fchmod fchmodat fchmodat2 chown fchown lchown fchownat truncate ftruncate fallocate utime utimes futimesat
        utimensat setxattr lsetxattr fsetxattr getxattr lgetxattr fgetxattr listxattr llistxattr flistxattr removexattr
        lremovexattr fremovexattr setxattrat getxattrat listxattrat removexattrat file_getattr file_setattr flock"""),
    "shared memory and queues that outlive it (ARG-7)": _names("""shmget shmat shmctl shmdt semget semop semctl
        semtimedop msgget msgsnd msgrcv msgctl mq_open mq_unlink mq_timedsend mq_timedreceive mq_notify
        mq_getsetattr"""),
    "kernel surface and privilege": _names("""bpf perf_event_open userfaultfd keyctl add_key request_key init_module
        finit_module delete_module create_module get_kernel_syms query_module kexec_load kexec_file_load iopl ioperm
        modify_ldt personality quotactl quotactl_fd swapon swapoff reboot acct settimeofday clock_settime clock_adjtime
        adjtimex sethostname setdomainname syslog vhangup uselib ustat sysfs _sysctl nfsservctl lookup_dcookie
        fanotify_init fanotify_mark inotify_init inotify_init1 inotify_add_watch inotify_rm_watch mbind set_mempolicy
        set_mempolicy_home_node memfd_secret lsm_get_self_attr lsm_set_self_attr lsm_list_modules io_setup io_destroy
        io_getevents io_submit io_cancel io_pgetevents sync syncfs statmount listmount remap_file_pages"""),
    "not implemented on x86_64": _names("""getpmsg putpmsg afs_syscall tuxcall security vserver epoll_ctl_old
        epoll_wait_old set_thread_area get_thread_area"""),
    "uprobes (the kernel passes these two through seccomp from its own trampoline; anywhere else they fail or kill)":
        _names("uretprobe uprobe"),
}

# CHECKED's argument rules.
# fcntl is an allowlist: a descriptor's flags and status flags, and reads. No read or render calls fcntl once the filter
# is on (traced); these are what Python's os module asks (dup, set_inheritable, set_blocking).
FCNTL_ALLOWED = {"F_DUPFD": 0, "F_GETFD": 1, "F_SETFD": 2, "F_GETFL": 3, "F_SETFL": 4, "F_GETLK": 5,
                 "F_OFD_GETLK": 36, "F_DUPFD_CLOEXEC": 1030, "F_GETPIPE_SZ": 1032, "F_GET_SEALS": 1034}
# Commands a taken-over child would try, which the allowlist refuses: signals to others (ARG-2), locks and leases, and
# a pipe's kernel buffer grown past its default.
FCNTL_REFUSED = {"F_SETLK": 6, "F_SETLKW": 7, "F_SETOWN": 8, "F_SETSIG": 10, "F_SETOWN_EX": 15, "F_OFD_SETLK": 37,
                 "F_OFD_SETLKW": 38, "F_SETLEASE": 1024, "F_NOTIFY": 1026, "F_SETPIPE_SZ": 1031, "F_ADD_SEALS": 1033}
# ioctl is an allowlist: a command not here answers EPERM, whatever driver or file system would read it. Traced on the
# child's reads and renders (8 statements, a password PDF, a broken one, renders of pages 1 and 2) the only ioctl
# after the filter is TCGETS; the others read a fact about a descriptor or change a flag of the child's own descriptor,
# for a Python or glibc that asks them where this one didn't.
IOCTL_ALLOWED = {
    "TCGETS": 0x5401,           # isatty(), which io.open asks of every file it opens
    "TCGETS2": 0x802C542A,      # the same, for a glibc whose tcgetattr reads struct termios2
    "TIOCGWINSZ": 0x5413,       # a terminal's size: reads only
    "FIONREAD": 0x541B,         # how many bytes wait on a descriptor: reads only
    "FIONBIO": 0x5421,          # its own descriptor's O_NONBLOCK
    "FIONCLEX": 0x5450,         # its own descriptor's close-on-exec (CPython's os.set_inheritable on Linux)
    "FIOCLEX": 0x5451,
}
# Commands a taken-over child would try, which the allowlist refuses: signals to others through a file's owner, typing
# into a terminal, and file attributes Landlock doesn't cover (FS_IOC_SETFLAGS can set or clear immutable and
# append-only; FS_IOC_FSSETXATTR sets project ids and the same flags). probe_escapes tries these four for real.
IOCTL_ESCAPES = {"FIOSETOWN": 0x8901, "SIOCSPGRP": 0x8902, "TIOCSPGRP": 0x5410, "TIOCSTI": 0x5412,
                 "TIOCLINUX": 0x541C, "FIOASYNC": 0x5452, "FS_IOC_SETFLAGS": 0x40086602,
                 "FS_IOC_FSSETXATTR": 0x401C5820, "FS_IOC_SETVERSION": 0x40087602, "FICLONE": 0x40049409}
# prctl is an allowlist of facts about itself. No read or render calls prctl once the filter is on (traced); the
# selfcheck reads PR_GET_PDEATHSIG, and mode() reads PR_GET_SECCOMP.
PRCTL_ALLOWED = {"PR_GET_PDEATHSIG": PR_GET_PDEATHSIG, "PR_GET_DUMPABLE": PR_GET_DUMPABLE, "PR_GET_NAME": PR_GET_NAME,
                 "PR_GET_SECCOMP": PR_GET_SECCOMP, "PR_GET_NO_NEW_PRIVS": PR_GET_NO_NEW_PRIVS}
# Options the allowlist refuses that a taken-over child would try: undoing dying with its parent (ARG-1), letting any
# process of its user ptrace it, KSM page merging (a side channel across processes), its core-scheduling cookie pushed
# onto the parent, and becoming a subreaper.
PRCTL_REFUSED = {"PR_SET_PDEATHSIG": PR_SET_PDEATHSIG, "PR_SET_DUMPABLE": 4, "PR_SET_CHILD_SUBREAPER": 36,
                 "PR_SET_NO_NEW_PRIVS": PR_SET_NO_NEW_PRIVS, "PR_SCHED_CORE": 62, "PR_SET_MEMORY_MERGE": 67,
                 "PR_SET_PTRACER": 0x59616D61, "PR_SET_VMA": 0x53564D41}
OPENS = {"open": 1, "openat": 2}                                    # name: the flags argument
SELF_PID = ("kill", "tkill", "tgkill", "rt_sigqueueinfo", "rt_tgsigqueueinfo")   # argument 0 is the child's own pid
SELF_ZERO = ("prlimit64", "sched_setaffinity", "sched_setparam", "sched_setscheduler", "sched_setattr")  # pid 0: itself

# The selfcheck calls these raw, with zero arguments, once the filter is on. Left out: fork and vfork (left to the
# Python probe, so a broken filter can't fork the child), the uprobes (the kernel lets them through and kills the
# caller), and the IPC calls that would make or wait on a queue under a broken filter (probe_escapes tries those safely).
# seccomp(0, 0, 0) would turn on strict mode under a broken filter, so probe_escapes asks SECCOMP_GET_ACTION_AVAIL.
UNPROBED = frozenset({"fork", "vfork", "uretprobe", "uprobe", "msgget", "msgrcv", "semop", "semtimedop", "seccomp"})
PROBED = tuple(n for names in DENY.values() for n in names if n not in UNPROBED)


def denied() -> list[str]:
    return [n for names in DENY.values() for n in names]


def allowed() -> list[str]:
    return [n for names in ALLOW.values() for n in names]


def _s(code: int, k: int) -> tuple[int, int, int, int]:
    return code, 0, 0, k


def _j(code: int, k: int, jt: int, jf: int) -> tuple[int, int, int, int]:
    return code, jt, jf, k


def _for(nr: int, body: list) -> list:
    """body runs for syscall nr only; every other syscall skips it with the number still loaded."""
    return [_j(_JEQ, nr, 0, len(body)), *body]


def _allow_values(nr: int, arg: int, values) -> list:
    """nr is allowed only when argument arg is one of values."""
    body = [_s(_LD, _arg(arg))]
    for v in values:
        body += [_j(_JEQ, v, 0, 1), _s(_RET, RET_ALLOW)]
    return _for(nr, [*body, _s(_RET, EPERM)])


def _only(nr: int, conds: list[tuple[int, int]]) -> list:
    """nr is allowed only when every (argument, value) holds."""
    body = []
    for i, (arg, value) in enumerate(conds):
        body += [_s(_LD, _arg(arg)), _j(_JEQ, value, 0, 2 * (len(conds) - 1 - i) + 1)]
    return _for(nr, [*body, _s(_RET, RET_ALLOW), _s(_RET, EPERM)])


def program(pid: int) -> list[tuple[int, int, int, int]]:
    prog = [_s(_LD, _ARCH), _j(_JEQ, AUDIT_ARCH_X86_64, 1, 0), _s(_RET, RET_KILL_PROCESS),
            _s(_LD, _NR), _j(_JGE, X32_BIT, 0, 1), _s(_RET, RET_KILL_PROCESS),
            _j(_JGE, TABLE_END, 0, 1), _s(_RET, ENOSYS)]
    prog += _for(NUMBERS["clone"], [_s(_LD, _arg(0)),               # clone: no flag outside glibc's pthread set,
                                    _j(_JSET, ~CLONE_PTHREAD & 0xFFFFFFFF, 4, 0),
                                    _s(_AND, CLONE_NEEDED),             # a thread of this process,
                                    _j(_JEQ, CLONE_NEEDED, 0, 2),
                                    _s(_LD, _arg_high(0)),              # and nothing in the high half
                                    _j(_JEQ, 0, 1, 0),
                                    _s(_RET, EPERM), _s(_RET, RET_ALLOW)])
    for name, flags in OPENS.items():
        prog += _for(NUMBERS[name], [_s(_LD, _arg(flags)), _j(_JSET, WRITE_FLAGS, 0, 1), _s(_RET, EPERM),
                                     _s(_RET, RET_ALLOW)])
    for name in SELF_PID:
        prog += _only(NUMBERS[name], [(0, pid)])
    for name in SELF_ZERO:
        prog += _only(NUMBERS[name], [(0, 0)])
    prog += _only(NUMBERS["setpriority"], [(0, 0), (1, 0)])         # PRIO_PROCESS, who 0: itself (PRIO_PGRP 0 would
    #                                                                 reach the parent, which shares its group)
    prog += _allow_values(NUMBERS["fcntl"], 1, FCNTL_ALLOWED.values())  # the command is an unsigned int in the kernel
    prog += _allow_values(NUMBERS["ioctl"], 1, IOCTL_ALLOWED.values())  # the same
    prog += _allow_values(NUMBERS["prctl"], 0, PRCTL_ALLOWED.values())  # the option is an int
    for name in NOSYS:
        prog += [_j(_JEQ, NUMBERS[name], 0, 1), _s(_RET, ENOSYS)]
    for name in allowed():
        prog += [_j(_JEQ, NUMBERS[name], 0, 1), _s(_RET, RET_ALLOW)]
    return [*prog, _s(_RET, EPERM)]                                 # DENY, and the holes in the table


class _Fprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]


def _machine() -> str:
    return os.uname().machine


def _libc():
    return ctypes.CDLL(None, use_errno=True)


def no_new_privs() -> None:
    """PR_SET_NO_NEW_PRIVS, which landlock_restrict_self and seccomp both need, or raise Unconfined."""
    if sys.platform != "linux" or _machine() != "x86_64":
        raise Unconfined("platform")
    libc = _libc()
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise Unconfined("no_new_privs")


def install() -> None:
    """Confine this process (and any thread it starts) for good, or raise Unconfined. The last step of the child's
    setup: once it's on, the filter refuses landlock_* and seccomp, so the wall must already be up."""
    no_new_privs()
    libc = _libc()
    prog = program(os.getpid())
    buf = ctypes.create_string_buffer(b"".join(struct.pack("=HBBI", *ins) for ins in prog))
    fprog = _Fprog(len(prog), ctypes.cast(buf, ctypes.c_void_p))
    libc.syscall.argtypes = [ctypes.c_long, ctypes.c_long, ctypes.c_long, ctypes.c_void_p]
    if libc.syscall(SYS_SECCOMP, SECCOMP_SET_MODE_FILTER, SECCOMP_FILTER_FLAG_TSYNC, ctypes.byref(fprog)) != 0:
        raise Unconfined("seccomp")


def orphaned() -> bool:
    """True when nothing reads this process's stdout any more: the parent that held the pipe's other end has died."""
    import select
    poll = select.poll()
    poll.register(1, select.POLLOUT)
    return any(ev & (select.POLLERR | select.POLLHUP | select.POLLNVAL) for _, ev in poll.poll(0))


def die_with_parent(sig: int) -> None:
    """ARG-1: the kernel sends sig to this process when the thread that started it ends. Steward's _run starts the child
    and waits for it in that one thread, so the thread outlives the child unless the parent process dies. Set before
    the filter, which then refuses PR_SET_PDEATHSIG, so a taken-over child can't undo it. A parent that died before
    this call never sends it (the child went to a reaper first, and its pipes may still hold a whole PDF), so the child
    then checks that something still reads its stdout, and sends itself sig when nothing does. A parent that dies after
    the call sends sig itself."""
    if sys.platform != "linux":
        return
    libc = _libc()
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl(PR_SET_PDEATHSIG, sig, 0, 0, 0)
    if orphaned():
        os.kill(os.getpid(), sig)


CLOCK_MONOTONIC, SIGEV_SIGNAL = 1, 0
_timer: int | None = None                                           # deadline()'s POSIX timer


def deadline(seconds: int) -> None:
    """SIGKILL to this whole process `seconds` from now, from a POSIX timer on CLOCK_MONOTONIC: the child's own clock,
    which holds when the parent's timer never fires (a parent that hangs, or one that died before die_with_parent).
    SIGKILL can't be blocked, caught or ignored, and the filter refuses timer_create, timer_settime and timer_delete,
    so a taken-over child can't move or remove it. Raises OSError when the kernel refuses."""
    global _timer
    if sys.platform != "linux":
        return
    fn = _raw()
    event = ctypes.create_string_buffer(struct.pack("=qii48x", 0, signal.SIGKILL, SIGEV_SIGNAL), 64)  # struct sigevent
    timer = ctypes.c_int(-1)
    if fn(ctypes.c_long(NUMBERS["timer_create"]), ctypes.c_long(CLOCK_MONOTONIC), event, ctypes.byref(timer)) != 0:
        raise OSError(ctypes.get_errno(), "timer_create")
    spec = ctypes.create_string_buffer(struct.pack("=qqqq", 0, 0, seconds, 0), 32)       # struct itimerspec, one shot
    if fn(ctypes.c_long(NUMBERS["timer_settime"]), ctypes.c_long(timer.value), ctypes.c_long(0), spec, None) != 0:
        raise OSError(ctypes.get_errno(), "timer_settime")
    _timer = timer.value


def deadline_left() -> float:
    """Seconds until deadline()'s SIGKILL, or -1 when there's no deadline."""
    if _timer is None:
        return -1
    spec = ctypes.create_string_buffer(32)
    if _raw()(ctypes.c_long(NUMBERS["timer_gettime"]), ctypes.c_long(_timer), spec) != 0:
        return -1
    _i, _n, sec, nsec = struct.unpack("=qqqq", spec.raw)
    return sec + nsec / 1e9


def parent_death_signal() -> int:
    """The signal die_with_parent set (0 when none), or -1 when it can't be read."""
    if sys.platform != "linux":
        return -1
    libc = _libc()
    out = ctypes.c_int(-1)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    return out.value if libc.prctl(PR_GET_PDEATHSIG, ctypes.byref(out), 0, 0, 0) == 0 else -1


def mode() -> int:
    """This process's seccomp mode as the kernel tells it (PR_GET_SECCOMP: 0 none, 2 filter), or -1 if it can't say.
    Asked through prctl, which the filter allows, because the wall keeps /proc out."""
    if sys.platform != "linux":
        return -1
    libc = _libc()
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    got = libc.prctl(PR_GET_SECCOMP, 0, 0, 0, 0)
    return got if got >= 0 else -1


def _raw():
    fn = _libc().syscall
    fn.restype, fn.argtypes = ctypes.c_long, None
    return fn


def _call(fn, nr: int, *args) -> str:
    """One raw syscall: its errno's name, or "ok"."""
    ctypes.set_errno(0)
    r = fn(ctypes.c_long(nr), *(ctypes.c_long(a) if isinstance(a, int) else a for a in args))
    return errno.errorcode.get(ctypes.get_errno(), "?") if r == -1 else "ok"


def probe_raw() -> dict[str, str]:
    """Each PROBED syscall, called with zero arguments: its errno's name (or "ok"). Run only once confined."""
    fn = _raw()
    return {name: _call(fn, NUMBERS[name], 0, 0, 0, 0, 0, 0) for name in PROBED}


CLONE_PARENT, CLONE_NEWUSER, SIGCHLD = 0x00008000, 0x10000000, 17


def probe_edges() -> dict[str, str]:
    """clone3 (ENOSYS, so glibc falls back to clone), and clones with CLONE_THREAD plus a flag outside glibc's pthread
    set (EPERM). None of them has CLONE_VM, so unconfined each is EINVAL: a broken filter can't start anything here."""
    fn = _raw()
    return {"clone3": _call(fn, NUMBERS["clone3"], 0, 0, 0, 0, 0, 0),
            "clone_newuser": _call(fn, NUMBERS["clone"], CLONE_NEWUSER | CLONE_THREAD, 0, 0, 0, 0, 0),
            "clone_parent": _call(fn, NUMBERS["clone"], CLONE_PARENT | CLONE_THREAD, 0, 0, 0, 0, 0),
            "clone_exit_signal": _call(fn, NUMBERS["clone"], SIGCHLD | CLONE_THREAD, 0, 0, 0, 0, 0),
            "clone_high_half": _call(fn, NUMBERS["clone"], (1 << 32) | CLONE_THREAD, 0, 0, 0, 0, 0)}


def probe_memfd() -> dict:
    """memfd_create stays allowed: RLIMIT_FSIZE 0 keeps what it makes empty (a write answers EFBIG, as it does on any
    file), and ftruncate and fallocate are refused. Run only once confined."""
    fd = os.memfd_create("steward-probe")
    try:
        try:
            os.write(fd, b"x" * 4096)
            write = "ok"
        except OSError as e:
            write = errno.errorcode.get(e.errno or 0, "?")
        grow = _call(_raw(), NUMBERS["ftruncate"], fd, 1 << 20)
        return {"write": write, "ftruncate": grow, "size": os.fstat(fd).st_size}
    finally:
        os.close(fd)


AT_FDCWD = -100
S_IFIFO = 0o010000
PRIO_PROCESS, PRIO_PGRP = 0, 1
IOPRIO_WHO_PROCESS = 1
NO_SUCH_KEY = 0x53545744                                            # a SysV key nothing uses: ENOENT unconfined
NO_SUCH_PGRP = 0x7FFFFFFE
O_TMPFILE = 0o20000000 | os.O_DIRECTORY
SECCOMP_GET_ACTION_AVAIL = 2


def probe_escapes(ppid: int) -> dict[str, str]:
    """What a taken-over child would try next (ARG-2, ARG-3, ARG-7, ARG-1, and Argon's second round), each with
    arguments that do nothing, or answer something other than EPERM, if the filter let it through: signals to the parent
    through a file's owner, metadata changes Landlock doesn't cover, shared memory and queues, scheduling the parent,
    undoing the parent-death signal, prctl options past the allowlist, a pipe grown, an O_TMPFILE, a link read, more
    Landlock or seccomp, moving or deleting the deadline, and a number past the table. Run only once confined, inside
    the child's own empty folder."""
    fn = _raw()
    owner = ctypes.create_string_buffer(struct.pack("=ii", 1, ppid))            # struct f_owner_ex: F_OWNER_PID
    lock = ctypes.create_string_buffer(struct.pack("=hh4xqqi4x", 0, 0, 0, 0, 0))  # struct flock: F_RDLCK, whole file
    pid = ctypes.c_int(ppid)
    flags = ctypes.create_string_buffer(8)                                      # FS_IOC_SETFLAGS: no flags
    fsx = ctypes.create_string_buffer(28)                                       # struct fsxattr, all zero
    nice = 20 - fn(ctypes.c_long(NUMBERS["getpriority"]), ctypes.c_long(PRIO_PROCESS), ctypes.c_long(ppid))
    cookie = ctypes.byref(ctypes.c_ulonglong(0))
    link = ctypes.create_string_buffer(256)
    action = ctypes.c_uint(RET_ALLOW)
    timer = -1 if _timer is None else _timer
    later = ctypes.create_string_buffer(struct.pack("=qqqq", 0, 0, 3600, 0), 32)  # the deadline an hour off
    calls = {
        "fcntl_setown": ("fcntl", 0, FCNTL_REFUSED["F_SETOWN"], ppid),
        "fcntl_setown_ex": ("fcntl", 0, FCNTL_REFUSED["F_SETOWN_EX"], owner),
        "fcntl_setsig": ("fcntl", 0, FCNTL_REFUSED["F_SETSIG"], 10),
        "fcntl_setlk": ("fcntl", 0, FCNTL_REFUSED["F_SETLK"], lock),
        "fcntl_setlease": ("fcntl", 0, FCNTL_REFUSED["F_SETLEASE"], 0),
        "ioctl_fiosetown": ("ioctl", 0, IOCTL_ESCAPES["FIOSETOWN"], ctypes.byref(pid)),
        "ioctl_tiocsti": ("ioctl", 0, IOCTL_ESCAPES["TIOCSTI"], b"x"),
        "ioctl_fs_ioc_setflags": ("ioctl", 0, IOCTL_ESCAPES["FS_IOC_SETFLAGS"], flags),   # stdin is a pipe: ENOTTY
        "ioctl_fs_ioc_fssetxattr": ("ioctl", 0, IOCTL_ESCAPES["FS_IOC_FSSETXATTR"], fsx),  # if let through
        "flock": ("flock", 0, 1),
        "fchmodat2": ("fchmodat2", AT_FDCWD, b".", 0o700, 0),
        "mknodat": ("mknodat", AT_FDCWD, b"fifo", S_IFIFO | 0o600, 0),
        "utimensat": ("utimensat", AT_FDCWD, b".", None, 0),
        "setxattr": ("setxattr", b".", b"user.steward", b"x", 1, 0),
        "file_setattr": ("file_setattr", AT_FDCWD, b".", None, 0, 0),
        "shmget": ("shmget", NO_SUCH_KEY, 0, 0),
        "msgget": ("msgget", NO_SUCH_KEY, 0),
        "semget": ("semget", NO_SUCH_KEY, 0, 0),
        "mq_open": ("mq_open", b"steward-probe", os.O_RDONLY, 0, None),
        "setpriority_parent": ("setpriority", PRIO_PROCESS, ppid, nice),         # its own value: no change if let in
        "setpriority_group": ("setpriority", PRIO_PGRP, NO_SUCH_PGRP, 19),
        "sched_setaffinity_parent": ("sched_setaffinity", ppid, 0, None),
        "sched_setscheduler_parent": ("sched_setscheduler", ppid, 0, None),
        "ioprio_set_parent": ("ioprio_set", IOPRIO_WHO_PROCESS, ppid, 0),
        "prctl_pdeathsig": ("prctl", PR_SET_PDEATHSIG, 0),
        "prctl_ptracer": ("prctl", PRCTL_REFUSED["PR_SET_PTRACER"], 0),         # 0 clears it: no change if let in
        "prctl_memory_merge": ("prctl", PRCTL_REFUSED["PR_SET_MEMORY_MERGE"], 0),
        "prctl_subreaper": ("prctl", PRCTL_REFUSED["PR_SET_CHILD_SUBREAPER"], 0),
        "prctl_sched_core_parent": ("prctl", PRCTL_REFUSED["PR_SCHED_CORE"], 0, ppid, 0, cookie),  # PR_SCHED_CORE_GET
        "fcntl_setpipe_sz": ("fcntl", 0, FCNTL_REFUSED["F_SETPIPE_SZ"], 1 << 16),  # a pipe's default: no change
        "o_tmpfile": ("openat", AT_FDCWD, b".", O_TMPFILE | os.O_RDWR, 0o600),  # the wall would answer EACCES
        "readlink": ("readlink", b"/proc/self/exe", link, 256),                 # the wall doesn't cover it
        "readlinkat": ("readlinkat", AT_FDCWD, b"/proc/self/exe", link, 256),
        "seccomp": ("seccomp", SECCOMP_GET_ACTION_AVAIL, 0, ctypes.byref(action)),  # reads only, if let in
        "landlock_create_ruleset": ("landlock_create_ruleset", None, 0, 1),     # Landlock's ABI, if let in
        "timer_settime_deadline": ("timer_settime", timer, 0, later, None),
        "timer_delete_deadline": ("timer_delete", timer),
    }
    out = {name: _call(fn, NUMBERS[call[0]], *call[1:]) for name, call in calls.items()}
    out["past_the_table"] = _call(fn, TABLE_END, 0, 0, 0, 0, 0, 0)
    return out


def probe_outside(path: str) -> dict[str, str]:
    """The calls Landlock doesn't cover, aimed at a file outside the child's folder that its user owns (ARG-3): the
    metadata changes, each of which would change the file if let through, and readlink (EINVAL on a file, if let
    through). Then the stated limit, pinned so the docs stay exact: a stat outside the wall answers, an open doesn't."""
    fn = _raw()
    p = os.fsencode(path)
    link = ctypes.create_string_buffer(256)
    st = ctypes.create_string_buffer(256)                                       # struct stat is 144 bytes
    return {"fchmodat2": _call(fn, NUMBERS["fchmodat2"], AT_FDCWD, p, 0o644, 0),
            "chmod": _call(fn, NUMBERS["chmod"], p, 0o644),
            "utimensat": _call(fn, NUMBERS["utimensat"], AT_FDCWD, p, None, 0),
            "setxattr": _call(fn, NUMBERS["setxattr"], p, b"user.steward", b"x", 1, 0),
            "readlink": _call(fn, NUMBERS["readlink"], p, link, 256),
            "newfstatat": _call(fn, NUMBERS["newfstatat"], AT_FDCWD, p, st, 0),
            "open": _call(fn, NUMBERS["openat"], AT_FDCWD, p, os.O_RDONLY, 0)}


def x32_call() -> None:
    """getpid with the x32 bit set: the filter kills the process (SIGSYS) before it returns."""
    libc = _libc()
    libc.syscall.argtypes = [ctypes.c_long]
    libc.syscall(X32_BIT | NUMBERS["getpid"])
