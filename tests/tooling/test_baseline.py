"""Standard-library regression tests; no upstream build or network access."""
import importlib.util
import json
import os
import socket
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "baseline.py"
spec = importlib.util.spec_from_file_location("baseline", SCRIPT)
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_raw_bytes_and_nonzero_exit(self):
        run = baseline.new_run(self.root)
        code = "import os; os.write(1,b'out\\x00\\xff\\r\\n'); os.write(2,b'err\\xfe\\n'); raise SystemExit(23)"
        result = baseline.capture(run, "failure", [sys.executable, "-c", code], self.root)
        self.assertEqual(result["exit_code"], 23)
        self.assertEqual((run / result["stdout"]).read_bytes(), b"out\x00\xff\r\n")
        self.assertEqual((run / result["stderr"]).read_bytes(), b"err\xfe\n")
        self.assertEqual(json.loads((run / "failure.json").read_text()), result)
        self.assertEqual(result["argv"][0], sys.executable)
        self.assertEqual(result["cwd"], str(self.root.resolve()))

    def test_cli_propagates_nonzero_exit(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "capture", "--artifacts", str(self.root), "--", sys.executable, "-c", "raise SystemExit(17)"], capture_output=True)
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual(len(list(self.root.glob("*/command.json"))), 1)

    def test_missing_command_is_recorded(self):
        run = baseline.new_run(self.root)
        result = baseline.capture(run, "missing", [str(self.root / "absent")], self.root)
        self.assertEqual(result["exit_code"], 127)
        self.assertTrue((run / result["stderr"]).read_bytes())

    @unittest.skipUnless(os.name == "posix", "POSIX executable permissions")
    def test_non_executable_launch_has_command_record(self):
        command = self.root / "not-executable"
        command.write_text("#!/bin/sh\nexit 0\n")
        command.chmod(0o600)
        run = baseline.new_run(self.root)
        try:
            result = baseline.capture(run, "permission", [str(command)], self.root)
        except OSError as exc:
            self.fail(f"launch failure escaped without a command record: {exc}")
        self.assertEqual(result["exit_code"], 126)
        self.assertEqual(result["launch_errno"], 13)
        self.assertIn(b"Permission denied", (run / result["stderr"]).read_bytes())
        self.assertEqual(json.loads((run / "permission.json").read_text()), result)

    @unittest.skipUnless(os.name == "posix", "POSIX executable format")
    def test_invalid_executable_has_command_record(self):
        command = self.root / "invalid-executable"
        command.write_text("not an executable format\n")
        command.chmod(0o700)
        run = baseline.new_run(self.root)
        try:
            result = baseline.capture(run, "format", [str(command)], self.root)
        except OSError as exc:
            self.fail(f"launch failure escaped without a command record: {exc}")
        self.assertEqual(result["exit_code"], 126)
        self.assertIn("launch_errno", result)
        self.assertTrue((run / result["stderr"]).read_bytes())
        self.assertEqual(json.loads((run / "format.json").read_text()), result)

    @unittest.skipUnless(os.name == "posix", "POSIX descendant cleanup")
    def test_timeout_terminates_descendant_before_return(self):
        # A connected socket proves readiness; EOF proves the descendant exited.
        with socket.socket(socket.AF_UNIX) as listener:
            address = str(self.root / "child.sock")
            listener.bind(address)
            listener.listen(1)
            listener.settimeout(2)
            child = ("import socket,sys; s=socket.socket(socket.AF_UNIX); "
                     f"s.connect({address!r}); print('child ready',flush=True); "
                     "s.recv(1); s.close()")
            parent = f"import subprocess,sys; subprocess.run([sys.executable,'-c',{child!r}])"
            run = baseline.new_run(self.root)
            result = baseline.capture(run, "descendant", [sys.executable, "-c", parent], self.root, timeout=0.5)
            self.assertEqual(result["exit_code"], 124)
            before = (run / result["stdout"]).read_bytes()
            self.assertEqual(before, b"child ready\n")
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(1)
                try:
                    self.assertEqual(connection.recv(1), b"", "descendant survived timeout")
                except TimeoutError:
                    # The context closes the peer, releasing the unfixed child on red.
                    self.fail("descendant remained connected after capture returned")
            self.assertEqual((run / result["stdout"]).read_bytes(), before)

    def test_artifacts_are_unique_and_not_overwritten(self):
        first = baseline.new_run(self.root)
        second = baseline.new_run(self.root)
        self.assertNotEqual(first, second)
        baseline.capture(first, "same", [sys.executable, "-c", "print('first')"], self.root)
        with self.assertRaises(FileExistsError):
            baseline.capture(first, "same", [sys.executable, "-c", "print('second')"], self.root)
        self.assertEqual((first / "same.stdout").read_bytes(), b"first\n")

    def test_timeout_preserves_partial_output(self):
        run = baseline.new_run(self.root)
        result = baseline.capture(run, "timeout", [sys.executable, "-c", "import os,time; os.write(1,b'before timeout'); time.sleep(30)"], self.root, timeout=0.5)
        self.assertEqual(result["exit_code"], 124)
        self.assertEqual((run / result["stdout"]).read_bytes(), b"before timeout")

    @unittest.skipUnless(os.name == "posix", "POSIX signal exit convention")
    def test_signal_exit_is_shell_compatible(self):
        result = baseline.capture(baseline.new_run(self.root), "signal", [sys.executable, "-c", "import os,signal; os.kill(os.getpid(),signal.SIGTERM)"], self.root)
        self.assertEqual(result["returncode"], -15)
        self.assertEqual(result["exit_code"], 143)

    def test_capture_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            baseline.capture(baseline.new_run(self.root), "../outside", [sys.executable], self.root)

    def test_libtest_counts_preserve_ignored(self):
        counts = baseline.test_counts(b"test result: ok. 3 passed; 0 failed; 2 ignored; 0 measured; 4 filtered out; finished in 1s\ntest result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0s\n")
        self.assertEqual(counts, {"suites": 2, "passed": 3, "failed": 1, "ignored": 2, "measured": 0, "filtered_out": 4})
        self.assertIsNone(baseline.test_counts(b"error: cannot compile"))


class SourceChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "source"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "test")
        (self.repo / "file").write_text("original\n")
        self.git("add", "file")
        self.git("commit", "-qm", "fixture")
        self.pin = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True)

    def test_clean_matching_pin(self):
        check = baseline.check_source(self.repo, self.pin)
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["actual_pin"], self.pin)

    def test_preflight_failure_never_invokes_cargo(self):
        args = SimpleNamespace(artifacts=Path(self.temp.name) / "artifacts")
        with patch.object(baseline, "check_source", return_value={"ok": False, "problems": ["pin mismatch"]}), patch.object(baseline, "capture") as capture:
            self.assertEqual(baseline.baseline(args), 2)
            capture.assert_not_called()
        result = json.loads(next(args.artifacts.glob("*/result.json")).read_text())
        self.assertEqual(result["status"], "source-preflight-blocked")
        self.assertEqual(result["commands"], [])

    def test_absent_requested_toolchain_never_invokes_cargo(self):
        args = SimpleNamespace(artifacts=Path(self.temp.name) / "artifacts", toolchain="999.0")
        def only_probe(run, name, argv, cwd, **kwargs):
            self.assertEqual(argv, ["rustup", "toolchain", "list"])
            (run / "installed-toolchains.stdout").write_text("1.95.0-aarch64-apple-darwin\n")
            return {"exit_code": 0, "stdout": "installed-toolchains.stdout"}
        with patch.object(baseline, "check_source", return_value={"ok": True}), patch.object(baseline, "capture", side_effect=only_probe) as capture:
            self.assertEqual(baseline.baseline(args), 2)
            self.assertEqual(capture.call_count, 1)
        result = json.loads(next(args.artifacts.glob("*/result.json")).read_text())
        self.assertEqual(result["status"], "requested-toolchain-not-installed")

    def test_wrong_pin(self):
        check = baseline.check_source(self.repo, "0" * 40)
        self.assertFalse(check["ok"])
        self.assertIn("pin mismatch", check["problems"])

    def test_dirty_tracked_and_untracked(self):
        (self.repo / "file").write_text("modified\n")
        (self.repo / "untracked").write_text("new\n")
        check = baseline.check_source(self.repo, self.pin)
        self.assertFalse(check["ok"])
        self.assertIn("dirty source", check["problems"])
        self.assertIn("?? untracked", check["status"])

    def test_uninitialized_nested_submodule(self):
        # Simulate a gitlink without cloning: status must detect '-' before build.
        self.git("update-index", "--add", "--cacheinfo", "160000," + self.pin + ",vendor/nested")
        (self.repo / ".gitmodules").write_text('[submodule "nested"]\n\tpath = vendor/nested\n\turl = https://example.invalid/nested.git\n')
        self.git("add", ".gitmodules")
        self.git("commit", "-qm", "gitlink")
        pin = self.git("rev-parse", "HEAD").strip()
        check = baseline.check_source(self.repo, pin)
        self.assertFalse(check["ok"])
        self.assertIn("unready nested submodule", check["problems"])


if __name__ == "__main__":
    unittest.main()
