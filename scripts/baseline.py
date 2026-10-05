#!/usr/bin/env python3
"""Phase 0 capture runner. Python 3.11+ standard library only."""
import argparse
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib

PINS = {
    "trailbase": "12d3343d7d78c8e4dd65af264a3244f472de450d",
    "turso": "e6c79b43cabde627ab9eb4eaa20c2d3e6d384d7c",
}
ROOT = Path(__file__).resolve().parents[1]


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def new_run(artifacts):
    artifacts = Path(artifacts).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(tempfile.mkdtemp(prefix=stamp + "-", dir=artifacts))


def capture(run, name, argv, cwd, env=None, timeout=None):
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
        raise ValueError("artifact name must be a single safe path component")
    started = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    result = {"argv": argv, "cwd": str(Path(cwd).resolve()), "started_utc": started,
              "stdout": name + ".stdout", "stderr": name + ".stderr",
              "timeout_seconds": timeout}
    # Exclusive creation is deliberate: never destroy evidence from a previous command.
    with (run / result["stdout"]).open("xb") as out, (run / result["stderr"]).open("xb") as err:
        try:
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=out, stderr=err,
                                       start_new_session=(os.name == "posix"))
        except OSError as exc:
            err.write((str(exc) + "\n").encode())
            result.update(exit_code=127 if exc.errno == errno.ENOENT else 126,
                          returncode=None, launch_errno=exc.errno,
                          capture_error="command or cwd not found" if exc.errno == errno.ENOENT else "command launch failed")
        else:
            try:
                returncode = process.wait(timeout=timeout)
                result["returncode"] = returncode
                result["exit_code"] = returncode if returncode >= 0 else 128 - returncode
            except subprocess.TimeoutExpired:
                stop_command(process)
                result.update(exit_code=124, returncode=None, capture_error="timeout; partial raw output preserved")
            except BaseException:
                stop_command(process)
                raise
    result["duration_seconds"] = round(time.monotonic() - start, 3)
    result["test_counts"] = test_counts((run / result["stdout"]).read_bytes())
    write_json(run / (name + ".json"), result)
    return result


def stop_command(process):
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    process.wait()


def test_counts(raw):
    matches = re.findall(rb"test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", raw)
    if not matches:
        return None  # Not zero tests passing: no executed-suite proof available.
    keys = ["passed", "failed", "ignored", "measured", "filtered_out"]
    return {"suites": len(matches), **{key: sum(int(m[i]) for m in matches) for i, key in enumerate(keys)}}


def check_source(path, expected):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(path), *args], stderr=subprocess.STDOUT).decode("utf-8", "replace")
    check = {"path": str(path), "expected_pin": expected, "problems": []}
    try:
        check["actual_pin"] = git("rev-parse", "HEAD").strip()
        check["status"] = git("status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none")
        check["submodules"] = git("submodule", "status", "--recursive")
        if check["actual_pin"] != expected:
            check["problems"].append("pin mismatch")
        if check["status"]:
            check["problems"].append("dirty source")
        if any(line and line[0] != " " for line in check["submodules"].splitlines()):
            check["problems"].append("unready nested submodule")
    except subprocess.CalledProcessError as exc:
        check["problems"].append("source inspection failed")
        check["error"] = exc.output.decode("utf-8", "replace")
    check["ok"] = not check["problems"]
    return check


