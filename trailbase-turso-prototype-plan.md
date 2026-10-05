# TrailBase + Turso Engine: Prototype and Validation Plan

**Status:** Draft for implementation  
**Purpose:** Determine whether TrailBase can run correctly on the embedded Turso engine today, while preserving a clean path to a future Turso Cloud-backed storage implementation.  
**Primary rule:** Prove database compatibility before investing in scale-to-zero orchestration.

## 1. Executive summary

Build a small, controlled TrailBase fork with a tenant database boundary that prevents TrailBase application logic from depending directly on local database files.

The work is deliberately split into two independent questions:

1. **Engine compatibility:** Can TrailBase run correctly on the open-source embedded Turso engine?
2. **Storage replaceability:** Can the same TrailBase-facing database interface later open a cloud-backed Turso database without changing TrailBase's auth, record APIs, realtime behavior, migrations, or business logic?

The first prototype uses local durable storage. It does **not** attempt to reproduce Turso Cloud's S3 Express WAL, segmented generations, lazy hydration, compaction, garbage collection, or point-in-time recovery.

The desired eventual architecture is:

```text
request router
    |
    v
tenant runtime (one active writer per tenant)
    |
    v
TrailBase application services
    |
    v
TenantDatabaseProvider
    |
    +-- LocalTursoProvider       (prototype)
    |
    +-- CloudTursoProvider       (future)
            |
            +-- disposable local cache
            +-- durable remote WAL/generations
```

Changing providers may require bootstrap and configuration changes. It should not require changes to TrailBase application/database behavior.

## 2. Goals

- Establish the current TrailBase-to-database call surface.
- Establish the current Turso compatibility gaps that matter to TrailBase.
- Choose the least invasive viable integration route based on test evidence.
- Run TrailBase's tests and representative API workflows against Turso.
- Introduce one narrow tenant database provider boundary.
- Prove that tenant routing and lifecycle logic do not depend on a hard-coded database path.
- Exercise stop, restart, relocation, crash, and cache-loss scenarios with a local test harness.
- Produce a compatibility report and a clear go/no-go recommendation for a cloud-storage integration.

## 3. Non-goals

- Reimplementing Turso Cloud storage.
- Simulating its exact segment, generation, WAL, checkpoint, compaction, or PITR formats.
- Production-ready multi-region scheduling.
- Multiple active writers for one tenant.
- Production billing, quotas, metering, or provisioning UI.
- Claiming that copying a local database to object storage has the same consistency or durability semantics as Turso Cloud.
- Replacing every direct filesystem use in TrailBase before the engine spike proves viable.

## 4. Core invariants

These invariants should guide every design and code-review decision:

1. **Single active writer:** At most one runtime owns write access to a tenant database.
2. **Opaque database location:** TrailBase services receive a database handle, not a path they inspect or manipulate.
3. **Provider-owned durability:** Checkpointing, snapshots, restore, and cache hydration belong below the TrailBase application layer.
4. **Disposable runtime state:** Correctness must not depend on a stopped container or its temporary directory continuing to exist.
5. **Explicit lifecycle:** Open, quiesce, close, snapshot, restore, and destroy are distinct operations with observable results.
6. **No false durability:** The prototype must label which state is authoritative and which state is merely cached.
7. **Compatibility before optimization:** No cold-start optimization work until correctness tests pass.

## 5. Questions the prototype must answer

### TrailBase dependency surface

- Which crates and modules create or own SQLite connections?
- Does TrailBase use `rusqlite`, SQLx, direct SQLite C calls, or more than one path?
- Which `rusqlite` optional features are enabled?
- Which SQLite C APIs, callbacks, hooks, backup APIs, custom functions, collations, virtual tables, or extension-loading mechanisms are used?
- Which SQL features, PRAGMAs, triggers, views, FTS features, JSON functions, schema-introspection queries, and migration behaviors are required?
- Are connection types exposed broadly enough that a native Turso integration would cause a large rewrite?

