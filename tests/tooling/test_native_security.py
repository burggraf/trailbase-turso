"""Probe contract tests: simulated evidence is never executed-engine proof."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "experiments/native-udf-security/contract.json").read_text())


def step(ok=True, calls=0, rows=None, error=None):
    return dict(sql="SELECT marker(1)", ok=ok, calls=calls,
                rows=[] if rows is None else rows, error=error,
                error_kind=None if ok else "engine-sql")


def evidence():
    security = []
    for engine, flags in [("sqlite", ["innocuous", "ordinary", "direct-only"]), ("native", ["ordinary"])]:
        for flag in flags:
            for context in ["top", "check", "default", "generated", "index", "view", "trigger", "stored-view"]:
                denied = engine == "sqlite" and flag != "innocuous" and context != "top"
                steps = [dict(step(), sql=sql) for sql in CONTRACT["security"][context]]
                if denied:
                    if context == "stored-view":
                        steps = steps[:2]
                    steps[-1].update(ok=False, error="unsafe use of marker()", error_kind="engine-sql")
                else:
                    for i, s in enumerate(steps):
                        if s["sql"].startswith("SELECT"):
                            s.update(calls=1, rows=[[1]])
                        elif i == len(steps) - 1:
                            s.update(calls=1)
                security.append(dict(engine=engine, flag=flag, context=context,
                    setting=dict(step(), sql=CONTRACT["setting_sql"]), readback=dict(step(rows=[[0]] if engine == "sqlite" else []), sql=CONTRACT["readback_sql"]),
                    positive=dict(step(calls=1, rows=[[1]]), sql=CONTRACT["positive_sql"]),
                    steps=steps, context_drops=1))
    return dict(schema_version=2, native_api="sdk-register-scalar-no-security-flags", security=security,
        bridge=[dict(engine=e, steps=[dict(step(calls=1, rows=v.get("rows"), ok="error" not in v, error=v.get("error")), sql=v["sql"]) for v in CONTRACT["bridge"]], context_drops=1, value_drops=6 if e == "native" else None) for e in ["sqlite", "native"]],
        overload=[dict(engine=e, before=dict(step(calls=1, rows=[[2]]), sql=CONTRACT["overload"]["before"]), after2=dict(step(calls=1, rows=[[2]]) if e == "sqlite" else step(False, error="wrong number of arguments"), sql=CONTRACT["overload"]["after2"]), after3=dict(step(calls=1, rows=[[3]]), sql=CONTRACT["overload"]["after3"]), context_drops=2) for e in ["sqlite", "native"]])


class NativeSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / "scripts/native_security.py"
        spec = importlib.util.spec_from_file_location("native_security", path)
        cls.m = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, "path", [str(path.parent), *sys.path]):
            spec.loader.exec_module(cls.m)

    def classify(self, data=None, result=None):
        return self.m.classify(result or {"exit_code":0}, json.dumps(evidence() if data is None else data))

    def test_executed_gaps_exit_one_not_pass(self):
        report = self.classify()
        self.assertEqual(report["exit_code"], 1)
        self.assertIn("native-security-flags-unavailable", report["blockers"])
        self.assertIn("native-schema-execution-gap:view", report["blockers"])
        self.assertIn("native-arity-overwrite", report["blockers"])

    def test_security_select_results_must_match_marker(self):
        for engine in ["sqlite", "native"]:
            for context in ["top", "view", "stored-view"]:
                with self.subTest(engine=engine, context=context):
                    d = evidence()
                    r = next(r for r in d["security"] if r["engine"] == engine and r["flag"] in ["innocuous", "ordinary"] and r["context"] == context)
                    r["steps"][-1]["rows"] = []
                    self.assertEqual(self.classify(d)["exit_code"], 2)

    def test_each_reopened_select_requires_its_own_callback(self):
        for engine in ["sqlite", "native"]:
            for index in [1, 2]:
                with self.subTest(engine=engine, index=index):
                    d = evidence()
                    r = next(r for r in d["security"] if r["engine"] == engine and r["flag"] in ["innocuous", "ordinary"] and r["context"] == "stored-view")
                    r["steps"][index]["calls"] = 0
                    self.assertEqual(self.classify(d)["exit_code"], 2)

    def test_bootstrap_and_setup_callbacks_are_not_execution_proof(self):
        for engine in ["sqlite", "native"]:
            for context in ["stored-view", "check", "index"]:
                with self.subTest(engine=engine, context=context):
                    d = evidence()
                    r = next(r for r in d["security"] if r["engine"] == engine and r["flag"] in ["innocuous", "ordinary"] and r["context"] == context)
                    r["steps"][0]["calls"] = 1
                    for s in r["steps"][1:]:
                        s.update(calls=0, rows=[])
                    self.assertEqual(self.classify(d)["exit_code"], 2)

    def test_unexpected_native_errors_are_harness_failure(self):
        for context, index in [("check", 0), ("generated", 0), ("index", 2)]:
            for error in ["synchronous SDK statement unexpectedly requires IO", "I/O error (read): PermissionDenied", "unrecognized engine rejection"]:
                with self.subTest(context=context, error=error):
                    d = evidence()
                    r = next(r for r in d["security"] if r["engine"] == "native" and r["context"] == context)
                    r["steps"] = r["steps"][:index + 1]
                    r["steps"][-1].update(ok=False, calls=0, rows=[], error=error, error_kind="engine-sql")
                    self.assertEqual(self.classify(d)["exit_code"], 2)

    def test_harness_origin_rejects_even_known_unsupported_diagnostic(self):
        d = evidence()
        r = next(r for r in d["security"] if r["engine"] == "native" and r["context"] == "generated")
        r["steps"] = [dict(step(False, error='Error("Parse error: Stored generated columns are not supported"): Parse error: Stored generated columns are not supported'), sql=CONTRACT["security"]["generated"][0], error_kind="harness")]
        self.assertEqual(self.classify(d)["exit_code"], 2)

    def test_known_unsupported_errors_require_the_matching_statement(self):
        error = 'Error("Parse error: Stored generated columns are not supported"): Parse error: Stored generated columns are not supported'
        d = evidence()
        r = next(r for r in d["security"] if r["engine"] == "native" and r["context"] == "check")
        r["steps"] = r["steps"][:1]
        r["steps"][0].update(ok=False, calls=0, rows=[], error=error, error_kind="engine-sql")
        self.assertEqual(self.classify(d)["exit_code"], 2)

    def test_actual_sdk_lost_arity_reports_no_such_function(self):
        d = evidence()
        d["overload"][1]["after2"]["error"] = 'Error("Parse error: no such function: jsonschema"): Parse error: no such function: jsonschema'
        self.assertEqual(self.classify(d)["exit_code"], 1)
        d["overload"][1]["after2"]["error"] = "no such function: unrelated"
        self.assertEqual(self.classify(d)["exit_code"], 2)

    def test_nonzero_or_capture_error_is_harness_failure_even_with_json(self):
        for result in [{"exit_code":1}, {"exit_code":134}, {"exit_code":124, "capture_error":"timeout"}]:
            self.assertEqual(self.classify(result=result)["exit_code"], 2)

    def test_malformed_partial_duplicate_or_wrong_types_rejected(self):
        for raw in ["", "{", "{}", "null", "[]", json.dumps(evidence()) + "trailing"]:
            self.assertEqual(self.m.classify({"exit_code":0}, raw)["exit_code"], 2)
        for mutate in [lambda d: d["security"].pop(),
                       lambda d: d["security"].append(d["security"][0]),
                       lambda d: d["security"][0].update(context_drops=0),
                       lambda d: d["security"][0]["positive"].update(calls=True),
                       lambda d: d["bridge"].pop(),
                       lambda d: d["overload"][0]["after3"].pop("rows")]:
            d = evidence(); mutate(d)
            self.assertEqual(self.classify(d)["exit_code"], 2)

    def test_partial_step_sequence_rejected_even_when_first_callback_ran(self):
        d = evidence()
        d["security"][7]["steps"][1].update(calls=1)
        d["security"][7]["steps"] = d["security"][7]["steps"][:2]
        self.assertEqual(self.classify(d)["exit_code"], 2)

    def test_wrong_sql_is_not_matching_case_proof(self):
        d = evidence()
        d["security"][1]["steps"][0]["sql"] = "SELECT marker(1)"
        self.assertEqual(self.classify(d)["exit_code"], 2)

    def test_nonstandard_json_constants_and_duplicate_keys_are_rejected(self):
        raw = json.dumps(evidence())
        duplicate = raw[:-1] + ', "schema_version": 1}'
        self.assertEqual(self.m.classify({"exit_code":0}, duplicate)["exit_code"], 2)

    def test_nonstandard_nan_json_rejected(self):
        d = evidence(); d["security"][24]["steps"][0]["rows"] = [[float("nan")]]
        self.assertEqual(self.classify(d)["exit_code"], 2)

    def test_denied_control_requires_rejection_and_zero_forbidden_calls(self):
        for change in [dict(ok=True, error=None), dict(calls=1), dict(error="SQL syntax error")]:
            d = evidence()
            d["security"][9]["steps"][-1].update(change)
            self.assertEqual(self.classify(d)["exit_code"], 2)

    def test_innocuous_and_top_positive_controls_required(self):
        for index in [0, 1, 8, 24]:
            d = evidence(); d["security"][index]["steps"][-1].update(calls=0)
            self.assertEqual(self.classify(d)["exit_code"], 2)

    def test_unsupported_native_context_is_not_demonstrated_security_gap(self):
        d = evidence()
        d["security"][27]["steps"] = [dict(step(False, error='Error("Parse error: Stored generated columns are not supported"): Parse error: Stored generated columns are not supported'), sql=CONTRACT["security"]["generated"][0])]
        report = self.classify(d)
        self.assertNotIn("native-schema-execution-gap:generated", report["blockers"])
        self.assertIn("native-sql-rejected:generated", report["missing"])

    def test_row_value_types_are_exact_not_python_numeric_coercions(self):
        for mutate in [lambda d: d["security"][0]["readback"].update(rows=[[False]]),
                       lambda d: d["bridge"][1]["steps"][1].update(rows=[[-7.0]]),
                       lambda d: d["security"][24]["steps"][0].update(rows=[[{"blob":[True]}]])]:
            d = evidence(); mutate(d)
            self.assertEqual(self.classify(d)["exit_code"], 2)

    def test_value_and_destructor_controls_required(self):
        for mutate in [lambda d: d["bridge"][1]["steps"][0].update(rows=[[0]]),
                       lambda d: d["bridge"][1].update(value_drops=0),
                       lambda d: d["overload"][0]["after2"].update(rows=[[3]]),
                       lambda d: d["security"][0]["readback"].update(rows=[])]:
            d = evidence(); mutate(d)
            self.assertEqual(self.classify(d)["exit_code"], 2)

    def test_pin_and_dirty_source_rejected_using_existing_checker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            subprocess.run(["git", "init", "-q", tmp], check=True)
            subprocess.run(["git", "-C", tmp, "-c", "user.name=Probe", "-c", "user.email=probe@example.invalid", "commit", "-qm", "initial", "--allow-empty"], check=True)
            pin = subprocess.check_output(["git", "-C", tmp, "rev-parse", "HEAD"], text=True).strip()
            self.assertTrue(self.m.sources_ok({"probe": self.m.baseline.check_source(path, pin)}))
            self.assertFalse(self.m.sources_ok({"probe": self.m.baseline.check_source(path, "0" * 40)}))
            (path / "dirty").write_text("changed")
            self.assertFalse(self.m.sources_ok({"probe": self.m.baseline.check_source(path, pin)}))
            self.assertFalse(self.m.sources_ok({}))

    def test_postflight_failure_overrides_engine_blocker(self):
        self.assertEqual(self.m.final_exit(1, False), 2)
        self.assertEqual(self.m.final_exit(1, True), 1)

    def test_capture_keeps_failure_streams(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.m.baseline.new_run(tmp)
            r = self.m.baseline.capture(run, "nonzero", [sys.executable, "-c", 'import sys; print("out"); print("err",file=sys.stderr); sys.exit(9)'], tmp)
            self.assertEqual(r["exit_code"], 9)
            self.assertEqual((run / r["stdout"]).read_text(), "out\n")
            self.assertEqual((run / r["stderr"]).read_text(), "err\n")


if __name__ == "__main__":
    unittest.main()
