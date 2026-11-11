"""Kernel-enforced Linux boundary for patched Python tests, never for OAuth.

No fallback to workspace-write, monkeypatch-only networking, or root services.
The trusted launcher closes descriptors and supplies a clean environment before
this function is called. Every descendant inherits both irreversible filters.
"""
import ctypes
import errno
import os
from pathlib import Path
import platform
import resource

READ_FILE = 1 << 2
READ_DIR = 1 << 3
EXECUTE = 1
FS_HANDLED = (1 << 15) - 1  # Require ABI >=3, including REFER and TRUNCATE.
WORK_ACCESS = FS_HANDLED & ~(EXECUTE | (1 << 6) | (1 << 9) | (1 << 10) | (1 << 11))
DENIED_SYSCALLS = (
    'socket', 'socketpair', 'connect', 'bind', 'listen', 'accept', 'accept4',
    'sendto', 'sendmsg', 'sendmmsg', 'recvfrom', 'recvmsg', 'recvmmsg',
    'kill', 'tkill', 'tgkill', 'rt_sigqueueinfo', 'rt_tgsigqueueinfo',
    'pidfd_open', 'pidfd_getfd', 'pidfd_send_signal', 'ptrace',
    'process_vm_readv', 'process_vm_writev', 'process_madvise', 'process_mrelease',
    'setsid', 'setpgid', 'setpriority', 'sched_setaffinity', 'sched_setscheduler',
    'sched_setparam', 'sched_setattr', 'migrate_pages', 'move_pages',
    'mount', 'umount2', 'pivot_root', 'move_mount', 'open_tree', 'mount_setattr',
    'fsopen', 'fsconfig', 'fsmount', 'fspick', 'setns', 'unshare', 'chroot',
    'bpf', 'perf_event_open', 'keyctl', 'add_key', 'request_key', 'kcmp',
    'io_uring_setup', 'io_uring_enter', 'io_uring_register', 'open_by_handle_at',
    'shmget', 'shmat', 'shmctl', 'semget', 'semctl', 'semop', 'semtimedop',
    'msgget', 'msgsnd', 'msgrcv', 'msgctl', 'mq_open', 'mq_unlink', 'mq_notify',
    'mq_timedsend', 'mq_timedreceive', 'mq_getsetattr', 'clone3', 'execve', 'execveat')


class RuleSet(ctypes.Structure):
    _fields_ = [('handled_access_fs', ctypes.c_uint64)]


class PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int32)]


class ArgComparison(ctypes.Structure):
    _fields_ = [('arg', ctypes.c_uint), ('op', ctypes.c_int),
                ('datum_a', ctypes.c_uint64), ('datum_b', ctypes.c_uint64)]


def capabilities():
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'aarch64'):
        raise PermissionError('Validated Linux Landlock/seccomp platform required')
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 3:
        raise PermissionError('Landlock ABI >=3 required; no weaker fallback')
    seccomp = ctypes.CDLL('libseccomp.so.2', use_errno=True)
    return libc, seccomp, abi