### Turso compatibility

- Can TrailBase compile through Turso's SQLite-compatible C API?
- If it compiles, which TrailBase tests pass unchanged?
- Are failures caused by missing C symbols, unsupported SQL, semantic differences, concurrency behavior, or test assumptions?
- Can missing functionality reasonably be added upstream or isolated in the fork?
- Would a native Rust API integration provide a meaningful advantage over the compatibility route at this stage?

### Future cloud storage boundary

- What exact handle or configuration will the future cloud-backed engine require?
- Does it expose the same transaction and connection semantics as the local engine?
- Who owns checkpoints, snapshots, retention, PITR, encryption, cache invalidation, and garbage collection?
- Can a new runtime safely open a tenant after total local-cache loss?
- What fencing token or generation check prevents a stale writer from committing?

## 6. Integration strategy

Evaluate the following routes in order. Do not commit to a large refactor until the preceding spike produces evidence.

### Route A — SQLite-compatible C API substitution

Keep TrailBase's current database-facing code substantially unchanged and link the SQLite wrapper against Turso's compatible C library.

**Why first:** It is the fastest way to turn uncertainty into a concrete list of missing symbols and behavioral incompatibilities.

**Exit conditions:**

- TrailBase builds and a meaningful majority of database tests pass; or
- the failures demonstrate that the C compatibility layer is not currently viable.

### Route B — small compatibility adapter

Keep existing TrailBase abstractions, but isolate a limited number of unsupported calls or semantic differences behind a local adapter.

Use this only when Route A failures are narrow, well understood, and maintainable.

### Route C — native Turso Rust backend

Introduce a database implementation using Turso's native Rust API.

Use this when either:

- Route A is blocked by broad C API or SQL incompatibility; or
- native Turso capabilities justify the larger refactor.

This route is likely to require adapting connection, transaction, statement, row, error, async I/O, and pooling behavior. Treat it as a separate estimate after the compatibility spike.

## 7. Proposed provider boundary

Do not force a prematurely generic SQL abstraction over every query. The provider should own database construction and lifecycle while returning the narrowest handle that the selected Turso integration supports.

Illustrative interface:

```rust
#[async_trait]
pub trait TenantDatabaseProvider: Send + Sync {
    type Database;

    async fn open(&self, tenant: &TenantId) -> Result<Self::Database>;
    async fn quiesce(&self, tenant: &TenantId) -> Result<()>;
    async fn close(&self, tenant: &TenantId) -> Result<()>;

    async fn snapshot(&self, tenant: &TenantId) -> Result<SnapshotRef>;
    async fn restore(
        &self,
        tenant: &TenantId,
        snapshot: &SnapshotRef,
    ) -> Result<()>;

    async fn health(&self, tenant: &TenantId) -> Result<DatabaseHealth>;
    async fn destroy(&self, tenant: &TenantId) -> Result<()>;
}
```

This is a design sketch, not a required API. After inspecting both codebases, reduce it to the smallest boundary that works. In particular, snapshot and restore may ultimately be control-plane operations rather than methods on an embedded database provider.

TrailBase code above this boundary must not:

- copy, rename, inspect, or delete database/WAL files;
- infer database existence from a local pathname;
- invoke file-oriented backup logic directly;
- assume a checkpoint makes a specific local file authoritative;
- treat a process-local lock as a tenant lease;
- assume opening a database is synchronous or requires full hydration.

## 8. Work plan

### Phase 0 — Pin inputs and capture a baseline

Create the experiment repository or branch and record:

- TrailBase repository URL and exact commit SHA;
- Turso repository URL and exact commit SHA;
- Rust toolchain version;
- operating system and target architecture;
- compiler and linker configuration;
- enabled database-related Cargo features;
- baseline TrailBase build and test results before modification.

Deliverables:

- `docs/baseline.md`
- machine-readable test output
- initial architecture decision record (`docs/adr/0001-engine-spike-order.md`)

