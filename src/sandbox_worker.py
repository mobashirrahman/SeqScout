"""Trusted Linux bootstrap. Apply irreversible kernel restrictions before agent code.

Called by isolation.py using system Python -I -S, a cleared environment and
closed inherited descriptors. No model-written code runs during setup.
"""
import ctypes
import errno
import json
import os
import platform
import resource
import sys
from pathlib import Path

READ_FILE, READ_DIR = 1 << 2, 1 << 3
WRITE_FILE, TRUNCATE = 1 << 1, 1 << 14
SCRATCH_ACCESS = (READ_FILE | READ_DIR | WRITE_FILE | TRUNCATE |
                  (1 << 4) | (1 << 5) | (1 << 7) | (1 << 8) |
                  (1 << 12) | (1 << 13))

# Only computation, bounded file I/O and local interpreter operations. Sockets,
# process/thread creation, exec, ptrace, io_uring, mount and privilege changes
# receive EPERM because they have no allow rule.
ALLOWED_SYSCALLS = (
    "read", "write", "readv", "writev", "close", "close_range",
    "open", "openat", "openat2", "lseek", "pread64", "pwrite64",
    "stat", "lstat", "fstat", "newfstatat", "statx", "getdents", "getdents64",
    "readlink", "readlinkat", "access", "faccessat", "faccessat2",
    "mkdir", "mkdirat", "rmdir", "unlink", "unlinkat", "rename", "renameat", "renameat2",
    "symlink", "symlinkat", "link", "linkat", "truncate", "ftruncate", "fsync", "fdatasync",
    "dup", "dup2", "dup3", "pipe", "pipe2", "getcwd", "umask",
    "mmap", "mmap2", "munmap", "mprotect", "mremap", "madvise", "brk",
    "rt_sigaction", "rt_sigprocmask", "rt_sigreturn", "sigaltstack",
    "futex", "futex_time64", "set_robust_list", "set_tid_address", "rseq",
    "clock_gettime", "clock_gettime64", "gettimeofday", "time", "times", "getrusage",
    "nanosleep", "clock_nanosleep", "clock_nanosleep_time64", "getrandom",
    "poll", "ppoll", "select", "pselect6", "epoll_create1", "epoll_ctl", "epoll_wait", "epoll_pwait",
    "getpid", "getppid", "gettid", "getuid", "geteuid", "getgid", "getegid",
    "getrlimit", "sched_getaffinity", "sched_yield", "uname", "restart_syscall",
    "exit", "exit_group",
)


class Ruleset(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64),
                ("handled_access_net", ctypes.c_uint64), ("scoped", ctypes.c_uint64)]


class PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


class ArgCompare(ctypes.Structure):
    _fields_ = [("arg", ctypes.c_uint), ("op", ctypes.c_int),
                ("datum_a", ctypes.c_uint64), ("datum_b", ctypes.c_uint64)]


def check(result, operation):
    if result < 0:
        raise OSError(ctypes.get_errno(), operation)
    return result


def restrict_files(libc, root, runtime, runtime_dirs, input_files):
    if platform.machine() not in ("x86_64", "aarch64"):
        raise RuntimeError("supported sandbox architectures: x86_64 and aarch64")
    libc.syscall.restype = ctypes.c_long
    abi = check(libc.syscall(444, ctypes.c_void_p(), ctypes.c_size_t(0), ctypes.c_uint(1)), "Landlock ABI probe")
    if abi < 6:
        raise RuntimeError(f"Landlock ABI >= 6 required, found {abi}")
    # ABI 6: all filesystem rights through IOCTL_DEV, deny TCP, and scope
    # signals and abstract Unix sockets. Newer ABI rights are not assumed.
    attr = Ruleset((1 << 16) - 1, 3, 3)
    ruleset = check(libc.syscall(444, ctypes.byref(attr), ctypes.c_size_t(ctypes.sizeof(attr)), ctypes.c_uint(0)), "create Landlock ruleset")
    try:
        paths = [(str(root), READ_DIR),
                 (str(root / "scratch"), SCRATCH_ACCESS)]
        paths += [(str(root / name), READ_FILE) for name in input_files if (root / name).exists()]
        paths += [(path, READ_FILE | (READ_DIR if Path(path).is_dir() else 0)) for path in runtime]
        paths += [(path, READ_DIR) for path in runtime_dirs]
        paths += [("/dev/null", READ_FILE | WRITE_FILE), ("/dev/urandom", READ_FILE)]
        for path, access in paths:
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathRule(access, fd)
                check(libc.syscall(445, ctypes.c_int(ruleset), ctypes.c_int(1), ctypes.byref(rule), ctypes.c_uint(0)), "add Landlock path rule")
            finally:
                os.close(fd)
        check(libc.prctl(38, 1, 0, 0, 0), "set no_new_privs")
        check(libc.syscall(446, ctypes.c_int(ruleset), ctypes.c_uint(0)), "enforce Landlock ruleset")
    finally:
        os.close(ruleset)
    return abi


