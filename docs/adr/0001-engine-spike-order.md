# ADR 0001: Prove engine compatibility before lifecycle abstraction

Status: Accepted for the experiment

## Decision

Evaluate TrailBase unchanged against SQLite first. Inventory its actual connection ownership, SQL, callbacks, extensions, and Cargo features. Attempt Turso's SQLite-compatible C API substitution in isolation next (Route A), preserving the existing database tests.

Only consider a small adapter (Route B) for narrow, evidenced incompatibilities. A native Rust integration (Route C) needs a separate estimate after Route A evidence. Do not add a provider, router, leases, snapshots, or cloud storage emulation before the engine gate.

## Reproducibility

Pin exact upstream Git revisions using submodules. Keep original upstream sources unmodified for the baseline. Put experiment build configuration and scripts outside those sources where possible, and record any temporary patch exactly. Preserve raw command output and distinguish environment failures from engine incompatibility.

## Consequences

The first implementation slice may legitimately end with a reproducible blocker report instead of a running server. Missing symbols or unsupported semantics must not be hidden by broad test skips or fallback linking to SQLite. No aggregate pass rate proves correctness.

The real cloud provider remains blocked on its actual bootstrap, commit durability, cache recovery, retention/PITR, and storage-enforced fencing contract. Public embedded-engine APIs do not establish these guarantees.
