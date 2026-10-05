"""Behavior contracts; standard library only, no fake engine compatibility claim."""
import importlib.util
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "compatibility.py"


class CompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("compatibility", SCRIPT)
        cls.module = importlib.util.module_from_spec(spec)
        # Match the scripts directory search path used by the command-line runner.
        with mock.patch.object(sys, 'path', [str(SCRIPT.parent), *sys.path]):
            spec.loader.exec_module(cls.module)

    def test_required_link_is_blocker_only_with_both_missing_symbols(self):
        classify = self.module.classify_link
        raw = 'Undefined symbols: "_sqlite3_auto_extension", "_sqlite3_preupdate_hook"'
        self.assertEqual(classify({"exit_code": 1}, raw), "missing-required-api")
        self.assertEqual(classify({"exit_code": 1}, 'compiler not found'), "tool-or-environment-error")
        self.assertEqual(classify({"exit_code": 1}, 'undefined reference to sqlite3_auto_extension'), "unexplained-link-failure")
        self.assertEqual(classify({"exit_code": 124, "capture_error": "timeout"}, raw), "tool-or-environment-error")
        self.assertEqual(classify({"exit_code": 0}, raw), "linked")

    def test_backup_requires_actual_abort_and_specific_panic(self):
        classify = self.module.classify_backup
        panic = "thread panicked: sqlite3_backup_init is not implemented"
        self.assertEqual(classify({"exit_code": 134, "returncode": -signal.SIGABRT}, panic), "panic-abort-backup-stub")
        self.assertEqual(classify({"exit_code": 1, "returncode": 1}, panic), "unexplained-runtime-failure")
        self.assertEqual(classify({"exit_code": 139, "returncode": -signal.SIGSEGV}, panic), "unexplained-runtime-failure")
        self.assertEqual(classify({"exit_code": 124, "capture_error": "timeout"}, panic), "tool-or-environment-error")

    def test_linkage_rejects_sqlite_fallback_and_wrong_library(self):
        check = self.module.linkage_ok
        selected = Path('/selected/libturso_sqlite3.dylib')
        self.assertTrue(check('bin:\n @rpath/libturso_sqlite3.dylib (compatibility version 0.0.0)\n /usr/lib/libSystem.B.dylib', selected, 'Darwin'))
        self.assertFalse(check('bin:\n /usr/lib/libsqlite3.dylib', selected, 'Darwin'))
        self.assertFalse(check('bin:\n @rpath/libturso_sqlite3.dylib\n /usr/lib/libsqlite3.dylib', selected, 'Darwin'))
        self.assertFalse(check('libturso_sqlite3.so => /wrong/libturso_sqlite3.so', Path('/selected/libturso_sqlite3.so'), 'Linux'))
        self.assertTrue(check('libturso_sqlite3.so => /selected/libturso_sqlite3.so (0x123)', Path('/selected/libturso_sqlite3.so'), 'Linux'))
        self.assertFalse(check('libturso_sqlite3.so => /selected/libturso_sqlite3.so.evil (0x123)', Path('/selected/libturso_sqlite3.so'), 'Linux'))
        self.assertFalse(check('libturso_sqlite3.so => /selected/libturso_sqlite3.so (0x123)\nlibother.so => not found', Path('/selected/libturso_sqlite3.so'), 'Linux'))

    def test_overall_blocked_is_not_pass_or_environment_failure(self):
        status = self.module.overall
        self.assertEqual(status(['passed', 'missing-required-api', 'panic-abort-backup-stub']), ('blocked', 1))
        self.assertEqual(status(['missing-required-api', 'tool-or-environment-error']), ('tool-or-environment-error', 2))
        self.assertEqual(status(['passed', 'unexplained-runtime-failure']), ('unexplained-failure', 2))
        self.assertEqual(status(['passed']), ('subset-only-no-blocker-observed', 0))

    def test_environment_removes_injected_loaders(self):
        env = self.module.runtime_env(Path('/chosen/libturso_sqlite3.dylib'), {'LD_PRELOAD':'evil', 'DYLD_INSERT_LIBRARIES':'evil', 'DYLD_LIBRARY_PATH':'wrong', 'SAFE':'yes'})
        self.assertNotIn('LD_PRELOAD', env)
        self.assertNotIn('DYLD_INSERT_LIBRARIES', env)
        self.assertEqual(env['DYLD_LIBRARY_PATH'], '/chosen')
        self.assertEqual(env['EXPECTED_ENGINE_LIBRARY'], '/chosen/libturso_sqlite3.dylib')
        self.assertEqual(env['SAFE'], 'yes')

    def test_build_is_locked_isolated_and_explicit(self):
        argv, env = self.module.build_config(Path('/source'), Path('/run'), '1.95.0')
        self.assertEqual(argv, ['cargo', '+1.95.0', 'build', '--locked', '-p', 'turso_sqlite3', '--features', 'capi'])
        self.assertEqual(env['CARGO_TARGET_DIR'], '/run/target')
        self.assertEqual(env['RUSTUP_AUTO_INSTALL'], '0')
        with self.assertRaises(ValueError):
            self.module.build_config(Path('/source'), Path('/run'), '')

    def test_capture_contract_preserves_failure_and_raw_streams(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.module.baseline.new_run(Path(tmp))
            result = self.module.baseline.capture(run, 'failed-control', [sys.executable, '-c', 'import sys; print("raw stdout"); print("raw stderr", file=sys.stderr); sys.exit(7)'], tmp)
            self.assertEqual(result['returncode'], 7)
            self.assertEqual(result['exit_code'], 7)
            self.assertEqual((run / result['stdout']).read_text(), 'raw stdout\n')
            self.assertEqual((run / result['stderr']).read_text(), 'raw stderr\n')
            missing = self.module.baseline.capture(run, 'missing-tool', [str(Path(tmp) / 'absent')], tmp)
            self.assertEqual(missing['exit_code'], 127)
            self.assertIsNone(missing['returncode'])
            self.assertIn('capture_error', missing)

    def test_final_postflight_status_controls_return_code(self):
        def postflight_error(args, outcome):
            outcome.update(exit_code=2, status='tool-or-environment-error')
            return 1  # earlier blocker must not mask later source/library changes
        with mock.patch.object(self.module, '_run_spike', side_effect=postflight_error):
            self.assertEqual(self.module.run_spike(object()), 2)


if __name__ == '__main__':
    unittest.main()
