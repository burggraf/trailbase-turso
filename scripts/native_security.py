#!/usr/bin/env python3
"""Isolated SDK UDF/security observations; 1=blocker, 2=incomplete/harness error."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import baseline

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "experiments/native-udf-security"
CONTRACT = json.loads((PACKAGE / "contract.json").read_text())
CONTEXTS = set(CONTRACT["security"])


def sources_ok(sources):
    return bool(sources) and all(s.get("ok") is True for s in sources.values())


def final_exit(code, postflight_ok):
    return code if postflight_ok else 2


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_step(s):
    require(isinstance(s, dict) and set(s) == {"sql", "ok", "calls", "rows", "error", "error_kind"}, "invalid step fields")
    require(isinstance(s["sql"], str) and bool(s["sql"]), "missing SQL")
    require(type(s["ok"]) is bool and type(s["calls"]) is int and s["calls"] >= 0, "invalid step outcome")
    require(isinstance(s["rows"], list) and all(isinstance(row, list) for row in s["rows"]), "invalid rows")
    for row in s["rows"]:
        for value in row:
            require(value is None or type(value) in {str, int, float} or (isinstance(value, dict) and set(value) == {"blob"} and isinstance(value["blob"], list) and all(type(b) is int and 0 <= b <= 255 for b in value["blob"])), "invalid cell type")
    require(s["error"] is None if s["ok"] else isinstance(s["error"], str) and bool(s["error"]), "contradictory error")
    require(s["error_kind"] is None if s["ok"] else s["error_kind"] == "engine-sql", "harness/environment error or invalid error kind")


def successful_call(s, expected=None):
    require(s["ok"] and s["calls"] > 0, "positive callback control incomplete")
    if expected is not None:
        require(json.dumps(s["rows"], sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True), "callback result/type mismatch")


def unique_object(pairs):
    result = dict(pairs)
    require(len(result) == len(pairs), "duplicate evidence field")
    return result


def reject_constant(value):
    raise ValueError("nonstandard JSON constant: " + value)


def classify(command, stdout):
    result = {"exit_code":2, "status":"incomplete-or-harness-error", "blockers":[], "missing":[], "rows":[]}
    try:
        require(command.get("exit_code") == 0 and not command.get("capture_error"), "fixture command failed; raw output is not complete proof")
        d = json.loads(stdout, object_pairs_hook=unique_object, parse_constant=reject_constant)
        require(isinstance(d, dict) and set(d) == {"schema_version", "native_api", "security", "bridge", "overload"}, "invalid evidence fields")
        require(type(d["schema_version"]) is int and d["schema_version"] == 2, "unknown contract")
        require(d["native_api"] == "sdk-register-scalar-no-security-flags", "unknown API exposure")
        expected = {(e, f, c) for e, flags in [("sqlite", ["innocuous", "ordinary", "direct-only"]), ("native", ["ordinary"])] for f in flags for c in CONTEXTS}
        require(isinstance(d["security"], list), "missing security observations")
        seen = set()
        for r in d["security"]:
            require(isinstance(r, dict) and set(r) == {"engine", "flag", "context", "setting", "readback", "positive", "steps", "context_drops"}, "invalid security fields")
            key = (r["engine"], r["flag"], r["context"])
            require(key in expected and key not in seen, "duplicate/unknown security case")
            seen.add(key)
            require(type(r["context_drops"]) is int and r["context_drops"] == 1, "context ownership control failed")
            require(isinstance(r["steps"], list) and bool(r["steps"]), "missing execution")
            for s in [r["setting"], r["readback"], r["positive"], *r["steps"]]:
                validate_step(s)
            require(r["setting"]["sql"] == CONTRACT["setting_sql"] and r["readback"]["sql"] == CONTRACT["readback_sql"] and r["positive"]["sql"] == CONTRACT["positive_sql"], "wrong control SQL")
            expected_sql = CONTRACT["security"][r["context"]]
            require([s["sql"] for s in r["steps"]] == expected_sql[:len(r["steps"])] and len(r["steps"]) <= len(expected_sql), "wrong schema SQL")
            require(all(s["ok"] for s in r["steps"][:-1]) and (not r["steps"][-1]["ok"] or len(r["steps"]) == len(expected_sql)), "partial execution sequence")
            for i, s in enumerate(r["steps"]):
                if not s["ok"]:
                    require(s["calls"] == 0 and s["rows"] == [], "rejected step has incomplete callback/row proof")
                    continue
                invokes = i > 0 if r["context"] == "stored-view" else i == len(expected_sql) - 1
                require(s["calls"] == int(invokes), "callback in wrong execution phase or missing invocation")
                expected_rows = [[1]] if s["sql"].startswith("SELECT") else []
                require(json.dumps(s["rows"], allow_nan=False) == json.dumps(expected_rows), "schema callback result/type mismatch")
            require(r["setting"]["ok"] and r["setting"]["calls"] == 0 and r["readback"]["ok"] and r["readback"]["calls"] == 0, "trusted_schema setting/readback failed")
            successful_call(r["positive"], [[1]])
            calls = sum(s["calls"] for s in r["steps"])
            all_ok = all(s["ok"] for s in r["steps"])
            rejected = [s for s in r["steps"] if not s["ok"]]
            if r["engine"] == "sqlite":
                require(json.dumps(r["readback"]["rows"]) == "[[0]]", "SQLite trusted_schema OFF not verified")
                if r["flag"] == "innocuous" or r["context"] == "top":
                    require(all_ok and calls > 0, "SQLite allowed control incomplete")
                    label = "allowed-control"
                else:
                    require(calls == 0 and rejected and all("unsafe use of marker" in s["error"].lower() for s in rejected), "SQLite denied control not proven")
                    label = "denied-zero-calls-control"
            elif r["context"] == "top":
                require(all_ok and calls > 0, "native top-level control incomplete")
                label = "native-top-level-call"
            elif rejected:
                # These are exact, pinned fixture diagnostics, not production error
                # categories. Unexpected engine/harness failures remain exit 2.
                known = {
                    "generated": (0, 'Error("Parse error: Stored generated columns are not supported"): Parse error: Stored generated columns are not supported'),
                    "index": (2, 'Error("Parse error: Error: invalid expression in CREATE INDEX: marker (x)"): Parse error: Error: invalid expression in CREATE INDEX: marker (x)'),
                }
                require(r["context"] in known, "unexpected native SQL rejection")
                index, diagnostic = known[r["context"]]
                require(len(r["steps"]) == index + 1 and r["steps"][-1]["error"] == diagnostic and calls == 0, "unrecognized native unsupported-context outcome")
                label = "sql-rejected-not-security-proof"
                result["missing"].append("native-sql-rejected:" + r["context"])
            elif calls > 0:
                label = "schema-callback-executed"
                result["blockers"].append("native-schema-execution-gap:" + r["context"])
            else:
                raise ValueError("native schema case executed no callback without rejection")
            result["rows"].append({"engine":r["engine"], "flag":r["flag"], "context":r["context"], "classification":label, "calls":calls, "trusted_schema_readback":r["readback"]["rows"]})
        require(seen == expected, "partial security matrix")
        for section in ["bridge", "overload"]:
            require(isinstance(d[section], list) and len(d[section]) == 2 and {r.get("engine") for r in d[section]} == {"sqlite", "native"}, "missing/duplicate engine control")
        for r in d["bridge"]:
            require(set(r) == {"engine", "steps", "context_drops", "value_drops"} and r["context_drops"] == 1 and type(r["context_drops"]) is int, "invalid bridge lifetime")
            require(isinstance(r["steps"], list) and len(r["steps"]) == 6, "partial bridge evidence")
            for s in r["steps"]:
                validate_step(s)
            require([s["sql"] for s in r["steps"]] == [s["sql"] for s in CONTRACT["bridge"]], "wrong bridge SQL")
            for s, expected in zip(r["steps"][:-1], CONTRACT["bridge"][:-1]):
                successful_call(s, expected["rows"])
                require(s["calls"] == 1, "unexpected bridge callback count")
            s = r["steps"][-1]
            require(not s["ok"] and s["calls"] == 1 and "probe callback error" in s["error"], "callback error propagation incomplete")
            require(r["value_drops"] == 6 and type(r["value_drops"]) is int if r["engine"] == "native" else r["value_drops"] is None, "value destruction incomplete")
        for r in d["overload"]:
            require(set(r) == {"engine", "before", "after2", "after3", "context_drops"} and type(r["context_drops"]) is int and r["context_drops"] == 2, "invalid overload lifetime")
            for name in ["before", "after2", "after3"]:
                validate_step(r[name])
                require(r[name]["sql"] == CONTRACT["overload"][name], "wrong overload SQL")
            successful_call(r["before"], [[2]])
            successful_call(r["after3"], [[3]])
            if r["engine"] == "sqlite":
                successful_call(r["after2"], [[2]])
            elif r["after2"]["ok"]:
                successful_call(r["after2"], [[2]])
            else:
                error = r["after2"]["error"].lower()
                require(r["after2"]["calls"] == 0 and ("wrong number of arguments" in error or "no such function: jsonschema" in error), "unexplained native overload failure")
                result["blockers"].append("native-arity-overwrite")
        result["blockers"].append("native-security-flags-unavailable")
        result.update(exit_code=1, status="blocked")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        result.update(exit_code=2, status="incomplete-or-harness-error", error=str(exc))
    return result


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_probe(args):
    run = baseline.new_run(args.artifacts)
    print("Raw native-security artifacts: " + str(run), flush=True)
    env = os.environ.copy()
    env.update(RUSTUP_AUTO_INSTALL="0", RUST_BACKTRACE="1", CARGO_TARGET_DIR=str(ROOT / "artifacts/native-security/target"))
    before = {n: baseline.check_source(ROOT / "upstream" / n, pin) for n, pin in baseline.PINS.items()}
    baseline.write_json(run / "sources-before.json", before)
    summary = {"schema_version":1, "run_dir":str(run), "exit_code":2, "status":"incomplete-or-harness-error"}
    locks = [ROOT / "upstream" / n / "Cargo.lock" for n in baseline.PINS]
    hashes = {}
    try:
        require(sources_ok(before), "source-preflight-blocked")
        paths = [*sorted(PACKAGE.rglob("*.rs")), PACKAGE / "Cargo.toml", PACKAGE / "Cargo.lock", PACKAGE / "contract.json", Path(__file__), ROOT / "scripts/run-native-security.sh", ROOT / "scripts/baseline.py", ROOT / "tests/tooling/test_native_security.py", *locks,
            ROOT / "upstream/turso/sdk-kit/src/rsapi.rs", ROOT / "upstream/turso/core/ext/mod.rs", ROOT / "upstream/turso/core/translate/pragma.rs", ROOT / "upstream/turso/extensions/core/src/functions.rs", ROOT / "upstream/turso/extensions/core/src/types.rs", ROOT / "upstream/turso/tests/integration/external_apis.rs", ROOT / "upstream/trailbase/crates/extension/src/lib.rs", ROOT / "upstream/trailbase/crates/extension/src/jsonschema.rs"]
        for p in paths:
            hashes[str(p.relative_to(ROOT))] = digest(p)
            dest = run / "inputs" / p.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dest)
        baseline.write_json(run / "inputs.json", hashes)
        baseline.write_json(run / "environment.json", {"toolchain":"1.95.0", "overrides":{k:env[k] for k in ["RUSTUP_AUTO_INSTALL", "RUST_BACKTRACE", "CARGO_TARGET_DIR"]}, "scope":"SDK/core only; not public driver or TrailBase/cloud parity"})
        def capture(name, argv):
            return baseline.capture(run, name, argv, ROOT, env, timeout=args.timeout)
        for name, argv in [("toolchains", ["rustup", "toolchain", "list"]), ("rustc", ["rustc", "+1.95.0", "-Vv"]), ("cargo", ["cargo", "+1.95.0", "-V"])]:
            r = capture(name, argv)
            require(r["exit_code"] == 0, "version probe failed")
            if name == "toolchains":
                require(any(line.split()[0].startswith("1.95.0-") or line.split()[0] == "1.95.0" for line in (run / r["stdout"]).read_text().splitlines() if line.split()), "toolchain not installed")
        cargo = ["cargo", "+1.95.0"]
        manifest = ["--manifest-path", str(PACKAGE / "Cargo.toml")]
        versions = capture("engine-versions", cargo + ["run", "--locked", *manifest, "--", "--versions"])
        require(versions["exit_code"] == 0, "engine version probe failed")
        tested = capture("rust-tests", cargo + ["test", "--locked", *manifest, "--", "--nocapture"])
        require(tested["exit_code"] == 0 and tested.get("test_counts") and tested["test_counts"]["passed"] > 0 and not tested["test_counts"]["ignored"], "Rust fixtures/tests incomplete")
        observed = capture("observations", cargo + ["run", "--locked", *manifest, "--", str(run / "databases")])
        summary.update(classify(observed, (run / observed["stdout"]).read_text()))
    except (OSError, ValueError) as exc:
        summary.update(exit_code=2, status="incomplete-or-harness-error", error=str(exc))
    finally:
        after = {n: baseline.check_source(ROOT / "upstream" / n, pin) for n, pin in baseline.PINS.items()}
        baseline.write_json(run / "sources-after.json", after)
        unchanged = sources_ok(after) and all(p.is_file() and digest(p) == h for rel, h in hashes.items() for p in [ROOT / rel])
        summary["inputs_unchanged"] = unchanged
        summary["exit_code"] = final_exit(summary["exit_code"], unchanged)
        if not unchanged:
            summary.update(status="incomplete-or-harness-error", postflight_error="source/input changed")
        baseline.write_json(run / "classification.json", summary)
        print(f"{summary['status']}: exit {summary['exit_code']} (see {run / 'classification.json'})", flush=True)
    return summary["exit_code"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--artifacts", type=Path, default=ROOT / "artifacts/native-security")
    p.add_argument("--timeout", type=int, default=900)
    return run_probe(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
