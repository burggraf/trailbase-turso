#!/usr/bin/env python3
"""Bounded Route A C spike; never a claim that TrailBase tests passed.

Uses baseline's capture/new_run/check_source contract; Python standard library only.
Exit 1 = observed engine blocker; exit 2 = tooling, source, or unexplained failure.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import shutil
import sys

import baseline

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    "trailbase": "12d3343d7d78c8e4dd65af264a3244f472de450d",
    "turso": "e6c79b43cabde627ab9eb4eaa20c2d3e6d384d7c",
}
BLOCKERS = {"missing-required-api", "panic-abort-backup-stub"}


def classify_link(result, stderr):
    if result.get("capture_error"):
        return "tool-or-environment-error"
    if result["exit_code"] == 0:
        return "linked"
    if re.search(r"Undefined symbols|undefined reference", stderr, re.I):
        if all(s in stderr for s in ["sqlite3_auto_extension", "sqlite3_preupdate_hook"]):
            return "missing-required-api"
        return "unexplained-link-failure"
    return "tool-or-environment-error"


def classify_backup(result, stderr):
    if result.get("capture_error"):
        return "tool-or-environment-error"
    if result["exit_code"] == 0:
        return "passed"
    if result.get("returncode") == -signal.SIGABRT and "sqlite3_backup_init" in stderr and "not implemented" in stderr and "panic" in stderr:
        return "panic-abort-backup-stub"
    if re.search(r"Library not loaded|cannot open shared object|engine image mismatch|cannot identify engine image", stderr):
        return "tool-or-environment-error"
    return "unexplained-runtime-failure"


def overall(classes):
    if any(c in {"tool-or-environment-error", "source-preflight-blocked", "source-changed-during-run"} for c in classes):
        return "tool-or-environment-error", 2
    if any(c.startswith("unexplained") for c in classes):
        return "unexplained-failure", 2
    if any(c in BLOCKERS for c in classes):
        return "blocked", 1
    return "subset-only-no-blocker-observed", 0


def runtime_env(library, inherited=None):
    env = dict(os.environ if inherited is None else inherited)
    # Do not inherit injection/search settings that could redirect SQLite symbols.
    for key in list(env):
        if key.startswith("DYLD_") or key in {"LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT"}:
            del env[key]
    if library:
        library = library.resolve()
        env.update(EXPECTED_ENGINE_LIBRARY=str(library), DYLD_LIBRARY_PATH=str(library.parent), LD_LIBRARY_PATH=str(library.parent))
    else:
        env.pop("EXPECTED_ENGINE_LIBRARY", None)
    env["RUST_BACKTRACE"] = "1"
    return env


def build_config(source, run, toolchain):
    if not toolchain or toolchain.startswith("-"):
        raise ValueError("an explicit already-installed Rust toolchain is required")
    env = os.environ.copy()
    env.update(CARGO_TARGET_DIR=str(run / "target"), RUSTUP_AUTO_INSTALL="0")
    return ["cargo", "+" + toolchain, "build", "--locked", "-p", "turso_sqlite3", "--features", "capi"], env


def linkage_ok(text, library, system):
    if re.search(r"libsqlite3[.\-]", text, re.I):
        return False
    if system == "Darwin":
        return any(line.strip().split(" (")[0] in {str(library), "@rpath/" + library.name} for line in text.splitlines()[1:])
    if system == "Linux":
        if "not found" in text:
            return False
        paths = re.findall(r"=>\s+(\S+)", text)
        return any(Path(path).resolve() == library.resolve() for path in paths)
    return False


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run_spike(args):
    outcome = {}
    _run_spike(args, outcome)
    return outcome["exit_code"]


def _run_spike(args, outcome):
    run = baseline.new_run(args.artifacts)
    print("Raw compatibility artifacts: " + str(run), flush=True)
    summary = {"schema_version": 1, "run_dir": str(run), "status": "running", "commands": [], "fixtures": [],
               "scope": "standalone C subset and two required-API blockers, not TrailBase substitution",
               "unchanged_trailbase_tests": "baseline-pending-unverified; not run by this spike"}
    classes = []
    library = None
    before_hash = None
    system = platform.system()
    source = ROOT / "upstream" / "turso"
    env = runtime_env(None)

    def save():
        baseline.write_json(run / "result.json", summary)

    def command(name, argv, cwd=ROOT, command_env=None, timeout=None):
        result = baseline.capture(run, name, [str(a) for a in argv], cwd, command_env or env, timeout=timeout or args.timeout)
        summary["commands"].append({"name": name, **result})
        save()
        return result

    def raw(result, stream):
        return (run / result[stream]).read_text(errors="replace")

    def fixture(engine, name, classification, **details):
        summary["fixtures"].append({"engine": engine, "fixture": name, "classification": classification, **details})
        if engine == "turso" or classification not in {"control-unavailable", "linked", "passed"}:
            classes.append(classification)
        save()

    def inspect(name, path):
        return command(name, ["otool", "-L", path] if system == "Darwin" else ["ldd", path], command_env=runtime_env(library))

    try:
        inputs = run / "inputs"
        inputs.mkdir()
        summary["input_sha256"] = {}
        for path in [Path(__file__), ROOT / "scripts" / "run-compatibility.sh", ROOT / "upstream" / "turso" / "bindings" / "c" / "include" / "sqlite3.h", *sorted((ROOT / "tests" / "compatibility").glob("*"))]:
            if path.is_file():
                shutil.copyfile(path, inputs / path.name)
                summary["input_sha256"][path.name] = digest(path)
        summary["baseline_helper"] = {"path": baseline.__file__, "sha256": digest(Path(baseline.__file__))}
        summary["sources_before"] = {name: baseline.check_source(ROOT / "upstream" / name, pin) for name, pin in PINS.items()}
        save()
        if not all(s["ok"] for s in summary["sources_before"].values()):
            classes.append("source-preflight-blocked")
            return 2
        summary["lock_sha256_before"] = digest(source / "Cargo.lock")
        summary["environment"] = {"platform": platform.platform(), "machine": platform.machine(), "toolchain": args.toolchain,
                                   "compiler": args.cc, "provided_library": bool(args.library)}
        if system not in {"Darwin", "Linux"}:
            classes.append("tool-or-environment-error")
            summary["error"] = "Only Darwin (otool) and Linux (ldd) linkage inspection are supported"
            return 2
        if args.library:
            library = args.library.resolve()
        else:
            installed = command("installed-toolchains", ["rustup", "toolchain", "list"], timeout=30)
            names = [line.split()[0] for line in raw(installed, "stdout").splitlines() if line.split()]
            if installed["exit_code"] or not any(n == args.toolchain or n.startswith(args.toolchain + "-") for n in names):
                classes.append("tool-or-environment-error")
                summary["error"] = "Requested toolchain is not already installed"
                return 2
            argv, build_env = build_config(source, run, args.toolchain)
            built = command("turso-build", argv, cwd=source, command_env=build_env)
            if built["exit_code"]:
                classes.append("tool-or-environment-error")
                return 2
            library = run / "target" / "debug" / ("libturso_sqlite3.dylib" if system == "Darwin" else "libturso_sqlite3.so")
        required_name = "libturso_sqlite3.dylib" if system == "Darwin" else "libturso_sqlite3.so"
        if not library.is_file() or library.name != required_name:
            classes.append("tool-or-environment-error")
            summary["error"] = "Must select a real Turso shared library with its expected filename"
            return 2
        before_hash = digest(library)
        summary["library"] = {"path": str(library), "sha256_before": before_hash,
                              "provenance": "explicit supplied build; source pin/build provenance must be audited separately" if args.library else "isolated locked build at checked pin"}
        dep = inspect("turso-library-dependencies", library)
        exports = command("turso-exports", ["nm", "-gU", library] if system == "Darwin" else ["nm", "-D", "--defined-only", library])
        if dep["exit_code"] or exports["exit_code"] or re.search(r"libsqlite3[.\-]", raw(dep, "stdout"), re.I):
            classes.append("tool-or-environment-error")
            summary["error"] = "Library inspection failed or SQLite dependency detected"
            return 2
        export_text = raw(exports, "stdout")
        summary["selected_exports"] = {symbol: bool(re.search(r"\b_?" + symbol + r"$", export_text, re.M)) for symbol in ["sqlite3_open", "sqlite3_backup_init", "sqlite3_auto_extension", "sqlite3_preupdate_hook"]}
        if not summary["selected_exports"]["sqlite3_open"]:
            classes.append("tool-or-environment-error")
            return 2
        compiler = command("compiler-version", [args.cc, "--version"], timeout=30)
        if compiler["exit_code"]:
            classes.append("tool-or-environment-error")
            return 2
        # Same reduced header for both engines; missing required public ABIs are
        # declared in the link-only fixture, not silently implemented.
        header = source / "bindings" / "c" / "include"
        for engine in ["sqlite", "turso"]:
            for name in ["subset", "required_api", "backup"]:
                binary = run / (engine + "-" + name)
                argv = [args.cc, "-std=c11", "-O0", "-Wall", "-Wextra", "-I", str(header), ROOT / "tests" / "compatibility" / (name + ".c"), "-o", binary]
                argv += [library] if engine == "turso" else ["-lsqlite3"]
                if system == "Linux":
                    argv += ["-ldl"]
                linked = command(engine + "-" + name + "-link", argv)
                classification = classify_link(linked, raw(linked, "stderr"))
                if classification != "linked":
                    if engine == "sqlite":
                        classification = "control-unavailable"
                    fixture(engine, name, classification, link_exit_code=linked["exit_code"], link_returncode=linked.get("returncode"))
                    continue
                if engine == "turso":
                    # Cargo's Darwin install-name can name target/debug/deps.
                    # Rewrite only the generated executable, never the input dylib,
                    # so runtime must load the exact explicitly selected file.
                    if system == "Darwin":
                        original = inspect(engine + "-" + name + "-dependencies-original", binary)
                        references = [line.strip().split(" (")[0] for line in raw(original, "stdout").splitlines()[1:] if "libturso_sqlite3.dylib" in line]
                        if original["exit_code"] or len(references) != 1:
                            fixture(engine, name, "tool-or-environment-error")
                            continue
                        if references[0] != str(library):
                            patched = command(engine + "-" + name + "-select-library", ["install_name_tool", "-change", references[0], library, binary])
                            if patched["exit_code"]:
                                fixture(engine, name, "tool-or-environment-error")
                                continue
                    deps = inspect(engine + "-" + name + "-dependencies", binary)
                    if deps["exit_code"] or not linkage_ok(raw(deps, "stdout"), library, system):
                        fixture(engine, name, "tool-or-environment-error", reason="exclusive Turso linkage not verified")
                        continue
                else:
                    deps = inspect(engine + "-" + name + "-dependencies", binary)
                    if deps["exit_code"]:
                        fixture(engine, name, "control-unavailable", reason="system SQLite linkage inspection unavailable")
                        continue
                if name == "required_api":
                    fixture(engine, name, "linked", reason="link-only; null-argument fixture is deliberately never executed")
                    continue
                paths = [run / (engine + "-" + name + "-source.db")]
                if name == "backup":
                    paths.append(run / (engine + "-" + name + "-destination.db"))
                executed = command(engine + "-" + name + "-run", [binary, *paths], command_env=runtime_env(library if engine == "turso" else None))
                stdout, stderr = raw(executed, "stdout"), raw(executed, "stderr")
                classification = classify_backup(executed, stderr)
                if executed["exit_code"] == 0 and ("PASS " + name + ":" not in stdout or "ENGINE_LIBRARY=" not in stdout):
                    classification = "unexplained-runtime-failure"
                if engine == "sqlite" and classification in BLOCKERS:
                    classification = "unexplained-runtime-failure"
                fixture(engine, name, classification, run_exit_code=executed["exit_code"], run_returncode=executed.get("returncode"),
                        observations=[line for line in stdout.splitlines() if line.startswith(("ENGINE_LIBRARY=", "PASS ", "CALL "))])
        # Compare semantic observations, excluding the intentionally different image paths.
        subsets = [f for f in summary["fixtures"] if f["fixture"] == "subset" and f["classification"] == "passed"]
        if len(subsets) == 2:
            summary["subset_differential_equal"] = [s for s in subsets[0]["observations"] if s.startswith("PASS ")] == [s for s in subsets[1]["observations"] if s.startswith("PASS ")]
            if not summary["subset_differential_equal"]:
                classes.append("unexplained-semantic-difference")
        return overall(classes)[1]
    except (OSError, ValueError) as exc:
        classes.append("tool-or-environment-error")
        summary["error"] = str(exc)
        return 2
    finally:
        summary["sources_after"] = {name: baseline.check_source(ROOT / "upstream" / name, pin) for name, pin in PINS.items()}
        if not all(s["ok"] for s in summary["sources_after"].values()):
            classes.append("source-changed-during-run")
        try:
            if "lock_sha256_before" in summary:
                summary["lock_sha256_after"] = digest(source / "Cargo.lock")
                if summary["lock_sha256_after"] != summary["lock_sha256_before"]:
                    classes.append("source-changed-during-run")
            if before_hash:
                summary["library"]["sha256_after"] = digest(library)
                if summary["library"]["sha256_after"] != before_hash:
                    classes.append("tool-or-environment-error")
        except OSError as exc:
            classes.append("tool-or-environment-error")
            summary["postflight_error"] = str(exc)
        summary["status"], summary["exit_code"] = overall(classes)
        save()
        outcome.update(summary)
        print(f"{summary['status']}: exit {summary['exit_code']} (see {run / 'result.json'})", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, help="Explicit already-built libturso_sqlite3 shared library; never falls back to SQLite")
    parser.add_argument("--toolchain", default="1.95.0", help="Explicit already-installed Rust toolchain for the default isolated build")
    parser.add_argument("--artifacts", type=Path, default=ROOT / "artifacts" / "compatibility")
    parser.add_argument("--cc", default="cc", help="Existing C compiler executable (not a shell command)")
    parser.add_argument("--timeout", type=int, default=900, help="Per-command timeout seconds")
    args = parser.parse_args()
    return run_spike(args)


if __name__ == "__main__":
    sys.exit(main())