def baseline(args):
    run = new_run(args.artifacts)
    print("Raw baseline artifacts: " + str(run), flush=True)
    sources = {name: check_source(ROOT / "upstream" / name, pin) for name, pin in PINS.items()}
    write_json(run / "sources-before.json", sources)
    summary = {"schema_version": 1, "run_dir": str(run), "sources_before": sources,
               "commands": [], "exit_code": 0, "status": "running"}
    write_json(run / "result.json", summary)
    if not all(s["ok"] for s in sources.values()):
        summary.update(exit_code=2, status="source-preflight-blocked")
        write_json(run / "result.json", summary)
        return 2

    source = ROOT / "upstream" / "trailbase"
    if args.toolchain:
        installed = capture(run, "installed-toolchains", ["rustup", "toolchain", "list"], source, timeout=30)
        names = (run / installed["stdout"]).read_text().splitlines()
        if installed["exit_code"] or not any(line.split()[0] == args.toolchain or line.split()[0].startswith(args.toolchain + "-") for line in names if line.split()):
            summary.update(exit_code=2, status="requested-toolchain-not-installed")
            write_json(run / "result.json", summary)
            return 2
    cargo = ["cargo"] + (["+" + args.toolchain] if args.toolchain else [])
    rustc = ["rustc"] + (["+" + args.toolchain] if args.toolchain else [])
    manifest = tomllib.loads((source / "Cargo.toml").read_text())
    config = source / ".cargo" / "config.toml"
    env = os.environ.copy()
    # Keep build products outside upstream; forbid build.rs from selecting a mutable JS lockfile.
    env.update(CARGO_TARGET_DIR=str((ROOT / "artifacts" / "baseline-target").resolve()),
               PNPM_OFFLINE="TRUE", RUST_BACKTRACE="1", RUSTUP_AUTO_INSTALL="0")
    details = {
        "platform": platform.platform(), "machine": platform.machine(), "python": sys.version,
        "toolchain_argument": args.toolchain, "upstream_ci_toolchain": "1.98.1",
        "tool_paths": {tool: shutil.which(tool) for tool in ["cargo", "rustc", "rustup", "cc", "clang", "ld", "protoc", "pnpm", "node", "pkg-config", "geos-config"]},
        "overrides": {key: env[key] for key in ["CARGO_TARGET_DIR", "PNPM_OFFLINE", "RUST_BACKTRACE", "RUSTUP_AUTO_INSTALL"]},
        # Record presence only: arbitrary user environment values may contain secrets.
        "inherited_configuration_names": sorted(key for key in os.environ if key.startswith(("CARGO_", "RUST", "CC_", "CXX_")) or key in ["CC", "CXX", "LD", "AR", "CFLAGS", "LDFLAGS", "PROTOC"]),
        "cargo_config": config.read_text(),
        "lock_sha256_before": hashlib.sha256((source / "Cargo.lock").read_bytes()).hexdigest(),
        "workspace_default_members": manifest["workspace"]["default-members"],
        "database_dependency_declarations": {key: value for key, value in manifest["workspace"]["dependencies"].items() if key in ["rusqlite", "sqlite-vec", "sqlite3-parser", "trailbase-sqlite", "trailbase", "litegis", "geos"]},
        "feature_resolution_proof": "See features.stdout; declarations are not a resolved feature graph.",
    }
    write_json(run / "environment.json", details)
    probes = [("rustc", rustc + ["-Vv"]), ("cargo", cargo + ["-V"]),
              ("toolchains", ["rustup", "toolchain", "list"]), ("compiler", ["cc", "--version"]),
              ("linker", ["ld", "-v"]), ("protoc", ["protoc", "--version"]),
              ("pnpm", ["pnpm", "--version"]), ("node", ["node", "--version"]),
              ("disk", ["df", "-h", str(ROOT)])]
    for name, argv in probes:
        capture(run, name, argv, source, env, timeout=30)
    # Upstream test.yml build matrix; extra --locked enforces the pinned dependency graph.
    # Default-member tests are unfiltered. Expanded workspace test includes the CI features,
    # but intentionally does not repeat CI's --skip=postgres or run mutating lefthook hooks.
    commands = [
        ("features", cargo + ["tree", "--locked", "-e", "features", "-i", "rusqlite"]),
        ("build-all-features", cargo + ["build", "--locked", "--all-features"]),
        ("build-no-default-features", cargo + ["build", "--locked", "--all-targets", "--no-default-features"]),
        ("test-default", cargo + ["test", "--locked", "--", "--nocapture"]),
        ("test-workspace", cargo + ["test", "--locked", "--workspace", "--features=geos,otel,pg,wasm", "--", "--nocapture"]),
    ]
    for name, argv in commands:
        print("Capturing " + name, flush=True)
        result = capture(run, name, argv, source, env, timeout=args.timeout)
        summary["commands"].append({"name": name, **result})
        if result["exit_code"] and not summary["exit_code"]:
            summary["exit_code"] = result["exit_code"]
        write_json(run / "result.json", summary)
        print(f"{name}: exit {result['exit_code']}", flush=True)
    after = {name: check_source(ROOT / "upstream" / name, pin) for name, pin in PINS.items()}
    write_json(run / "sources-after.json", after)
    summary["sources_after"] = after
    summary["lock_sha256_after"] = hashlib.sha256((source / "Cargo.lock").read_bytes()).hexdigest()
    if not all(s["ok"] for s in after.values()) or summary["lock_sha256_after"] != details["lock_sha256_before"]:
        summary["exit_code"] = summary["exit_code"] or 2
        summary["status"] = "source-changed-during-run"
    else:
        summary["status"] = "passed" if not summary["exit_code"] else "blocked-or-failed"
    write_json(run / "result.json", summary)
    return summary["exit_code"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    run_parser = sub.add_parser("baseline")
    run_parser.add_argument("--artifacts", type=Path, default=ROOT / "artifacts" / "baseline")
    run_parser.add_argument("--toolchain", default="", help="Already-installed rustup toolchain; never installs or changes the default")
    run_parser.add_argument("--timeout", type=int, default=900, help="Per Cargo command timeout in seconds")
    capture_parser = sub.add_parser("capture")
    capture_parser.add_argument("--artifacts", type=Path, required=True)
    capture_parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.mode == "baseline":
        return baseline(args)
    argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    if not argv:
        parser.error("capture requires a command after --")
    run = new_run(args.artifacts)
    print(run, flush=True)
    return capture(run, "command", argv, Path.cwd())["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
