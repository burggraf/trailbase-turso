# trailbase-turso

A compatibility-first experiment to determine whether TrailBase can run on the embedded Turso engine. **Not yet a working TrailBase-on-Turso server.**

## Current result

- The pinned Turso SQLite C library builds; bounded value/transaction/reopen controls match system SQLite.
- Unchanged Route A substitution is blocked: `sqlite3_auto_extension` and `sqlite3_preupdate_hook` are missing; `sqlite3_backup_init` aborts at a panic stub.
- The unmodified TrailBase baseline build/test attempts are blocked by missing offline pnpm dependencies and a Rust test/toolchain mismatch. No upstream test pass rate or application parity is established.

See [baseline evidence](docs/baseline.md), [SQLite dependency inventory](docs/sqlite-dependency-inventory.md), [C API reconnaissance](docs/turso-c-api-reconnaissance.md), [compatibility matrix](docs/compatibility-matrix.md), and [integrated verification](docs/verification.md).

## Reproduce

```sh
git submodule update --init --recursive
python3 -m unittest discover -s tests/tooling -v
scripts/run-baseline.sh --toolchain 1.95.0 --timeout 600
scripts/run-compatibility.sh --toolchain 1.95.0
```

Prerequisites: Python 3.11+, Git, an already-installed compatible Rust toolchain, and a C compiler. The compatibility runner supports macOS (`otool`, `nm`, `install_name_tool`) and Linux (`ldd`, `nm`); only macOS execution has been checked. TrailBase additionally requires its JS/native build prerequisites; see the baseline report. Scripts do not install tooling or change toolchain defaults, but Cargo may fetch locked dependencies.

The compatibility runner exits **1** for observed engine blockers, **2** for source/tool/environment or unexplained failures, and **0** only for its bounded subset—not application acceptance. To reuse a built engine, pass `--library /absolute/path/to/libturso_sqlite3.dylib` (Linux: `.so`).

Raw command output, statuses, input snapshots, and generated databases stay local under ignored `artifacts/`. Checked-in JSON records reference those local artifacts; raw evidence is not included in a clone. Do not publish credentials or runtime databases.

## Scope and next decision

See [the implementation plan](trailbase-turso-prototype-plan.md), [ADR 0001](docs/adr/0001-engine-spike-order.md), and [proposed ADR 0002](docs/adr/0002-c-api-spike-results.md).

Next: prepare and rerun the unchanged baseline, then decide whether to implement the required C APIs upstream or separately estimate a native Rust backend. Do not add tenant providers/orchestration before engine compatibility is established. Cloud storage still requires its actual durability, recovery, and fencing contract; local tests do not prove Turso Cloud guarantees.

Upstreams are exact pinned Git submodules under `upstream/`. Clone with `git clone --recurse-submodules`.
