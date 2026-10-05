# Phase 0: unmodified TrailBase baseline

This report covers SQLite baseline tooling only. It does not assess Turso C compatibility or change upstream sources, dependency locks, pins, or toolchain defaults.

## Reproduce

Prerequisites: Python 3.11+, Git, an already-installed compatible Rust toolchain, and the initialized pinned upstream/nested submodules. The wrapper may be invoked from any directory:

```sh
python3 -m unittest discover -s tests/tooling -v
scripts/run-baseline.sh --toolchain 1.95.0 --timeout 600
```

Omit `--toolchain` to use the active toolchain. An explicit missing toolchain is rejected before invoking Cargo; auto-install is disabled. The captured run uses already-installed Rust 1.95.0 rather than active 1.91.1; upstream core's declared minimum is 1.95, while CI uses 1.98.1. No tools are installed by this runner. Normal locked Cargo dependency fetching is allowed.

The runner exits with the first failed Cargo command's exit code (or 2 for invalid source/toolchain prerequisites). It still attempts both build variants and both test suites so the result identifies missing test proof independently of build failures. Each Cargo command has a bounded timeout, recorded as exit 124 with partial raw output retained. On POSIX hosts, commands run in isolated process groups; timeout/interruption kills that group before finalizing evidence. Missing commands record exit 127; permission/format and other launch errors record exit 126, diagnostics and errno. Non-POSIX descendant cleanup is not established. Pin mismatch, dirty tracked/untracked source, uninitialized/mismatched nested submodules, and changed lockfiles are not accepted as a clean baseline.

## Actual upstream requirements and commands

Inspected at the pinned revision:

- `.github/workflows/test.yml`: build matrix `cargo build --all-features` and `cargo build --all-targets --no-default-features`; CI toolchain 1.98.1.
- `lefthook.yml`: Rust workspace tests enable `geos,otel,pg,wasm`, with `--nocapture` and an upstream `--skip=postgres`. The baseline deliberately **does not skip postgres**. A default-member unfiltered suite is attempted separately. PostgreSQL-dependent tests may need an external service.
- `.github/actions/setup_build/action.yml`: Ubuntu CI installs SSL, pkg-config, libclang, protobuf and GEOS, plus fake sendmail. This run uses the existing macOS tools instead; it is not CI parity.
- `.github/actions/setup_pnpm/action.yml`: CI uses Node 22 and pnpm ^12 with installed workspace JS dependencies. Local Node/pnpm differ; these are captured, not changed.
- `crates/assets/build.rs` and `crates/build/src/lib.rs`: Cargo builds the admin JS bundle via pnpm. `PNPM_OFFLINE=TRUE` forces frozen-lockfile/offline dependency use rather than permitting a lockfile-changing fallback. The runner does not install/prepopulate JS dependencies.
- `crates/core/build.rs`: protobuf generation requires protoc. `.cargo/config.toml` only sets `TS_RS_EXPORT_DIR`; its commented Linux linker/static flags are not active.
- `Cargo.toml`: default members include the CLI, core, SQLite/extension/schema crates, clients, assets and WASM runtime crates. The full workspace includes guests/examples beyond those default members.

All Cargo commands run in `upstream/trailbase`, with `--locked` added to preserve dependencies:

```text
cargo +1.95.0 tree --locked -e features -i rusqlite
cargo +1.95.0 build --locked --all-features
cargo +1.95.0 build --locked --all-targets --no-default-features
cargo +1.95.0 test --locked -- --nocapture
cargo +1.95.0 test --locked --workspace --features=geos,otel,pg,wasm -- --nocapture
```

`CARGO_TARGET_DIR` is the ignored `artifacts/baseline-target`; `RUST_BACKTRACE=1`. No `--ignore-rust-version`, source patch, test filter or broad skip is introduced. Lefthook itself is not invoked because its hooks can fix/stage upstream files and run unrelated client tooling.

## Evidence layout

Each invocation creates a unique `artifacts/baseline/<UTC timestamp>-<random suffix>/` directory, never a reused `latest` directory:

- `<command>.stdout` / `.stderr`: separate, full raw byte streams, including failures.
- `<command>.json`: exact argv, cwd, UTC start, duration, exit/return code, timeout and stream paths.
- `environment.json`: OS/architecture, selected toolchain, tool locations, source Cargo configuration, declared database dependencies/default members and lockfile SHA-256.
- `sources-before.json` / `sources-after.json`: pins, source status, nested submodule status.
- `result.json`: all Cargo outcomes and post-run integrity checks.
- Tool versions/compiler/linker/disk probes have their own raw streams and JSON records.

No whole environment dump is taken. Arbitrary inherited compiler/Cargo environment values are not copied because they may contain secrets; only variable names are recorded. Captured tool probes/source configuration and explicit overrides provide configuration evidence for this run. `features.stdout` is the resolved **default** rusqlite feature graph, distinct from manifest declarations and the expanded build/test feature variants.

Recognized stable libtest summary lines are normalized to JSON counts (passed/failed/ignored/measured/filtered plus suites). `test_counts: null` means no executed-suite proof, **not zero tests passed**. Raw output remains authoritative. Ignored upstream tests are recorded, never represented as passes.

Durable environment/results are in `docs/baseline-environment.json` and `docs/baseline-results.json`. Raw artifacts are intentionally ignored and local; archive them out of band if moving this evidence to another machine. Inspect a new run before updating durable snapshots; the runner never overwrites tracked reports.

## Captured inputs and local environment