Acceptance criteria:

- An unmodified baseline can be built and tested reproducibly.
- Failures that already exist upstream are separated from prototype regressions.

### Phase 1 — Inventory TrailBase's SQLite usage

Search the repository for database dependencies and behavior, including:

```text
rusqlite
libsqlite3_sys
sqlite3_
PRAGMA
CREATE TRIGGER
CREATE VIEW
virtual table
fts
json
backup
checkpoint
wal
update_hook
preupdate_hook
create_function
create_collation
load_extension
ATTACH
VACUUM
savepoint
```

Classify every finding:

| Category | Examples | Why it matters |
|---|---|---|
| Build/API | C symbols, Cargo features | Determines whether Route A links |
| SQL syntax | DDL, DML, PRAGMAs | Determines parser/execution compatibility |
| Semantics | transactions, constraints, errors | May silently change behavior |
| Extensions | FTS, JSON, custom functions | Can be a hard blocker |
| Lifecycle | backup, WAL, checkpoint | Must move below the provider boundary |
| Concurrency | pools, threads, hooks | Affects correctness and realtime |

Deliverable: `docs/sqlite-dependency-inventory.md` with source locations and a severity rating for each dependency.

Acceptance criteria:

- Every direct connection-creation site is identified.
- Every enabled `rusqlite` feature is explained.
- Known blockers and silent-correctness risks are called out separately.

### Phase 2 — Build the smallest engine compatibility spike

Attempt Route A without first introducing a broad abstraction:

1. Add an isolated build target or Cargo feature such as `turso-engine-spike`.
2. Link the existing SQLite wrapper to Turso's compatible C implementation, if the pinned Turso revision supports the required integration.
3. Resolve only the minimum build-system issues necessary to compile.
4. Run unit and integration tests unchanged.
5. Record every missing symbol and failure.

Do not hide failures with broad test skips. A temporary skip must include a linked compatibility issue and a reason.

Produce a failure matrix:

| Test/workflow | SQLite baseline | Turso result | Failure class | Severity | Candidate fix |
|---|---:|---:|---|---|---|
| migrations | pass | TBD | SQL/API/semantic | blocker/high/etc. | TBD |
| auth signup/login | pass | TBD | | | |
| record CRUD | pass | TBD | | | |
| realtime | pass | TBD | | | |
| FTS | pass | TBD | | | |
| backup/restore | pass | TBD | | | |

Acceptance criteria:

- The spike either produces a running TrailBase process or a complete, reproducible blocker report.
- All test differences are categorized; no unexplained aggregate pass percentage is accepted.

Decision gate:

- **Proceed with Route A/B** if incompatibilities are limited and do not threaten correctness.
- **Estimate Route C** if connection/C API incompatibilities are broad but native Turso supports the needed behavior.
- **Stop** if required database behavior is absent with no credible implementation path.

### Phase 3 — Validate application behavior

Once TrailBase starts on Turso, test representative behavior end to end:

- clean database creation;
- existing SQLite-format database opening, if supported;
- all migrations from an empty database;
- upgrade migrations from at least one older TrailBase fixture;
- admin creation and login;
- user signup, login, refresh, logout, and password reset flows;
- record CRUD, filters, sorting, pagination, relations, and constraints;
- file/blob metadata behavior used by TrailBase;
- realtime subscriptions and transaction visibility;
- JSON and FTS behavior used by TrailBase;
- transaction rollback and constraint error mapping;
- abrupt process termination during writes;
- restart and integrity verification.

For every critical workflow, compare externally visible results with the SQLite baseline rather than checking only that the request succeeds.

Acceptance criteria:

- All Tier 1 workflows match the baseline.
- Any intentional difference is documented and approved.
- Crash/restart tests show no acknowledged transaction loss under the local engine's documented durability settings.

### Phase 4 — Introduce tenant database lifecycle isolation

