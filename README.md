# trailbase-turso

A compatibility-first experiment to determine whether TrailBase can run on the embedded Turso engine.

See [the implementation plan](trailbase-turso-prototype-plan.md) and [ADR 0001](docs/adr/0001-engine-spike-order.md).

## Scope

Start with pinned upstream sources, an unmodified SQLite baseline, a source-level dependency inventory, and an isolated SQLite C API substitution attempt. Do not build tenant orchestration until engine compatibility is established.

This repository is an experiment coordinator, not yet a working TrailBase fork or a Turso Cloud implementation. Local storage tests do not establish cloud durability.

## Upstream sources

The upstream repositories will be tracked as pinned submodules under `upstream/`. Clone with `git clone --recurse-submodules` or run `git submodule update --init --recursive`.

Baseline and compatibility commands, results, and prerequisites will be recorded under `docs/` as they are established. Raw execution artifacts remain local under `artifacts/`; never publish credentials or runtime databases.
