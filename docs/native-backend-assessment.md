# Native Turso backend: scope, estimate, and next gate

Status: assessment completed; broad backend implementation is **not approved by this assessment**. The user approved continuing the recommended native-backend assessment after Route A blockers. This is not a declaration that Route C is viable with full feature parity.

Inputs: experiment `ea8633989ff21bb8b186e3b5901a1696ab6b1707`, TrailBase `12d3343d7d78c8e4dd65af264a3244f472de450d`, Turso `e6c79b43cabde627ab9eb4eaa20c2d3e6d384d7c`. Two independent, read-only subagent assessments covered the adapter and specialized parity seams. The parent verified the critical API/security findings against those sources. Upstream source/locks and dependency declarations remain unchanged; no tools or JS packages were installed. Cargo could fetch existing locked Rust dependencies for the driver tests.

## Recommendation

**Do not begin the full TrailBase rewrite yet.** Preserve SQLite as the default/reference backend. First prove native scalar-function registration, overloads, and schema-execution security. If that gate needs unsupported engine changes, obtain a separate scope/budget decision rather than discarding flags or accepting weaker security.

If that gate is viable, build one optional native executor behind TrailBase's existing concrete database facade. Do not introduce tenant providers, routing, cloud storage, or a universal SQL abstraction at this stage. A main-only experiment retaining SQLite logs/session is useful but must be labelled mixed-engine, not SQLite-free or application parity.

## Executed evidence

The unchanged native driver library suite was run with default crate features, without the optional cloud-sync feature:

```sh
cd upstream/turso
CARGO_TARGET_DIR=<experiment>/artifacts/turso-target RUSTUP_AUTO_INSTALL=0 \
  cargo +1.95.0 test --locked -p turso --lib -- --nocapture
```

**Result: exit 0; 14 passed, 0 failed, 0 ignored, 0 filtered out.** Duration: 131.820 seconds including build; reported test execution: 0.78 seconds. Both source-integrity checks passed. Raw evidence: `artifacts/native-readiness/20261005T235813Z-ead1h_lo/` (`native-lib-tests.{json,stdout,stderr}`, `source-before.json`, `source-after.json`). [The exact command record](native-driver-tests.json) is a byte-for-byte copy of the capture metadata; raw streams remain local.

Tests cover driver parameters, batch rollback error handling, transaction commit/rollback/deferred drop cleanup, persistence, and parallel-write/WAL scenarios. This is the complete selected **library unit target**, not Turso's whole suite or TrailBase's mandatory baseline. No native UDF/security, application migration/auth/CRUD/realtime/vector, snapshot-fault, or cloud guarantee is established. The [SQLite baseline remains blocked](baseline.md); see [its provisioning prerequisites](baseline-prerequisites.md).

## Required adapter seam

TrailBase already has concrete SQLite/Postgres dispatch and owned eager rows, but exposes synchronous callbacks and rusqlite transaction/statement details. Relevant sources: `upstream/trailbase/crates/sqlite/src/traits.rs:6-32`, `rows.rs:41-53,119-200`, `sqlite/connection.rs:109-147`, `generic.rs:185-232,560-691`.

A proposed native worker should own each handle and resolve async engine operations on a dedicated worker, returning existing TrailBase values/rows. It must reserve the writer for an entire transaction/job, keep reader ownership and the existing pool-wide read/write exclusion initially, and finish cleanup even if the request receiver disappears. Do not nest blocking runtimes inside request tasks or expose native clones/statements to application code.

Changes would be concentrated in `crates/sqlite` (optional module/features, executor, values, params, errors, concrete dispatch), then `crates/refinery` (writer-local migration session) and Core factories/error translation/admin capabilities. Existing SQLite modules and tests stay intact. A retained WASM transaction requires a separately designed owned reservation/token; do not port unsafe cross-thread borrowed transaction ownership mechanically.