def enforce(workspace, scratch, repository_metadata, python):
    """All paths are host-selected; the model cannot supply these arguments."""
    libc, seccomp, abi = capabilities()
    paths = [Path(x) for x in (workspace, scratch, repository_metadata)]
    if any(p.is_symlink() or not p.is_dir() for p in paths):
        raise PermissionError('Owned regular sandbox directories required')
    workspace, scratch, metadata = [p.resolve() for p in paths]
    job = workspace.parent
    if (workspace.name != 'worktree' or scratch != job/'tmp'
            or metadata != job/'repository/.git' or len({workspace, scratch, metadata}) != 3):
        raise PermissionError('Fixed per-task repository/worktree layout required')
    python = Path(python).resolve(strict=True)
    if not python.is_file() or not str(python).startswith('/usr/bin/python3'):
        raise PermissionError('Pinned system Python interpreter required')
    if libc.prctl(38, 1, 0, 0, 0):  # PR_SET_NO_NEW_PRIVS
        raise OSError(ctypes.get_errno(), 'NoNewPrivileges required')
    attr = RuleSet(FS_HANDLED)
    ruleset = libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if ruleset < 0:
        raise OSError(ctypes.get_errno(), 'Landlock ruleset creation failed')
    try:
        def add(path, rights):
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathRule(rights, fd)
                if libc.syscall(445, ruleset, 1, ctypes.byref(rule), 0):
                    raise OSError(ctypes.get_errno(), 'Landlock path rule rejected')
            finally:
                os.close(fd)
        for name in ('/usr', '/lib', '/lib64', '/opt/openclaw/venv'):
            if Path(name).is_dir():
                add(Path(name).resolve(), READ_FILE | READ_DIR)
        add(workspace, WORK_ACCESS)
        add(scratch, WORK_ACCESS)
        add(metadata, READ_FILE | READ_DIR)
        for name in ('/dev/null', '/dev/urandom', '/dev/random'):
            if Path(name).exists():
                add(name, READ_FILE | (2 if name == '/dev/null' else 0))
        if libc.syscall(446, ruleset, 0):
            raise OSError(ctypes.get_errno(), 'Landlock restriction failed')
    finally:
        os.close(ruleset)
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_syscall_resolve_name.restype = ctypes.c_int
    seccomp.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    seccomp.seccomp_rule_add.restype = ctypes.c_int
    seccomp.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
                                              ctypes.c_uint, ctypes.POINTER(ArgComparison)]
    seccomp.seccomp_rule_add_array.restype = ctypes.c_int
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_load.restype = ctypes.c_int
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = seccomp.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW, explicit denied syscalls below.
    if not ctx:
        raise MemoryError('seccomp context unavailable')
    try:
        for name in DENIED_SYSCALLS:
            number = seccomp.seccomp_syscall_resolve_name(name.encode())
            if number < 0:
                if name in ('socket', 'kill', 'ptrace', 'setsid', 'setpgid'):
                    raise PermissionError('Required syscall filter unavailable')
                continue
            if seccomp.seccomp_rule_add(ctx, 0x00050000 | errno.EPERM, number, 0):
                raise PermissionError('Syscall filter installation failed')
        # fcntl async-signal ownership must not become a peer-signal bypass.
        for cmd in (8, 10, 15):  # F_SETOWN, F_SETSIG, F_SETOWN_EX (Linux ABI).
            comparison = ArgComparison(1, 4, cmd, 0)  # SCMP_CMP_EQ
            if seccomp.seccomp_rule_add_array(ctx, 0x00050000 | errno.EPERM,
                    seccomp.seccomp_syscall_resolve_name(b'fcntl'), 1, ctypes.byref(comparison)):
                raise PermissionError('Async-signal filter failed')
        comparison = ArgComparison(0, 1, 0, 0)  # prlimit64(pid != 0), SCMP_CMP_NE.
        if seccomp.seccomp_rule_add_array(ctx, 0x00050000 | errno.EPERM,
                seccomp.seccomp_syscall_resolve_name(b'prlimit64'), 1, ctypes.byref(comparison)):
            raise PermissionError('Foreign resource-limit filter failed')
        if seccomp.seccomp_load(ctx):
            raise PermissionError('seccomp filter load failed')
    finally:
        seccomp.seccomp_release(ctx)
    for kind, cap in ((resource.RLIMIT_CORE, 0), (resource.RLIMIT_NOFILE, 128),
            (resource.RLIMIT_FSIZE, 8_000_000), (resource.RLIMIT_CPU, 60),
            (resource.RLIMIT_AS, 512 * 1024 * 1024), (resource.RLIMIT_NPROC, 128)):
        inherited = [v for v in resource.getrlimit(kind) if v != resource.RLIM_INFINITY]
        bound = min([cap, *inherited])  # Never raise an inherited soft or hard limit.
        resource.setrlimit(kind, (bound, bound))
    return {'landlock_abi': abi, 'seccomp': True, 'network': 'DENIED',
            'credential_and_production_paths': 'NOT_GRANTED', 'exec': 'DENIED_AFTER_TRUSTED_PYTHON_START'}