| Input | Value |
|---|---|
| Experiment repository base | `f6d057b9518f403b8e0f718b0e9c26381a774ff6` |
| TrailBase | https://github.com/trailbaseio/trailbase.git at `12d3343d7d78c8e4dd65af264a3244f472de450d` |
| Turso (provenance only, not built) | https://github.com/tursodatabase/turso.git at `e6c79b43cabde627ab9eb4eaa20c2d3e6d384d7c` |
| Nested rmcp-openapi-minimal | `deac51f04b37e2d01b83e403fd22e4fa5acba800` |
| Nested sqlite-vec | `d0006d774bc8f0f8bee3b3be8353f7299088adbd` |
| OS / Rust host | macOS 27.0.1 arm64 / `aarch64-apple-darwin` |
| Rust / Cargo | 1.95.0 / 1.95.0 (explicit installed toolchain) |
| Compiler / linker | Apple clang 21.0.0 / Apple ld 27037.1 |
| protoc / pnpm / Node | 36.0 / 11.22.0 / v26.7.0 |
| Cargo.lock SHA-256 before build | `9c41c3b80f912fdaea3ecfd4eb44f4bcf2b25213c67839eef06eae2a88379fb9` |

Both upstreams and nested submodules passed clean-source checks before building. No inherited Cargo/Rust/compiler environment overrides were present. No user or ancestor Cargo config was found in the inspected working-directory hierarchy. Compiler/linker defaults therefore apply; no linker override was introduced.

The resolved default-member graph enables rusqlite 0.40.2 features `backup`, `bundled`, `cache`, `column_decltype`, `default`, `ffi-sqlite-wasm-rs`, `functions`, `hashlink`, `hooks`, `modern_sqlite`, `preupdate_hook`. In particular, manifest `default-features=false` does **not** prove that Cargo's unified graph has no default features. The default CLI enables geos/mcp/wasm; its workspace core dependency also enables pg. This is still the SQLite baseline, not a Turso substitution.

## Recorded result

**Completed capture; baseline blocked, not passing.** Raw evidence is in `artifacts/baseline/20261005T225822Z-0yca3754/`. The resolved feature query exited 0. Both build variants, the default-member test command, and the expanded workspace test command exited **101**, without a timeout. The wrapper propagated exit 101.

| Command record | Exit | Duration | Executed test counts |
|---|---:|---:|---|
| `features` | 0 | 8.480 s | Not applicable |
| `build-all-features` | 101 | 580.344 s | Not applicable |
| `build-no-default-features` | 101 | 540.130 s | Not applicable |
| `test-default` | 101 | 245.519 s | Unavailable (`null`) |
| `test-workspace` | 101 | 216.151 s | Unavailable (`null`) |

Two observed blockers are separated from any prototype regression:

1. **Environment / missing offline JS metadata:** all four build/test commands fail in the unchanged `trailbase-assets` build script. Its `pnpm --dir js/admin install --frozen-lockfile --offline` emits `[ERR_PNPM_NO_OFFLINE_META] Failed to resolve barrelize` for `/Users/markb/Library/Caches/pnpm/v11/metadata-full/registry.npmjs.org/barrelize.jsonl`. Exact passages are in `build-all-features.stderr:696-900`, `build-no-default-features.stderr:384-525`, `test-default.stderr:111-287`, and `test-workspace.stderr:98-287`. This runner intentionally requires prepopulated JS dependencies; it did not fetch JS dependencies online or replace locks to bypass this requirement.
2. **Pinned upstream test / selected-toolchain mismatch:** `test-default.stderr:75-109` additionally reports Rust E0658 (`use of unstable library feature assert_matches`) at `crates/client/tests/client_integration_test.rs:4`, `:252`, and `:455`, using installed Rust 1.95.0. This is not a Turso failure. Whether upstream CI's 1.98.1 resolves it is untested; no newer toolchain, unstable workaround, or test patch was introduced.

Both source trees and nested pins remain clean after the run. Cargo.lock SHA-256 is unchanged at `9c41c3b80f912fdaea3ecfd4eb44f4bcf2b25213c67839eef06eae2a88379fb9`. Durable environment/result JSON files are byte-for-byte copies of the raw run's corresponding JSON, not edited success summaries.

**Missing proof:** no successful full build, no executed upstream test-suite counts/pass rate, no server startup/API workflow baseline, and no CI-toolchain/platform parity. Four failed commands are not four failing test cases. Further application/engine claims remain blocked pending environment preparation and rerun; no upstream builds/tests were repeated during finalization.

Tooling validation passed **14 tests, 0 failures**, plus shell syntax and diff checks. Final validation evidence is retained under `artifacts/tooling/20261005T232645Z-demgyomk/` (`command.stdout`, `command.stderr`, `command.json`), including byte-identical JSON copy checks. New-file whitespace checks also passed. The parent preserved the pre-finalization files in `artifacts/recovery/baseline-partial.tar.gz` (verified SHA-256 `464b526409466ff1b2b155904cd3a74b6dda179d20c9cb6738a908b1f7f838c5`).

## Tooling regression coverage

Tests were written before the capture helper (initial run failed because the helper did not exist). Standard-library tests cover exact binary stdout/stderr, nonzero CLI propagation, missing command, signal exit, partial timeout evidence, unique/exclusive artifacts, safe artifact names, libtest count normalization, matching/mismatched pins, tracked/untracked dirtiness, nested readiness, and blocking before Cargo for invalid inputs. No dependency or upstream test modification is needed.
