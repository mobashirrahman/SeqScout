"""Kernel-enforced isolation tests. No model API calls or internet traffic.

Run: .venv/bin/python tests/test_isolation.py
Requires Linux Landlock ABI >= 6, system Python and libseccomp. Unsupported
environments fail these checks rather than silently skipping enforcement.
"""
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import harness
from backends import AnthropicChat, OpenAIChat
from isolation import DEFAULT_POLICY, IsolationError, load_policy, stdlib_paths, workspace_usage
from tools import Workspace


class IsolationTests(unittest.TestCase):
    @contextlib.contextmanager
    def workspace(self, *, overrides=None, tools=None, inputs=None):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "run"
            root.mkdir()
            (root / "region.fasta").write_text(">test\n" + "ACGT" * 100 + "\n")
            (parent / "canary.txt").write_text("TEST_CANARY_OUTSIDE_WORKSPACE")
            policy = load_policy(DEFAULT_POLICY)
            policy["limits"].update(overrides or {})
            if tools:
                policy["allowed_tools"] = tools
            if inputs:
                policy["input_files"] = inputs
            policy_path = parent / "policy.json"
            policy_path.write_text(json.dumps(policy))
            workspace = Workspace(root, policy=policy_path)
            yield workspace, root, parent

    def successful(self, workspace, code, expected="ok"):
        output, error = workspace.call("run_python", {"code": code})
        self.assertFalse(error, output)
        self.assertEqual(output.strip(), expected)
        self.assertTrue(workspace.last_execution["setup"]["ready"])

    def test_real_sequence_analysis_and_standard_library(self):
        with self.workspace() as (workspace, root, _):
            (root / "region.fasta").write_text((ROOT / "data/ecoli/loci/region_006.fasta").read_text())
            self.successful(workspace, """
import collections, statistics, random, hashlib, re, math, tempfile
seq=''.join(x.strip() for x in open('region.fasta') if not x.startswith('>'))
counts=collections.Counter(seq)
assert len(seq)==3000
assert counts['G']==764 and counts['C']==883
assert round(100*(counts['G']+counts['C'])/len(seq),1)==54.9
assert statistics.mean([1,2,3])==2
assert len(hashlib.sha256(seq.encode()).hexdigest())==64
with tempfile.TemporaryFile(mode='w+') as f:
    f.write('scratch works');f.seek(0);assert f.read()=='scratch works'
print('ok')
""")

    def test_socket_families_and_raw_syscalls_are_denied(self):
        with self.workspace() as (workspace, _, _):
            self.successful(workspace, """
import socket,ctypes,errno,platform
for family,kind in [(socket.AF_INET,socket.SOCK_STREAM),(socket.AF_INET,socket.SOCK_DGRAM),
                    (socket.AF_INET6,socket.SOCK_STREAM),(socket.AF_UNIX,socket.SOCK_STREAM)]:
    try: socket.socket(family,kind)
    except PermissionError: pass
    else: raise AssertionError('socket allowed')
libc=ctypes.CDLL(None,use_errno=True)
number=41 if platform.machine()=='x86_64' else 198
assert libc.syscall(number,2,1,0)==-1 and ctypes.get_errno()==errno.EPERM
print('ok')
""")

    def test_http_client_cannot_connect_even_to_localhost(self):
        with self.workspace() as (workspace, _, _):
            output, error = workspace.call("run_python", {"code": "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9',timeout=1)"})
            self.assertTrue(error)
            self.assertIn("Operation not permitted", output)

    def test_host_contents_and_metadata_changes_are_denied(self):
        with self.workspace() as (workspace, _, parent):
            canary = parent / "canary.txt"
            original_mode = stat.S_IMODE(canary.stat().st_mode)
            self.successful(workspace, f"""
import os
for operation in [lambda:open({str(canary)!r}).read(),lambda:os.chmod({str(canary)!r},0o777)]:
    try: operation()
    except PermissionError: pass
    else: raise AssertionError('host access allowed')
print('ok')
""")
            self.assertEqual(stat.S_IMODE(canary.stat().st_mode), original_mode)
            self.assertEqual(canary.read_text(), "TEST_CANARY_OUTSIDE_WORKSPACE")

    def test_symlink_and_hardlink_cannot_escape(self):
        with self.workspace() as (workspace, _, parent):
            canary = parent / "canary.txt"
            self.successful(workspace, f"""
import os,errno
os.symlink({str(canary)!r},'scratch/escape')
try: open('scratch/escape').read()
except PermissionError: pass
else: raise AssertionError('symlink escaped')
try: os.link({str(canary)!r},'scratch/hardlink')
except OSError as error: assert error.errno in (errno.EPERM,errno.EACCES,errno.EXDEV)
else: raise AssertionError('hardlink escaped')
print('ok')
""")
            output, error = workspace.call("read_file", {"path": "scratch/escape"})
            self.assertTrue(error)
            self.assertIn("outside the working directory", output)

    def test_input_contents_cannot_be_changed_or_removed(self):
        with self.workspace() as (workspace, root, _):
            original = (root / "region.fasta").read_bytes()
            self.successful(workspace, """
import os
for operation in [lambda:open('region.fasta','w'),lambda:os.unlink('region.fasta'),
                  lambda:os.rename('region.fasta','scratch/moved'),lambda:os.truncate('region.fasta',0)]:
    try: operation()
    except PermissionError: pass
    else: raise AssertionError('input changed')
print('ok')
""")
            self.assertEqual((root / "region.fasta").read_bytes(), original)

    def test_unlisted_workspace_file_is_not_readable(self):
        with self.workspace() as (workspace, root, _):
            (root / "hidden_answer.txt").write_text("TEST_ANSWER_KEY")
            output, error = workspace.call("read_file", {"path": "hidden_answer.txt"})
            self.assertTrue(error)
            self.assertNotIn("TEST_ANSWER_KEY", output)
            self.successful(workspace, """
try: open('hidden_answer.txt').read()
except PermissionError: print('ok')
else: raise AssertionError('unlisted file accessible')
""")

    def test_packages_and_external_imports_are_unavailable(self):
        with self.workspace() as (workspace, _, parent):
            (parent / "outside_module.py").write_text("raise RuntimeError('EXTERNAL_MODULE_EXECUTED')")
            self.successful(workspace, f"""
import importlib.util,sys
assert all(importlib.util.find_spec(name) is None for name in ('Bio','numpy','pip','openai'))
sys.path.insert(0,{str(parent)!r})
try: import outside_module
except (PermissionError,ModuleNotFoundError): pass
else: raise AssertionError('external import allowed')
print('ok')
""")

    def test_package_directories_inside_runtime_root_are_denied(self):
        with self.workspace() as (workspace, _, parent):
            library = parent / "library"
            library.mkdir()
            (library / "allowed_stdlib.py").write_text("TEST_STDLIB_CONTENT")
            blocked = []
            for name in ("site-packages", "dist-packages", "ensurepip"):
                directory = library / name
                directory.mkdir()
                package = directory / "third_party.py"
                package.write_text("TEST_THIRD_PARTY_CONTENT")
                blocked.append(str(package))
            workspace.runtime = {**workspace.runtime,
                                 "runtime_paths": workspace.runtime["runtime_paths"] + sorted(stdlib_paths(library)),
                                 "runtime_dirs": workspace.runtime["runtime_dirs"] + [str(library)]}
            self.successful(workspace, f"""
assert open({str(library / 'allowed_stdlib.py')!r}).read()=='TEST_STDLIB_CONTENT'
for path in {blocked!r}:
    try: open(path).read()
    except PermissionError: pass
    else: raise AssertionError('bundled package readable')
print('ok')
""")

    def test_monitor_does_not_follow_a_directory_swapped_for_symlink(self):
        with self.workspace() as (workspace, root, parent):
            scratch = root / "scratch"
            (scratch / "race").mkdir()
            outside = parent / "outside"
            outside.mkdir()
            (outside / "canary").write_text("TEST_OUTSIDE_MONITOR")
            original_open = os.open

            def swap(path, flags, *args, **kwargs):
                if path == "race" and "dir_fd" in kwargs:
                    (scratch / "race").rmdir()
                    (scratch / "race").symlink_to(outside, target_is_directory=True)
                return original_open(path, flags, *args, **kwargs)

            with patch("isolation.os.open", side_effect=swap):
                self.assertEqual(workspace_usage(scratch, workspace.policy["limits"]), (1, 0))

    def test_credentials_and_inherited_file_descriptors_are_absent(self):
        with self.workspace() as (workspace, _, parent):
            fd = os.open(parent / "canary.txt", os.O_RDONLY)
            os.set_inheritable(fd, True)
            try:
                with patch.dict(os.environ, {"OPENCODE_API_KEY": "TEST_ONLY_KEY", "HTTP_PROXY": "http://test.invalid"}):
                    self.successful(workspace, f"""
import os
assert not any('KEY' in key or 'TOKEN' in key or 'PROXY' in key for key in os.environ)
try: os.read({fd},100)
except OSError: pass
else: raise AssertionError('inherited descriptor accessible')
print('ok')
""")
            finally:
                os.close(fd)

    def test_fork_and_exec_are_denied(self):
        with self.workspace() as (workspace, _, _):
            self.successful(workspace, """
import os,subprocess
for operation in [os.fork,lambda:os.execv('/usr/bin/python3',['python3','-c','print("escaped")']),
                  lambda:subprocess.run(['/usr/bin/python3','-c','print("escaped")'])]:
    try: operation()
    except PermissionError: pass
    else: raise AssertionError('process creation/execution allowed')
print('ok')
""")

    def test_scratch_persists_but_interpreter_state_does_not(self):
        with self.workspace() as (workspace, _, _):
            self.successful(workspace, "sentinel='old state';open('scratch/artifact.txt','w').write('saved');print('ok')")
            self.successful(workspace, "assert 'sentinel' not in globals();assert open('scratch/artifact.txt').read()=='saved';print('ok')")
            with self.workspace() as (second, _, _):
                self.successful(second, "import os;assert not os.path.exists('scratch/artifact.txt');print('ok')")

    def test_tool_allowlist_is_enforced(self):
        with self.workspace(tools=["read_file"]) as (workspace, _, _):
            output, error = workspace.call("run_python", {"code": "print('should not run')"})
            self.assertTrue(error)
            self.assertIn("not allowed by policy", output)
            self.assertIsNone(workspace.last_execution)
            output, error = workspace.call("read_file", {"path": "region.fasta"})
            self.assertFalse(error, output)

    def test_python_failure_records_stderr_and_exit_status(self):
        with self.workspace() as (workspace, _, _):
            output, error = workspace.call("run_python", {"code": "print('before');raise ValueError('failure marker')"})
            self.assertTrue(error)
            self.assertEqual(workspace.last_execution["returncode"], 1)
            self.assertEqual(workspace.last_execution["stdout"], "before\n")
            self.assertIn("ValueError: failure marker", workspace.last_execution["stderr"])
            self.assertIn("exit status", output)

    def test_wall_time_limit_terminates_script(self):
        with self.workspace(overrides={"wall_seconds": 1}) as (workspace, _, _):
            _, error = workspace.call("run_python", {"code": "import time;time.sleep(10)"})
            self.assertTrue(error)
            self.assertEqual(workspace.last_execution["failure"], "wall_timeout")
            self.assertEqual(workspace.last_execution["signal"], 9)

    def test_closed_output_streams_cannot_bypass_deadline(self):
        with self.workspace(overrides={"wall_seconds": 1}) as (workspace, _, _):
            _, error = workspace.call("run_python", {"code": "import os,time;os.close(1);os.close(2);time.sleep(10)"})
            self.assertTrue(error)
            self.assertEqual(workspace.last_execution["failure"], "wall_timeout")
            self.assertLess(workspace.last_execution["seconds"], 3)

    def test_cpu_limit_terminates_busy_loop(self):
        with self.workspace(overrides={"cpu_seconds": 1, "wall_seconds": 5}) as (workspace, _, _):
            _, error = workspace.call("run_python", {"code": "while True: pass"})
            self.assertTrue(error)
            self.assertIn(workspace.last_execution["signal"], (9, 24))

    def test_parent_proc_descriptors_cannot_be_reopened(self):
        with self.workspace() as (workspace, _, parent):
            fd = os.open(parent / "canary.txt", os.O_RDONLY)
            pipe_read, pipe_write = os.pipe()
            try:
                self.successful(workspace, f"""
import os
for path in ['/proc/{os.getpid()}/fd/{fd}','/proc/{os.getpid()}/fd/{pipe_write}']:
    try: os.open(path,os.O_RDONLY)
    except PermissionError: pass
    else: raise AssertionError('parent descriptor reopened')
print('ok')
""")
            finally:
                os.close(fd)
                os.close(pipe_read)
                os.close(pipe_write)

    def test_output_limit_is_bounded_and_reported(self):
        with self.workspace(overrides={"stdout_bytes": 100}) as (workspace, _, _):
            _, error = workspace.call("run_python", {"code": "print('x'*1000000)"})
            self.assertTrue(error)
            self.assertEqual(workspace.last_execution["failure"], "output_limit")
            self.assertTrue(workspace.last_execution["stdout_truncated"])
            self.assertEqual(len(workspace.last_execution["stdout"]), 100)

    def test_memory_limit_and_limit_changes(self):
        with self.workspace(overrides={"memory_mb": 64}) as (workspace, _, _):
            self.successful(workspace, """
import resource
assert resource.getrlimit(resource.RLIMIT_AS)==(64*1024**2,64*1024**2)
try: resource.setrlimit(resource.RLIMIT_AS,(128*1024**2,128*1024**2))
except (PermissionError,ValueError): pass
else: raise AssertionError('raised memory limit')
try: bytearray(256*1024**2)
except MemoryError: print('ok')
else: raise AssertionError('memory limit not enforced')
""")

    def test_file_size_limit(self):
        with self.workspace(overrides={"file_mb": 1}) as (workspace, root, _):
            _, error = workspace.call("run_python", {"code": "open('scratch/large','wb').write(b'x'*(2*1024**2))"})
            self.assertTrue(error)
            self.assertLessEqual((root / "scratch/large").stat().st_size, 1024 ** 2)

    def test_workspace_file_count_limit(self):
        with self.workspace(overrides={"workspace_files": 2}) as (workspace, _, _):
            _, error = workspace.call("run_python", {"code": "import time\nfor i in range(3):open('scratch/file'+str(i),'w').close()\ntime.sleep(2)"})
            self.assertTrue(error)
            self.assertEqual(workspace.last_execution["failure"], "workspace_limit")

    def test_failed_setup_stops_before_model_api(self):
        class Client:
            calls = 0

            @property
            def messages(self):
                self.calls += 1
                raise AssertionError("model API was touched")

        with tempfile.TemporaryDirectory() as temporary:
            locus = Path(temporary) / "locus.fasta"
            locus.write_text(">test\nACGT\n")
            client = Client()
            with patch("isolation.WORKER", Path(temporary) / "missing_worker.py"):
                with self.assertRaises(IsolationError):
                    harness.run_once(client, locus, "file", model="test", effort="low", read_default=2000, max_turns=2)
            self.assertEqual(client.calls, 0)

    def test_policy_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.json"
            policy = load_policy()
            policy["input_files"] = ["../outside"]
            path.write_text(json.dumps(policy))
            with self.assertRaises(ValueError):
                load_policy(path)

    def test_harness_records_a_blocked_model_script(self):
        from test_offline import ScriptedClient, response

        with tempfile.TemporaryDirectory() as temporary:
            locus = Path(temporary) / "locus.fasta"
            locus.write_text(">test\nACGT\n")
            attempt = SimpleNamespace(type="tool_use", id="attack", name="run_python",
                                      input={"code": "import socket;socket.socket()"})
            final = SimpleNamespace(type="text", text="No external lookup performed.")
            client = ScriptedClient([response("tool_use", [attempt]), response("end_turn", [final])])
            record = harness.run_once(client, locus, "file", model="test", effort="low",
                                      read_default=2000, max_turns=3)
            self.assertTrue(record["isolation"]["setup_verified"])
            self.assertEqual(record["isolation"]["policy"], load_policy())
            self.assertEqual(record["tool_errors"], 1)
            call = record["tool_calls"][0]
            self.assertTrue(call["is_error"])
            self.assertEqual(call["execution"]["returncode"], 1)
            self.assertIn("PermissionError", call["execution"]["stderr"])
            result = record["transcript"][2]["content"][0]
            self.assertTrue(result["is_error"])
            self.assertIn("Operation not permitted", result["content"])
            json.dumps(record)

    def test_restricted_tool_list_reaches_both_provider_requests(self):
        from test_offline import ScriptedClient, response

        final = SimpleNamespace(type="text", text="Report.")
        anthropic = ScriptedClient([response("end_turn", [final])])
        message = SimpleNamespace(content="Report.", tool_calls=[])
        message.model_dump = lambda exclude_none: {"role": "assistant", "content": "Report."}
        completion = SimpleNamespace(id="offline-test", choices=[SimpleNamespace(finish_reason="stop", message=message)],
                                     usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3))
        compatible = ScriptedClient([completion])
        compatible.chat = SimpleNamespace(completions=compatible)
        with tempfile.TemporaryDirectory() as temporary:
            locus = Path(temporary) / "locus.fasta"
            locus.write_text(">test\nACGT\n")
            policy = load_policy()
            policy["allowed_tools"] = ["read_file"]
            for client, adapter in [(anthropic, AnthropicChat), (compatible, OpenAIChat)]:
                with self.subTest(adapter=adapter.__name__):
                    record = harness.run_once(client, locus, "file", model="test", effort="low",
                                              read_default=2000, max_turns=2, chat_cls=adapter, policy_path=policy)
                    offered = client.requests[0]["tools"]
                    names = [t.get("name") or t["function"]["name"] for t in offered]
                    self.assertEqual(names, ["read_file"])
                    self.assertNotEqual(record["prompt_hash"], harness.PROMPT_HASH)
                    self.assertEqual(record["isolation"]["policy"]["allowed_tools"], ["read_file"])

    def test_cli_refuses_historical_results_before_api_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            loci, out = root / "loci", root / "old-results"
            loci.mkdir()
            out.mkdir()
            (loci / "region.fasta").write_text(">test\nACGT\n")
            (out / "region__file__0.json").write_text(json.dumps({"report": "Historical report."}))
            with patch.object(sys, "argv", ["harness.py", "--loci", str(loci), "--out", str(out)]), \
                    patch("harness.make_client") as make_client, \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                with self.assertRaises(SystemExit) as stopped:
                    harness.main()
            self.assertEqual(stopped.exception.code, 2)
            self.assertIn("fresh --out directory", errors.getvalue())
            make_client.assert_not_called()

    def test_cli_checks_kernel_setup_before_api_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            loci = root / "loci"
            loci.mkdir()
            (loci / "region.fasta").write_text(">test\nACGT\n")
            with patch.object(sys, "argv", ["harness.py", "--loci", str(loci), "--out", str(root / "new-results")]), \
                    patch("isolation.WORKER", root / "missing_worker.py"), \
                    patch("harness.make_client") as make_client, \
                    contextlib.redirect_stderr(io.StringIO()) as errors, contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as stopped:
                    harness.main()
            self.assertEqual(stopped.exception.code, 2)
            self.assertIn("sandbox setup failed", errors.getvalue())
            make_client.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
