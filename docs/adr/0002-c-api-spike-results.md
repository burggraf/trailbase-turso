# ADR 0002: Stop Route A at observed required-API blockers

Status: Proposed, based on the bounded pinned C fixture experiment

## Context

ADR 0001 requires compatibility evidence before a provider/lifecycle abstraction. At TrailBase `12d3343d7d78c8e4dd65af264a3244f472de450d` and Turso `e6c79b43cabde627ab9eb4eaa20c2d3e6d384d7c`, the standalone subset matches system SQLite, but exclusive Turso linking cannot resolve the required `sqlite3_auto_extension` and `sqlite3_preupdate_hook`. The exported `sqlite3_backup_init` links but aborts at its panic stub. System SQLite links the required API fixture and successfully copies the backup control row.

## Proposed decision

Stop the substitution spike without patching rusqlite, adding a broad adapter, or introducing a native backend/provider/router. Route A is not viable unchanged at these pins. Required extension startup, realtime hooks, and backup need upstream implementation or an explicitly scoped alternative. Estimate Route C separately only after a product/architecture decision; do not assume the native API preserves these behaviors.

## Consequences

This is a reproducible blocker report, not a running TrailBase process or a complete compatibility assessment. The unchanged upstream SQLite baseline capture completed with build/environment blockers and no executed-suite counts (see [baseline evidence](../baseline.md)); no TrailBase-on-Turso tests were run. PRAGMA, migration, UDF/security, vector, transaction/realtime, crash/restart and concurrency parity remain unknown. No cloud-storage guarantee follows.

See [the compatibility matrix](../compatibility-matrix.md) and `docs/compatibility-results.json` for exact raw paths, statuses, library identity and residual risks. The runner returns blocked/nonzero rather than promoting subset controls into application passes.