| Contract | Pinned source finding | Required action/proof |
|---|---|---|
| Prepare/rows/column metadata | Public driver provides async statements, owned values, names/decltypes (`upstream/turso/bindings/rust/src/lib.rs:413-645`, `rows.rs:46-124`). | Differential NULL/i64/f64/text/blob, empty results, conversions and binding/reuse tests. |
| Named/sparse binding, SQL-string batches, expansion | Public driver lacks the complete low-level facade. SDK offers `prepare_first`/bind/count/name; core offers parameter lookup and expanded SQL (`upstream/turso/sdk-kit/src/rsapi.rs:1390-1421,1563-1632`; `core/statement.rs:1420-1472`). | Prefer narrow forwarding APIs; if SDK/core access is selected, confine version-sensitive ownership to one module. No custom SQL splitting/string replacement. |
| Errors/HTTP mapping | Driver/SDK collapse constraint detail into string-bearing categories (`upstream/turso/bindings/rust/src/lib.rs:88-162`; `sdk-kit/src/rsapi.rs:735-770`). | Structured errors or an explicitly approved externally visible change. Never fabricate extended SQLite codes or classify by error text. |
| Transactions | `transaction::Transaction` is implemented despite a separate empty root placeholder (`upstream/turso/bindings/rust/src/transaction.rs:99-250`). Drop defers cleanup; clone copies cleanup state while sharing the engine (`connection.rs:73-88`). | Transaction-long reservation, explicit rollback/autocommit verification and handle quarantine after uncertain cleanup. Test preexisting clones/statements, dropped/failed/cancelled work. |
| Batch/RETURNING | TrailBase tolerates SELECT in normal batches and returns last-statement rows in admin batches. Native execute may reject rows after stepping (`upstream/turso/bindings/rust/src/lib.rs:414-444`; `connection.rs:379-388`). | Compare side effects, not just errors; preserve parsing and admin semantics without pretending APIs are interchangeable. |
| Migration session | FK state, BEGIN/check/commit/restore must be writer-local and reserved for the whole job (`upstream/trailbase/crates/refinery/src/drivers/trailbase.rs:33-101`). | Restore FK settings on failure/cancellation; run all embedded migrations after UDF security is available, not filtered subsets. |
| Close/cancellation | SDK exposes explicit close/interrupt; public wrapper does not expose the complete lifecycle (`upstream/turso/sdk-kit/src/rsapi.rs:1422-1448`). | Bound drain/close and state the cancellation contract. Finish-after-enqueue is distinct from aborting a transaction. |

The native crate's `sync` feature means cloud synchronization, **not** a synchronous embedded driver (`upstream/turso/bindings/rust/src/sync.rs:1-30`). `Send + Sync` declarations do not establish transaction isolation.

## Specialized parity gates

### 1. Scalar UDF/security — earliest blocker

TrailBase registers per-connection UUID/password/JSON-schema/validation functions and sets `trusted_schema=OFF`; WASM functions can carry direct-only/innocuous flags (`upstream/trailbase/crates/extension/src/lib.rs:28-98`; `crates/wasm-runtime-host/src/functions.rs:170-188`). Migrations/CHECKs depend on those functions.

At this pin, the public native connection does not expose equivalent registration. SDK registration accepts callback/lifetime parameters and a deterministic boolean, but not scalar innocuous/direct-only flags (`upstream/turso/sdk-kit/src/rsapi.rs:1200-1231`). The core registry has the same limited scalar metadata and inserts by name, overwriting same-name arities (`upstream/turso/core/ext/mod.rs:108-147`; `core/function.rs:77-93`). A direct port of TrailBase's `jsonschema` arities 2 and 3 would therefore lose an overload.

A scoped search of core, SDK and Rust bindings found virtual-table innocuous handling and introspection flags, **not matching scalar schema-security enforcement**. Unknown PRAGMAs are silently ignored (`upstream/turso/core/translate/pragma.rs:215-247`); success setting `trusted_schema=OFF` is not proof it protects schema execution. These are source findings, not an executed exploit demonstration.

Gate: innocuous functions must work in required CHECK/default/index/view/trigger contexts; unsafe/direct-only functions must be blocked from schema use while working in permitted top-level calls. Include malicious schema/reopen/reprepare, overloads, NULL/type/error conversion, and callback lifetimes. Dropping flags, enabling trusted schema, or scanning tenant SQL outside the engine is not an acceptable equivalent.

### 2. Realtime — CDC is a candidate, not a preupdate hook

Native SQL CDC v2 stores typed changes with transaction IDs and COMMIT markers (`upstream/turso/core/cdc.rs:21-39`; emitter `core/translate/emitter/mod.rs:1538-1662`). Existing test source covers some payload/failed-statement/transaction cases, but those tests were not run here.

A committed-event adapter needs an independent reader, explicit format validation, per-database identity, ordering, schema/version handling, subscribe-baseline race protection, bounded lag and safe retention. Capture must be enabled on every writer. Attached same-name tables, rowid-changing UPDATE (represented as DELETE+INSERT), generated columns, trigger/FK writes and crash/reopen require direct probes. No uncommitted-event publication is acceptable. Any intentional change from actual SQLite baseline behavior must be documented and approved; the source-level rollback-event risk is not yet a reproduced baseline failure.

### 3. Vector behavior — scalar and vec0 scopes differ

TrailBase's coffee example uses `vec_f32`/`vec_distance_L2`; Turso exposes different native names (`upstream/trailbase/examples/coffee-vector-search/traildepot/migrations/main/U1732092075__crate_coffee_table.sql:13-18`; `upstream/turso/core/function.rs:332-378`). No matching vec0 implementation was found. Native approximate indexing is not equivalent to sqlite-vec's virtual-table contract.

