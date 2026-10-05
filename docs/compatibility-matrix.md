# Route A compatibility matrix (bounded C spike)

**Verdict: blocked at the pinned C API.** This is not a TrailBase-on-Turso build or test pass. Stop the substitution spike here; any native backend/adapter needs a separate decision and estimate.

Pins: TrailBase `12d3343d7d78c8e4dd65af264a3244f472de450d`; Turso `e6c79b43cabde627ab9eb4eaa20c2d3e6d384d7c`. Both isolated submodules, including TrailBase's nested submodules, were clean at the pins before and after execution. Turso's Cargo.lock and selected dylib SHA-256 were unchanged.

## Observed standalone fixtures

| Fixture | System SQLite control | Exclusive Turso C library | Classification / severity | Candidate action |
|---|---|---|---|---|
| File-backed open/create, prepared INSERT/SELECT, bound/read NULL/INTEGER/REAL/TEXT/BLOB, commit, update+insert rollback, close/reopen | pass, exit 0 | pass, exit 0; identical asserted values | subset-only control, **not application proof** | No expansion before API blockers are addressed |
| Required API link: `sqlite3_auto_extension` + `sqlite3_preupdate_hook` | links, exit 0; intentionally not executed | linker lists both undefined symbols, exit 1; both absent from `nm -gU` | missing-required-api / **blocker** | Implement upstream API/semantics or separately estimate replacement startup/vector/realtime paths |
| Backup: open two file databases, insert 42, `sqlite3_backup_init`/step/finish, read destination | pass, exit 0; copied row 42 | links, then `sqlite3_backup_init` panics in `bindings/c/src/lib.rs:1984`; SIGABRT, Python returncode -6, shell-normalized exit 134 | panic-abort-backup-stub / **blocker** | Implement backup or separately design/validate a replacement |

The subset asserts an exact 64-bit integer beyond double precision, real 1.25, UTF-8 text, a blob containing NUL and 0xff, NULL, one surviving row, and rollback-restored text. Reopen visibility is **not** a crash, power-loss, concurrency, or durability guarantee. The required-API fixture uses SQLite public ABI declarations because Turso's reduced header omits them. Its null arguments are link probes only; the binary is never run.

These APIs are concrete TrailBase dependencies: CLI auto-extension startup (`upstream/trailbase/crates/cli/src/bin/trail.rs:52-55`); realtime preupdate hook (`crates/core/src/records/subscribe/hook.rs:39-53`); backup/restore (`crates/sqlite/src/sqlite/util.rs:147-189`). See the separately owned inventory/reconnaissance reports for the broader surface; this matrix does not exhaust it.

## Unchanged upstream application tests

| Test/workflow | SQLite TrailBase baseline | Turso TrailBase result | Severity / missing proof |
|---|---|---|---|
| Unchanged upstream build/unit/integration suites | **baseline pending/unverified** | not attempted; API gate blocked | blocker; no substituted rusqlite/libsqlite3-sys build |
| Migrations / schema upgrades / PRAGMAs | **baseline pending/unverified** | unverified | high; no application migrations run |
| Auth signup/login / record CRUD / admin | **baseline pending/unverified** | unverified | high; no TrailBase process started |
| Realtime subscriptions / rollback event visibility | **baseline pending/unverified** | API link blocked; application behavior unverified | blocker; no hook or CDC parity proof |
| Vector extension / sqlite-vec / optional FTS or tenant SQL | **baseline pending/unverified** | auto-extension link blocked; other behavior unverified | blocker/high; no extension equivalence proof |
| Application backup/restore / attached databases | **baseline pending/unverified** | backup C runtime blocked; application behavior unverified | blocker; no multi-database consistency proof |
| Crash/restart / concurrency / custom UDF security flags | **baseline pending/unverified** | unverified | high; standalone controls do not establish these semantics |

**Integration update:** the unchanged baseline capture has now completed, but is **blocked, not passing**: both build variants and both test commands exited 101, with no executed-suite counts. All hit missing offline pnpm metadata; default tests also hit `assert_matches` E0658 on Rust 1.95.0. See [baseline evidence](baseline.md). The table's pending/unverified cells describe the fixture experiment's original state and still mean application parity is unverified; they are not baseline passes.