Only after engine viability is established:

1. Add a tenant identifier type and provider configuration.
2. Centralize database open/create calls.
3. Move database file and lifecycle knowledge into `LocalTursoProvider`.
4. Route one TrailBase runtime to one tenant database.
5. Add structured logs and metrics for open, close, recovery, and ownership.

Suggested prototype repository layout:

```text
.
├── README.md
├── PLAN.md
├── Cargo.toml
├── crates/
│   ├── trailbase-turso/
│   ├── tenant-db-provider/
│   └── scale-to-zero-harness/
├── tests/
│   ├── compatibility/
│   ├── lifecycle/
│   ├── crash_recovery/
│   └── fixtures/
├── docs/
│   ├── baseline.md
│   ├── compatibility-matrix.md
│   ├── sqlite-dependency-inventory.md
│   └── adr/
└── scripts/
    ├── run-baseline.sh
    ├── run-compatibility.sh
    └── run-failure-injection.sh
```

Adapt this layout if working directly inside a TrailBase fork; do not duplicate the upstream workspace unnecessarily.

Acceptance criteria:

- TrailBase application modules no longer construct tenant database paths.
- Switching a test between two provider implementations is configuration/bootstrap work, not application-logic work.

### Phase 5 — Build a scale-to-zero lifecycle harness

The harness should test orchestration properties without imitating Turso Cloud internals.

Implement:

- a tenant router;
- a single-writer lease with owner ID, expiry, and monotonically increasing fencing token;
- runtime start/stop;
- idle shutdown;
- provider open/close;
- a durable local test representation separate from the runtime cache;
- fault injection at lifecycle boundaries.

Minimum lease record:

```text
tenant_id
owner_id
lease_expires_at
fencing_token
```

The fencing token must be validated by any future storage path that can accept writes. Lease expiry alone is not sufficient protection from a paused or partitioned stale writer.

Required scenarios:

1. First request starts a tenant runtime.
2. Concurrent first requests create exactly one writer.
3. Idle runtime stops and later restarts.
4. Runtime moves to another node/process.
5. Runtime crashes before and after a commit acknowledgement.
6. Lease expires while the old owner is paused.
7. Stale owner resumes and is fenced from writes.
8. Entire runtime cache is deleted while stopped.
9. Tenant is reconstructed from the prototype's declared durable representation.
10. Integrity checks and an application-level checksum match the pre-failure state.

Important: if the temporary provider uploads/downloads whole database snapshots, describe it as a **lifecycle test double**, not as the future storage design.

Acceptance criteria:

- Total loss of disposable runtime state does not lose committed tenant data in the test model.
- A stale writer cannot commit after a newer owner is established.
- The same upper-layer lifecycle tests can be reused for a future cloud provider.

### Phase 6 — Define the real cloud-provider contract

This phase requires access to the actual cloud storage interface and its guarantees. Replace assumptions with answers from the implementation owners and code.

Document:

- open/bootstrap inputs;
- tenant/database identity mapping;
- cache directory semantics;
- commit durability boundary;
- WAL ownership and acknowledgement rules;
- generation and manifest rules;
- lazy hydration behavior;
- checkpoint and compaction ownership;
- snapshot/PITR APIs;
- retention and garbage collection;
- encryption and key ownership;
- corruption detection and repair;
- lease/fencing integration;
- behavior during object-store, network, and control-plane failures;
- expected local-versus-remote performance characteristics.

Then implement `CloudTursoProvider` behind the same TrailBase-facing construction/lifecycle boundary. Re-run the complete compatibility and lifecycle suites, adding cloud-specific durability and cache-loss tests.

Acceptance criteria:

- Deleting the entire local cache and starting on a clean node recovers the latest acknowledged state.
- Restore to a selected historical point is demonstrably separate from cache recovery.
- Cloud-provider failures never fall back to an unsafe local-only authoritative state.
- No TrailBase application-service changes are required for the provider swap.

