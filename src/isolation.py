"""Controlled, fail-closed execution of agent tools on Linux.

Landlock controls file content access; a seccomp syscall allowlist blocks all
sockets and subprocesses. No mount namespace is required. See docs/isolation.md
for the exact boundary, including host metadata that Landlock does not hide.
"""
import argparse
import ctypes.util
import errno
import hashlib
import json
import os
import re
import selectors
import signal
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path

DEFAULT_POLICY = Path(__file__).with_name("sandbox_policy.json")
WORKER = Path(__file__).with_name("sandbox_worker.py")
TOOLS = {"list_files", "read_file", "run_python"}
LIMIT_KEYS = {"wall_seconds", "cpu_seconds", "memory_mb", "file_mb", "open_files",
              "stdout_bytes", "stderr_bytes", "code_bytes", "workspace_bytes", "workspace_files"}


class IsolationError(RuntimeError):
    """Restrictions cannot be verified; execute no agent code."""


def load_policy(path=DEFAULT_POLICY):
    # Freeze a passed configuration so batch workers cannot see later edits.
    policy = json.loads(json.dumps(path)) if isinstance(path, dict) else json.loads(Path(path).read_text())
    if set(policy) != {"schema_version", "allowed_tools", "input_files", "python", "limits"} or policy["schema_version"] != 1:
        raise ValueError("invalid sandbox policy schema")
    if (not isinstance(policy["allowed_tools"], list) or not policy["allowed_tools"]
            or any(not isinstance(name, str) for name in policy["allowed_tools"])
            or not set(policy["allowed_tools"]) <= TOOLS or len(set(policy["allowed_tools"])) != len(policy["allowed_tools"])):
        raise ValueError("allowed_tools must be a nonempty list of distinct supported tools")
    if set(policy["limits"]) != LIMIT_KEYS:
        raise ValueError("sandbox policy must specify all resource limits")
    if any(type(v) is not int or v <= 0 for v in policy["limits"].values()):
        raise ValueError("sandbox limits must be positive integers")
    if policy["limits"]["open_files"] < 16:
        raise ValueError("open_files must be at least 16 for sandbox setup")
    if not Path(policy["python"]).is_absolute():
        raise ValueError("sandbox Python path must be absolute")
    if (not isinstance(policy["input_files"], list) or not policy["input_files"]
            or any(not isinstance(p, str) or not p or Path(p).is_absolute()
                   or any(part in ("..", "scratch") for part in Path(p).parts)
                   or p == "." for p in policy["input_files"])):
        raise ValueError("input_files must name relative input files outside scratch; traversal is forbidden")
    return policy


def policy_hash(policy):
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()[:16]


def dependencies(path):
    result = subprocess.run(["ldd", str(path)], capture_output=True, text=True, timeout=10,
                            env={"PATH": "/usr/bin:/bin", "LANG": "C"})
    if result.returncode:
        raise IsolationError(f"cannot determine runtime dependencies for {path}")
    if "not found" in result.stdout:
        raise IsolationError(f"missing runtime dependency for {path}")
    return {str(Path(p).resolve()) for p in re.findall(r"(/[\w./+@-]+)", result.stdout)}


def stdlib_paths(stdlib):
    # Do not grant a recursive read rule on the whole library root: some
    # installations keep third-party packages or bundled pip wheels there.
    excluded = {"site-packages", "dist-packages", "ensurepip", "__pycache__"}
    return {str(path.resolve()) for path in Path(stdlib).iterdir()
            if path.name not in excluded and (path.is_file() or path.is_dir())}