def restrict_syscalls(lib):
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
                                         ctypes.c_uint, ctypes.POINTER(ArgCompare)]
    lib.seccomp_rule_add_array.restype = ctypes.c_int
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_load.restype = ctypes.c_int
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    context = lib.seccomp_init(0x00050000 | errno.EPERM)
    if not context:
        raise RuntimeError("seccomp_init failed")

    def allow(name, comparisons=()):
        number = lib.seccomp_syscall_resolve_name(name.encode())
        if number < 0:  # syscall absent on this architecture
            return
        args = (ArgCompare * len(comparisons))(*(ArgCompare(index, 4, value, 0) for index, value in comparisons))
        result = lib.seccomp_rule_add_array(context, 0x7FFF0000, number, len(args), args)
        if result < 0:
            raise RuntimeError(f"seccomp rule {name}: {os.strerror(-result)}")

    try:
        for name in ALLOWED_SYSCALLS:
            allow(name)
        # Read own limits, never raise limits or affect another process.
        allow("prlimit64", ((0, 0), (2, 0)))
        # Descriptor operations only. No F_SETOWN/F_SETFL asynchronous signals.
        for operation in (0, 1, 2, 3, 1030):
            allow("fcntl", ((1, operation),))
            allow("fcntl64", ((1, operation),))
        # CPython FileIO uses FIOCLEX for descriptors returned by an opener.
        # All other ioctl requests remain blocked, including terminal injection.
        allow("ioctl", ((1, 0x5451),))
        result = lib.seccomp_load(context)
        if result < 0:
            raise RuntimeError(f"seccomp_load: {os.strerror(-result)}")
    finally:
        lib.seccomp_release(context)


def limits(policy):
    values = {
        resource.RLIMIT_AS: policy["memory_mb"] * 1024 ** 2,
        resource.RLIMIT_FSIZE: policy["file_mb"] * 1024 ** 2,
        resource.RLIMIT_NOFILE: policy["open_files"],
        resource.RLIMIT_CORE: 0,
        resource.RLIMIT_NPROC: 0,
    }
    for kind, value in values.items():
        resource.setrlimit(kind, (value, value))
    cpu = policy["cpu_seconds"]
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))


def tool(request, root):
    name, args = request["name"], request["args"]
    if name == "list_files":
        if args:
            raise ValueError("list_files takes no arguments")
        print("\n".join(f"{p.name}\t{p.stat().st_size}" for p in sorted(root.iterdir())))
    elif name == "read_file":
        if set(args) - {"path", "offset", "length"}:
            raise ValueError("unexpected read_file arguments")
        path = (root / args["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("path is outside the working directory")
        offset, length = args.get("offset", 0), args.get("length", request["read_default"])
        if not isinstance(offset, int) or not isinstance(length, int) or offset < 0 or length < 1:
            raise ValueError("offset must be >= 0 and length >= 1")
        # Inputs are small; scratch files are bounded by RLIMIT_FSIZE.
        text = path.read_text()
        chunk = text[offset:offset + min(length, request["read_cap"])]
        print(chunk + f"\n[characters {offset}-{offset + len(chunk)} of {len(text)}]", end="")
    elif name == "run_python":
        if set(args) != {"code"} or not isinstance(args["code"], str):
            raise ValueError("run_python requires one string argument: code")
        sys.argv = ["<agent>"]
        exec(compile(args["code"], "<agent>", "exec"), {"__name__": "__main__"})
    else:
        raise ValueError(f"unknown tool: {name}")


def main():
    request = json.load(sys.stdin)
    ready_fd = int(sys.argv[1])
    root = Path(request["root"]).resolve()
    # Load the enforcement library before restricting dynamic library reads.
    libc = ctypes.CDLL(None, use_errno=True)
    seccomp = ctypes.CDLL(request["seccomp_library"], use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    os.chdir(root)
    sys.dont_write_bytecode = True
    sys.path[:] = request["python_paths"]
    try:
        limits(request["limits"])
        abi = restrict_files(libc, root, request["runtime_paths"], request["runtime_dirs"], request["input_files"])
        restrict_syscalls(seccomp)
        os.write(ready_fd, json.dumps({"ready": True, "landlock_abi": abi}).encode())
    except Exception as error:
        os.write(ready_fd, json.dumps({"ready": False, "error": str(error)}).encode())
        os.close(ready_fd)
        return 125
    os.close(ready_fd)  # agent code cannot forge the setup receipt
    tool(request, root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