## 9. Testing strategy

### Test tiers

**Tier 0 — Build and smoke**

- compile all relevant targets;
- start server;
- health endpoint;
- create/open database;
- simple read/write transaction.

**Tier 1 — Release blockers**

- migrations;
- auth;
- record CRUD and constraints;
- realtime correctness;
- transaction commit/rollback;
- restart durability;
- single-writer fencing.

**Tier 2 — Compatibility breadth**

- FTS, JSON, complex queries, views/triggers if used;
- administrative operations;
- extension behavior;
- import/export and backup-adjacent workflows.

**Tier 3 — Performance and resilience**

- cold/warm start latency;
- first-query latency;
- steady-state read/write latency;
- memory per tenant runtime;
- cache working-set size;
- high-concurrency requests;
- repeated crash/recovery and fault injection.

### Differential testing

Run identical tests against:

```text
A. Unmodified TrailBase + SQLite
B. TrailBase fork + local Turso
C. TrailBase fork + future cloud-backed Turso
```

Compare:

- response status and body;
- resulting rows and schema;
- constraint and transaction behavior;
- emitted realtime events and ordering;
- restart state;
- documented error classifications.

### Failure injection points

- before a transaction begins;
- during statement execution;
- immediately before commit;
- immediately after commit is acknowledged;
- during provider close;
- during snapshot publication in the test double;
- after lease loss;
- while reopening with an empty cache;
- during remote timeout or partial unavailability once a real cloud provider exists.

## 10. Measurement plan

Correctness gates come first. Once they pass, capture:

| Metric | Baseline | Local Turso | Cloud Turso |
|---|---:|---:|---:|
| Process startup | TBD | TBD | TBD |
| Database open | TBD | TBD | TBD |
| First indexed read | TBD | TBD | TBD |
| First write commit | TBD | TBD | TBD |
| Warm read p50/p95/p99 | TBD | TBD | TBD |
| Warm write p50/p95/p99 | TBD | TBD | TBD |
| RSS after startup | TBD | TBD | TBD |
| RSS under representative load | TBD | TBD | TBD |
| Bytes fetched after empty-cache open | N/A | N/A | TBD |
| Recovery time after cache loss | TBD | TBD | TBD |

Do not adopt a sub-second cold-start target until the cloud backend's actual bootstrap, scheduling, networking, and hydration costs have been measured.

## 11. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Missing SQLite C APIs | Build/runtime blocker | Inventory symbols; upstream small gaps; switch to native API if broad |
| SQL executes with different semantics | Silent corruption or incorrect API results | Differential tests and result checks, not only pass/fail tests |
| Required trigger/FTS/JSON behavior is incomplete | Feature blocker | Test required TrailBase behavior early; do not rely on generic compatibility percentages |
| Database types leak throughout TrailBase | Large refactor | Map ownership and connection creation before designing abstraction |
| Async/native API changes concurrency behavior | Deadlocks or throughput regression | Isolated backend, stress tests, explicit connection ownership |
| Prototype snapshot copy is mistaken for production storage | Bad durability assumptions | Label it a lifecycle test double; document acknowledgement boundary |
| Lease without fencing permits split brain | Data corruption | Monotonic fencing token validated at the write authority |
| Cache and durable state are conflated | Data loss | Separate directories/configuration and destructive cache-loss tests |
| Cloud storage interface differs from assumptions | Rework | Keep the upper boundary narrow; conduct Phase 6 before optimization |
| Upstream changes move compatibility target | Unstable results | Pin commits; update deliberately; retain compatibility matrix by revision |

## 12. Decision gates

### Gate 1 — Is the engine integration viable?

Proceed when TrailBase can start and Tier 1 database workflows either pass or have a short, credible remediation list.

Stop or change route when required features are missing, semantic differences risk correctness, or the compatibility shim requires a long-lived broad fork.

### Gate 2 — Is the provider boundary clean?