Exact f32 scalar aliases may be a bounded path after UDF security is solved, but need differential blob/text/NULL/error/subtype/NaN/Inf/tie-order tests. Full vec0 CRUD/KNN/filter/rollback/persistence/backup parity is separate engine/extension work if required. Restricting supported tenant SQL/vector scope needs approval; do not silently rewrite application SQL.

### 4. Backup/lifecycle — use a real snapshot operation, not a file-copy claim

No equivalent native stepped online backup/live-handle restore API was found. SQL `VACUUM [schema] INTO` is available without the experimental in-place VACUUM flag (`upstream/turso/core/translate/vacuum.rs:24-51`). The implementation uses a source transaction and output checkpointing (`core/vdbe/execute.rs:19485-19667`; `core/vdbe/vacuum.rs:366-404`). That makes it a credible local export seam, **not a tested durability guarantee**.

A candidate replacement stages unpublished exports, validates every required DB, and publishes only after durable aggregate completion; restore occurs under quiescence with stale-WAL prevention and verified reopen. Probe concurrent writers, UDF/schema replay, hidden-rowid preservation, attachments, cancellation/ENOSPC/fsync/checkpoint faults and crash boundaries. Live restore, multi-file atomicity, directory durability and future provider IO need separate contracts. Neither cacheflush nor copying files is snapshot acknowledgement. Cloud guarantees remain out of scope.

## Provisional work ranges

One experienced Rust/database engineer, usable build environment, timely scope/API decisions. **These are planning estimates from source assessment, not measured implementation times or shipping commitments.** Engine changes/upstream acceptance can invalidate them. Shared proof work overlaps; do not mechanically add every range.

| Work | Conditional range | Boundary |
|---|---:|---|
| Baseline environment preparation | 0.5–2 engineer-days | Approval/provisioning first; new upstream failures excluded. |
| Isolated adapter capability fixture | 2–4 engineer-days | Queries, params, transactions/drop/cancel; may end in blocker report. |
| Bounded local adapter plus differential qualification | 19–35 engineer-days **including the fixture** | Excludes specialized parity below, engine fixes, retained WASM and all-DB conversion. |
| Narrow public forwarding APIs | 3–6 additional engineer-days | Alternative to broader direct-core ownership; acceptance not promised. |
| Direct-core ownership instead | 5–10 additional engineer-days | Alternative allowance; version-sensitive, not preferred by default. |
| Retained WASM transaction integration | 4–8 additional engineer-days | Only after ownership/protocol decision. |
| All-DB/attached factory conversion | 3–6 additional engineer-days | Does not include attached realtime/backup proof. |
| UDF bridge/arity/lifetimes | 2–4 engineer-weeks after proof | Engine security is additional, not solved by the bridge. |
| Scalar schema-security engine work | 4–8+ engineer-weeks | High uncertainty; separate engine scope/review required. |
| Single-DB committed realtime adapter | 2–4 engineer-weeks after proof | Attachment/DDL/race/lag fixes may add 2–4+ weeks. |
| Demonstrated f32 vector scalar subset | 1–2 engineer-weeks after proof | Full scalar/type compatibility may be 3–6+ weeks; vec0 separately 6–12+ weeks. |
| Staged local export/offline restore | 2–4 engineer-weeks after proof | Fault/durability/rowid/special-schema remediation may add 3–6+ weeks. |

**No defensible total full-parity delivery estimate yet.** In particular, the 19–35-day adapter estimate must not be presented as a fully working TrailBase/Turso server timeline.

## Assessment verification

A fresh independent reviewer checked the key source claims, raw native test results, prerequisite assessment and estimate boundaries; no findings were raised (**Merge verdict: OK with notes**, documentation only). The unchanged tooling suite also passed **25 tests**, along with wrapper syntax/diff checks; raw validation is `artifacts/native-assessment-validation/20261006T000712Z-3awg89j9/`. Relative documentation links and the byte-identical native command record were checked. These checks do not certify application parity or authorize provisioning/rewrite work.

## Recommended next implementation gate

Authorize only an isolated UDF/security capability spike first: roughly **3–5 engineer-days of investigation**, not a commitment to implement the missing engine security in that period. Keep upstream pins and SQLite control tests; place fixtures outside upstream. Test the public registration surface versus SDK/core options, overloads, exact callback values/errors, and schema-security contexts. Stop on missing enforcement or a need for engine changes and return a concrete blocker/patch-scope proposal.

After that gate, select a public-forwarding versus pinned SDK/core seam and settle error fidelity, vector/vec0 scope, main-only versus all-DB use, retained WASM transactions, and backup/restore needs. Only then start the optional adapter. No broad refactor, feature deletion, provider abstraction, dependency installation, cloud claim, or upstream repinning is implicitly approved by this estimate.