System SQLite C fixtures are **not** TrailBase's bundled rusqlite baseline. No aggregate application pass rate is inferred.

## Reproduction and evidence

From the integrated repository:

```sh
git submodule update --init --recursive
# Default: explicit installed Rust 1.95.0, locked isolated debug build; no install/default change.
scripts/run-compatibility.sh --toolchain 1.95.0
# Or select an existing real library, with no SQLite fallback:
scripts/run-compatibility.sh \
  --library /Users/markb/dev/trailbase-turso/artifacts/turso-target/debug/libturso_sqlite3.dylib \
  --artifacts /Users/markb/dev/trailbase-turso/artifacts/compatibility --timeout 120
python3 -m unittest discover -s tests/tooling -p test_compatibility.py
```

The original isolated-worktree validation used the parent's baseline helper via `PYTHONPATH`; the integrated repository imports it directly from `scripts/`, with no override needed. Python 3.11+ and existing `cc` are required; macOS uses existing `otool`, `nm`, `install_name_tool`, Linux uses `ldd`, `nm`. No dependency tooling is installed.

Exit **1 / blocked** means an observed engine incompatibility. Exit **2** means source/tool/environment or unexplained failure, even if blockers were also observed. Exit 0 is only “subset-only-no-blocker-observed,” never “TrailBase works.” All command records preserve argv/cwd, raw stdout/stderr, original returncode, normalized exit code and capture errors. The runner stops after these three fixtures; it does not invoke the TrailBase suites.

Raw evidence (generated outside the worktree, retained through integration):

- Successful control comparison / blocked verdict: `/Users/markb/dev/trailbase-turso/artifacts/compatibility/20261005T232534Z-twy5oee0/`. See `result.json`, `turso-required_api-link.stderr`, `turso-backup-run.{json,stdout,stderr}`, `turso-{subset,backup}-dependencies.stdout`, and system control streams. `inputs/` snapshots the run's fixtures/runner/header, with hashes in the result.
- Earlier harness/environment error: `/Users/markb/dev/trailbase-turso/artifacts/compatibility/20261005T232414Z-4gsii84o/`. System SQLite's shared-cache path has no on-disk file, so the first identity check returned 90. It is **not** a SQLite failure or engine blocker. The correction allows shared-cache system images while still requiring exact on-disk Turso identity.
- Final tooling tests: `/Users/markb/dev/trailbase-turso/artifacts/compatibility/20261005T232633Z-y5duwkqh/` (8 tests, exit 0). Tests were introduced before implementation (initial missing-script failure); additional Linux path rejection tests failed before the parser correction. The corrected Linux parser is unit-tested only; Darwin evidence above is unaffected.
- Supplied real Turso build: `/Users/markb/dev/trailbase-turso/artifacts/turso-build/20261005T231039Z-mltygr47/command.{json,stdout,stderr}`; exit 0, `cargo +1.95.0 build --locked -p turso_sqlite3 --features capi`.

The Turso fixture link argv contains the absolute real dylib and **no `-lsqlite3`**. `otool -L` shows only that chosen dylib and libSystem in the fixture, and no libsqlite3 dependency in the chosen Turso image. Cargo's original install-name points at `debug/deps`; only the generated executables' load commands are rewritten to the explicitly chosen `debug` file. `dladdr(sqlite3_open)` and realpath validate that exact loaded file before each runtime control. Loader injection/search overrides are removed; the library hash remains `9c9bd5843977cb4131d5c747a466f2396645b1d9e6d32a2ac31dd3b352d0dddf` before/after. The link failure separately corroborates the missing exports. See `compatibility-results.json` for structured references.

## Residual risks

No complete undefined-symbol inventory, rusqlite substitution, unchanged TrailBase test results, startup, migration/UDF/PRAGMA semantics, sqlite-vec parity, realtime equivalence, application backup/restore, crash recovery, or concurrency proof. The supplied-library mode records identity/hash but cannot establish arbitrary caller-supplied build provenance; this run uses the separately captured real build above. The default isolated-build configuration is unit-tested, not rebuilt during this bounded run. Linux execution is unverified. Neither local reopen visibility nor a native API establishes Turso Cloud storage guarantees.