@lru_cache(maxsize=4)
def runtime(python):
    if sys.platform != "linux":
        raise IsolationError("isolated execution requires Linux with Landlock ABI >= 6 and libseccomp")
    if (Path(python).parent.parent / "pyvenv.cfg").exists():
        raise IsolationError("sandbox must use system Python, not a virtual environment")
    probe = "import json,sys,sysconfig; print(json.dumps({'version':sys.version,'stdlib':sysconfig.get_path('stdlib'),'prefix':sys.prefix,'base_prefix':sys.base_prefix,'python':sys.executable}))"
    result = subprocess.run([python, "-I", "-S", "-c", probe], capture_output=True, text=True,
                            timeout=10, env={"LANG": "C.UTF-8"})
    if result.returncode:
        raise IsolationError("cannot start isolated system Python")
    info = json.loads(result.stdout)
    if info["prefix"] != info["base_prefix"]:
        raise IsolationError("sandbox must use system Python, not a virtual environment")
    stdlib = Path(info["stdlib"]).resolve()
    binary = Path(python).resolve()
    shared = dependencies(binary)
    for module in (stdlib / "lib-dynload").glob("*.so"):
        shared |= dependencies(module)
    library = ctypes.util.find_library("seccomp")
    if not library:
        raise IsolationError("libseccomp is required; refusing unrestricted execution")
    info.update({"runtime_paths": sorted(shared | stdlib_paths(stdlib) | {str(binary)}),
                 "runtime_dirs": [str(stdlib)],
                 "python_paths": [str(stdlib), str(stdlib / "lib-dynload")],
                 "seccomp_library": library,
                 "python_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()})
    return info


def workspace_usage(root, limits):
    count = size = 0
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    pending = [os.open(root, flags)]
    try:
        while pending:
            directory = pending.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        count += 1
                        if entry.is_file(follow_symlinks=False):
                            size += entry.stat(follow_symlinks=False).st_size
                        if count > limits["workspace_files"] or size > limits["workspace_bytes"]:
                            return count, size
                        if entry.is_dir(follow_symlinks=False):
                            try:
                                pending.append(os.open(entry.name, flags, dir_fd=directory))
                            except OSError as error:
                                if error.errno not in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
                                    raise
                                # Removed or swapped for a symlink during the scan.
            finally:
                os.close(directory)
        return count, size
    finally:
        for directory in pending:
            os.close(directory)


class IsolatedWorkspace:
    def __init__(self, root, read_default=2000, read_cap=20000, policy=None):
        self.root = Path(root).resolve()
        self.read_default, self.read_cap = read_default, read_cap
        self.policy = load_policy(policy or DEFAULT_POLICY)
        self.runtime = runtime(self.policy["python"])
        (self.root / "scratch").mkdir(exist_ok=True)
        for name in self.policy["input_files"]:
            path = self.root / name
            if path.exists() and (not path.is_file() or not path.resolve().is_relative_to(self.root)):
                raise IsolationError(f"input must be a regular file inside the workspace: {name}")
        if (self.root / "scratch").is_symlink():
            raise IsolationError("scratch must not be a symlink")
        self.last_execution = None
        self.metadata = {
            "backend": "landlock-seccomp", "policy_hash": policy_hash(self.policy),
            "policy": self.policy, "python_version": self.runtime["version"],
            "python_sha256": self.runtime["python_sha256"],
            "network": "all socket syscalls denied", "subprocesses": "denied",
            "files": "listed inputs read-only; scratch writable; system Python runtime read-only",
            "environment": "cleared; no API credentials", "setup_verified": False,
        }
        # Trusted no-op tests actual activation before any model request.
        output, error = self._execute("run_python", {"code": "print('sandbox ready')"})
        if error or output.strip() != "sandbox ready":
            raise IsolationError(f"sandbox preflight failed: {output}")
        self.metadata.update(setup_verified=True, landlock_abi=self.last_execution["setup"]["landlock_abi"])
        self.last_execution = None

    def call(self, name, args):
        self.last_execution = None
        if name not in self.policy["allowed_tools"]:
            return f"error: tool not allowed by policy: {name}", True
        if not isinstance(args, dict):
            return "error: tool arguments must be an object", True
        code = args.get("code", "")
        if isinstance(code, str) and len(code.encode()) > self.policy["limits"]["code_bytes"]:
            return "error: script exceeds policy code limit", True
        return self._execute(name, args)

    def _execute(self, name, args):
        limits = self.policy["limits"]
        request = {"root": str(self.root), "name": name, "args": args, "limits": limits,
                   "input_files": self.policy["input_files"],
                   "read_default": self.read_default, "read_cap": self.read_cap,
                   **{k: self.runtime[k] for k in ("runtime_paths", "runtime_dirs", "python_paths", "seccomp_library")}}
        read_fd, ready_fd = os.pipe()
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                [self.policy["python"], "-I", "-S", str(WORKER), str(ready_fd)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=self.root, close_fds=True, pass_fds=(ready_fd,), start_new_session=True,
                env={"LANG": "C.UTF-8", "TZ": "UTC", "HOME": "/nonexistent",
                     "TMPDIR": str(self.root / "scratch")},
            )
        except BaseException:
            os.close(read_fd)
            raise
        finally:
            os.close(ready_fd)
        output = {"stdout": bytearray(), "stderr": bytearray(), "setup": bytearray()}
        received = {key: 0 for key in output}
        failure = None
        with selectors.DefaultSelector() as selector:
            for stream, label in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, label)
            os.set_blocking(read_fd, False)
            selector.register(read_fd, selectors.EVENT_READ, "setup")
            try:
                process.stdin.write(json.dumps(request).encode())
                process.stdin.close()
                # An agent may close both output streams and keep running.
                # Keep monitoring its deadline even when there are no pipes left.
                while selector.get_map() or process.poll() is None:
                    if failure is None and time.monotonic() - started > limits["wall_seconds"]:
                        failure = "wall_timeout"
                    if failure is None:
                        try:
                            count, size = workspace_usage(self.root / "scratch", limits)
                            if count > limits["workspace_files"] or size > limits["workspace_bytes"]:
                                failure = "workspace_limit"
                        except FileNotFoundError:
                            pass  # scratch entry was removed while being counted
                    if failure is not None and process.poll() is None:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    for key, _ in selector.select(.05):
                        fd = key.fileobj if isinstance(key.fileobj, int) else key.fileobj.fileno()
                        block = os.read(fd, 65536)
                        if not block:
                            selector.unregister(key.fileobj)
                            continue
                        label = key.data
                        cap = 4096 if label == "setup" else limits[f"{label}_bytes"]
                        received[label] += len(block)
                        output[label].extend(block[:max(0, cap - len(output[label]))])
                        if received[label] > cap and failure is None:
                            failure = "output_limit"
                process.wait()
                if failure is None:
                    count, size = workspace_usage(self.root / "scratch", limits)
                    if count > limits["workspace_files"] or size > limits["workspace_bytes"]:
                        failure = "workspace_limit"
            finally:
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                process.stdout.close()
                process.stderr.close()
                os.close(read_fd)
        try:
            setup = json.loads(output["setup"])
        except (ValueError, UnicodeDecodeError):
            setup = {"ready": False, "error": "missing verified sandbox setup receipt"}
        if not setup.get("ready"):
            raise IsolationError(f"sandbox setup failed: {setup.get('error', 'unknown error')}")
        stdout, stderr = (bytes(output[label]).decode("utf-8", errors="replace") for label in ("stdout", "stderr"))
        self.last_execution = {
            "stdout": stdout, "stderr": stderr, "returncode": process.returncode,
            "signal": -process.returncode if process.returncode < 0 else None,
            "seconds": round(time.monotonic() - started, 3), "failure": failure,
            "stdout_truncated": received["stdout"] > limits["stdout_bytes"],
            "stderr_truncated": received["stderr"] > limits["stderr_bytes"],
            "stdout_bytes": received["stdout"], "stderr_bytes": received["stderr"], "setup": setup,
        }
        text = stdout + (f"\n[stderr]\n{stderr}" if stderr else "")
        if failure:
            text += f"\n[execution stopped: {failure}]"
        elif process.returncode:
            text += f"\n[exit status: {process.returncode}]"
        return text or "[no output]", failure is not None or process.returncode != 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args()
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "region.fasta").write_text(">probe\nACGTACGT\n")
        workspace = IsolatedWorkspace(root, policy=args.policy)
        probes = {
            "sequence read": "assert 'ACGTACGT' in open('region.fasta').read(); print('ok')",
            "network sockets denied": "import socket\ntry: socket.socket()\nexcept PermissionError: print('ok')\nelse: raise AssertionError('socket allowed')",
            "host files denied": "\ntry: open('/etc/passwd').read()\nexcept PermissionError: print('ok')\nelse: raise AssertionError('host file readable')",
            "input writes denied": "\ntry: open('region.fasta','w')\nexcept PermissionError: print('ok')\nelse: raise AssertionError('input writable')",
            "scratch writable": "open('scratch/check.txt','w').write('test'); print('ok')",
            "packages unavailable": "import importlib.util; assert all(importlib.util.find_spec(p) is None for p in ('numpy','Bio','pip')); print('ok')",
            "subprocesses denied": "import os\ntry: os.fork()\nexcept PermissionError: print('ok')\nelse: raise AssertionError('fork allowed')",
            "credentials absent": "import os; assert not any('KEY' in k or 'TOKEN' in k for k in os.environ); print('ok')",
        }
        for label, code in probes.items():
            result, error = workspace._execute("run_python", {"code": code})
            if error or result.strip() != "ok":
                raise IsolationError(f"{label}: {result}")
            print(f"PASS {label}")
        print(json.dumps(workspace.metadata, indent=2))


if __name__ == "__main__":
    main()