Proceed when provider selection is isolated to construction/configuration and TrailBase application services do not manipulate database files.

### Gate 3 — Is scale-to-zero orchestration correct?

Proceed when concurrent activation produces one writer, stale writers are fenced, and complete disposable-state loss is recoverable in the test model.

### Gate 4 — Is the real cloud backend suitable?

Proceed toward production only after its commit, cache-loss, recovery, retention, and PITR guarantees are verified with failure tests.

## 13. Initial backlog

### Milestone 1 — Two-day reconnaissance and baseline

- [ ] Pin TrailBase and Turso commits.
- [ ] Build and test unmodified TrailBase.
- [ ] Map all connection-creation sites.
- [ ] Record database Cargo dependencies and features.
- [ ] Inventory SQLite C APIs and SQL features.
- [ ] Write the first compatibility matrix.

### Milestone 2 — Engine spike

- [ ] Add isolated Turso engine build configuration.
- [ ] Attempt C compatibility linking.
- [ ] Run the unchanged test suite.
- [ ] Categorize every failure.
- [ ] Demonstrate one end-to-end CRUD workflow or publish a blocker report.
- [ ] Decide Route A/B versus Route C.

### Milestone 3 — Application compatibility

- [ ] Pass migrations.
- [ ] Pass auth workflows.
- [ ] Pass record API workflows.
- [ ] Pass realtime workflows.
- [ ] Pass crash/restart tests.
- [ ] Document all remaining differences.

### Milestone 4 — Provider and lifecycle

- [ ] Centralize tenant database creation/opening.
- [ ] Implement `LocalTursoProvider`.
- [ ] Add tenant router and runtime registry.
- [ ] Add lease and fencing-token test implementation.
- [ ] Add idle stop/restart.
- [ ] Add total cache-loss scenario.

### Milestone 5 — Cloud handoff readiness

- [ ] Replace every Phase 6 assumption with the real cloud contract.
- [ ] Implement `CloudTursoProvider`.
- [ ] Reuse the compatibility/lifecycle suites.
- [ ] Test empty-cache recovery and acknowledged-commit durability.
- [ ] Benchmark cold and warm behavior.
- [ ] Produce production-readiness recommendation.

## 14. Definition of prototype success

The prototype succeeds when it produces evidence for all of the following:

1. TrailBase's required database behavior works on the pinned Turso engine, with documented exceptions.
2. The integration approach is maintainable and its upstream/fork obligations are understood.
3. TrailBase application logic is insulated from local-versus-cloud database location.
4. One active writer per tenant is enforced with fencing, not merely best-effort routing.
5. Lifecycle tests prove restart, relocation, crash handling, and complete disposable-cache loss.
6. The future cloud provider can be evaluated through a written contract and the same upper-layer test suite.

Success does **not** mean the local prototype has proven Turso Cloud durability. That conclusion requires testing the real cloud storage implementation.

## 15. Recommended first pull request

Keep the first PR intentionally small:

1. Add this plan and an ADR explaining the spike order.
2. Add scripts that capture the unmodified TrailBase baseline.
3. Add the SQLite dependency inventory.
4. Add an isolated Turso-engine build attempt.
5. Add a compatibility report generated from unchanged tests.

Do not add the router, scheduler, object-store test double, or cold-start optimization in the first PR. The first PR should answer one question cleanly:

> **How much of TrailBase works on the current embedded Turso engine, and exactly what prevents the rest?**

## 16. Reference points

Before implementation, verify all details against the pinned revisions rather than relying on general project documentation:

- TrailBase repository: <https://github.com/trailbaseio/trailbase>
- Turso engine repository: <https://github.com/tursodatabase/turso>
- Turso compatibility document: <https://github.com/tursodatabase/turso/blob/main/COMPAT.md>
- Turso manual: <https://github.com/tursodatabase/turso/blob/main/docs/manual.md>
- `rusqlite`: <https://github.com/rusqlite/rusqlite>

