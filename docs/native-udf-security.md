# Isolated native scalar/security gate

This probe is **not a backend implementation** and does not qualify TrailBase,
cloud, or the public Rust driver. It exercises the pinned SDK/core registration
path against bundled SQLite (`rusqlite = 0.40.2`, functions/bundled).

Run with already-installed Rust 1.95.0:

```sh
scripts/run-native-security.sh
python3 -m unittest discover -s tests/tooling -p test_native_security.py -v
```

`contract.json` is the shared SQL/result contract consumed by the Rust fixture,
Python classifier and tooling evidence tests. Version 2 observations distinguish
SQL errors from harness/environment failures. Duplicate keys, nonstandard JSON
constants, wrong SQL, truncated sequences and failed controls are rejected.
Successful SELECTs require the exact marker result; setup/bootstrap statements
must have zero calls, and both reopened SELECTs must independently invoke it.
Only the exact pinned generated/index rejection at its expected statement is
accepted as missing proof; other native failures are exit 2. This pin-specific
fixture validation is not a production error-code translation strategy.

The standalone `experiments/native-udf-security/Cargo.lock` was resolved offline;
all subsequent Cargo commands use `--locked`. This locks the isolated fixture's
transitive resolution; it does not assert identical dependency/feature resolution
to either upstream workspace build. Cargo fetched its locked `bytemuck_derive`
1.12.1 dependency during the first build (raw `20261006T130256Z-qq6j7x1p/command.stderr`). Upstream sources and locks must
remain clean at TrailBase `12d3343d7d78c8e4dd65af264a3244f472de450d` and Turso
`e6c79b43cabde627ab9eb4eaa20c2d3e6d384d7c`.

## Contract and evidence

`artifacts/native-security/<unique-run>/` is ignored. `inputs/` and `inputs.json`
capture fixture, runner, standalone/upstream locks, and relevant source APIs.
`sources-before.json`/`sources-after.json` retain pin/clean checks. Each command
has its own JSON metadata and unmodified stdout/stderr, including failures;
`classification.json` is derived, never a replacement for the raw evidence.
Build products use ignored `artifacts/native-security/target/`.

Exit **1** means a demonstrated compatibility/security blocker; **2** means
harness/environment failure, malformed/partial evidence, failed ownership/type
controls or a failed SQLite security control. Native SQL rejection is labelled
missing proof, not proof of equivalent security. Expected engine limitations
are observations in the Rust executable, not upstream tests falsely passed.

The SDK registration call accepts name, argc, deterministic, callback/context
and destructors. It cannot express SQLite innocuous/direct-only scalar flags.
There is no invented native flag implementation. Only ordinary deterministic
native marker callbacks are registered. Native `views,generated_columns` are
explicitly enabled using existing SDK experimental features; encryption and
cloud features are not enabled.

Each security case has fresh DB/context counters, records setting
`PRAGMA trusted_schema=OFF` and readback, then proves a top-level marker positive
control. SQLite compares innocuous, ordinary/non-innocuous and direct-only
registrations across top-level, CHECK, default, stored generated column,
expression index, view and trigger contexts. Denied controls require SQL
rejection and zero forbidden callback calls; innocuous controls must execute.
The stored-view case creates an attacker-shaped stored view without registering
the function, closes/drops the DB, reopens/registers the callback with OFF, and
selects twice via fresh preparations. CLI database files are preserved in the
run; tests use disposable temporary files.

The typed echo bridge records NULL, integer, real, text and blob results plus an
explicit callback error; it deep-copies allocated native results, catches Rust
panics before crossing extern C and uses upstream managed result/context
ownership contracts. Context destruction is counted after connection/database
drop and native result destruction after each invocation. Same-name
`jsonschema` arities 2/3 use JSON-schema-shaped SQL arguments but return markers,
not a JSON schema validator. No variadic workaround is supplied.

## Boundaries

This is a bounded representative matrix, not exhaustive malformed-schema,
cancellation, concurrency, allocator fault, or all schema-expression coverage.
The stored view is syntactically valid but attacker-shaped; arbitrary corrupted
schema/recovery is not established. Native SDK exposure is not a public-driver
registration pass. No actual TrailBase extensions, migrations or baseline are
run. Missing security metadata/enforcement requires separate engine work, not
flag removal, SQL scanning or trusted-schema relaxation.

## Initial executed result: blocked, runner exit 1

Initial worker raw run (retained before validator review corrections): `artifacts/native-security/20261006T131453Z-_7yt1mpm/`.
`observations.json` records the command exit **0**; `observations.stdout` contains
32 security rows, two six-invocation bridge rows and two overload rows.
`classification.json` separately records **7 blocker classifications** and
**2 missing-security-proof contexts**. Requested native OFF is **not verified**:
setting succeeds, but readback returns no rows. SQLite readback is `0` in all
24 cases. Unknown-pragma source behavior is captured, not treated as safety proof.

| Case | Bundled SQLite | Native SDK/core |
|---|---|---|
| Top-level | All three flags call marker | Ordinary marker works |
| CHECK | Innocuous calls; ordinary/direct-only rejected, zero calls | Ordinary marker executes once |
| Default | Same SQLite controls | Ordinary marker executes once |
| Stored generated column | Same SQLite controls | SQL rejected: stored generated columns unsupported; zero calls, not security proof |
| Expression index | Same SQLite controls | SQL rejected: invalid index expression; zero calls, not security proof |
| View / trigger | Same SQLite controls | Ordinary marker executes once in each |
| Stored view, close/reopen, two preparations | Innocuous calls twice; ordinary/direct-only rejected, zero calls | Ordinary marker executes twice |
| Same-name jsonschema arities 2/3 | Both continue working | Arity 2 works before registering 3; then `no such function: jsonschema`, zero calls; arity 3 works |
| NULL/integer/real/text/blob/error | Correct five values and callback error | Same observations; six result destructors |
| Context ownership | One drop per single registration; two per overload fixture | Same final counts |

SQLite has **10 allowed cases and 14 denied/zero-forbidden-call cases**, with
24 additional top-level positive controls. Native has 8 top-level positives,
5 demonstrated schema-execution gaps and 2 SQL-unsupported cases. The SDK
security-flag exposure gap is reported independently; it is not a native flag test.

Rust tests: **3 passed, 0 failed, 0 ignored**, captured as `rust-tests.*` in the
final run. Tooling: **41 passed** (16 new, 25 unchanged), captured under
`artifacts/native-security/20261006T131458Z-jk501sd_/command.*`. Wrapper syntax,
Rust formatting, diff checks and empty staging checks also exited 0, under
`20261006T131504Z-ufirj423`, `20261006T131504Z-_otg1c9j`,
`20261006T131505Z-dbg_8f80`, `20261006T131506Z-3784lijm` respectively.

Exact versions/commands are in `rustc.*`, `cargo.*`, `engine-versions.*` and the
other command metadata. Rust/Cargo 1.95.0 were used; bundled SQLite reports
3.53.2, native `sqlite_version()` reports 3.50.4 (not a native release identifier;
the native source pin above is authoritative). All source/lock/input checks
passed before and after. Six existing upstream core warnings remain unmodified.
At the initial handoff no files were staged. No tools, toolchains or JS packages
were installed and no upstream edits were performed; the locked Cargo dependency
fetch noted above is recorded explicitly.

Red evidence remains under the same ignored artifact root: initial missing
runner (`20261006T130012Z-lctlsc0p`), missing Rust fixture API
(`20261006T130256Z-qq6j7x1p`), subsequent compile failure
(`20261006T130617Z-swd6opc4`), and classifier regressions for SQL/truncation/types,
actual overload error wording and strict JSON. The first complete engine run
(`20261006T130953Z-2wk_62i2`) exited 2 because the classifier conservatively
rejected the previously unrecognized overload wording; that failure and all
raw evidence were preserved, then covered by a failing/passing regression.

## Parent verification and published records

The parent initially reproduced the same 7 blockers and 2 missing contexts under `artifacts/native-security/20261006T131955Z-7aic4jpe/` (outer capture `artifacts/native-security-parent-verification/20261006T131955Z-zj7zvktf/`). That run passed 3 Rust tests and the initial full tooling suite passed 41 tests under `artifacts/native-security-parent-tooling/20261006T132026Z-b67y8_l_/`.

An independent reviewer found two P1 validator defects: aggregate counts admitted wrong-phase/incomplete SELECT evidence, and unexpected native failures could be labelled unsupported SQL. Neither invalidated the real captured engine observations. The parent reproduced them with failing regressions (`artifacts/native-security-review-red/20261006T132854Z-4f7b3ze5/`, 26 failed subcases), then added per-step call/result validation, exact pinned rejection/phase checks, and typed SDK-versus-harness error origins. The Rust origin regression failed first under `artifacts/native-security-rust-review-red/20261006T133122Z-_rtrb80_/`. No security assertions were weakened or engine behavior patched. Subsequent full tooling validation passed 47 tests; final fixture/evidence verification is recorded below.

The final post-correction rerun is `artifacts/native-security/20261006T133510Z-glt7whqz/`, with outer capture `artifacts/native-security-final-verification/20261006T133510Z-5tt_9rj7/`: **exit 1**, the same 7 blockers and 2 missing contexts, and **4 Rust fixture tests passed** (3 integration plus 1 origin regression). Before/after source checks and all captured input hashes passed and were recomputed by the parent. Full tooling **47 tests passed** (22 new, 25 unchanged), wrapper syntax, Rust formatting and diff checks passed under `artifacts/native-security-final-checks/20261006T133513Z-y471pph9/`. The prior formatting-only failure is preserved under `artifacts/native-security-final-checks/20261006T133415Z-6v3onxot/`.

[Published classifications](native-security-results.json) and [outer command metadata](native-security-command.json) are exact copies of those final parent-run records, not substitutes for raw observation streams or a general parity pass. SQLite direct-only controls were tested with trusted schema OFF; direct-only enforcement with trusted schema ON is not independently established by this matrix. The native fixture uses only ordinary registrations because the pinned SDK cannot express either security flag. No adapter or engine-security patch is authorized by these results.

The fresh independent reviewer’s targeted follow-up closed both original P1 findings and returned **Merge verdict: OK**, with no new findings. That accepts this fixture/report only; **engine integration remains BLOCKED**. The reviewer inspected source/raw records but did not execute tests or independently recompute hashes.

## Required separately approved patch scope

1. Carry scalar innocuous/direct-only metadata through extension ABI, registry
   and SDK; add public-driver forwarding if that seam is selected. Exposure alone
   is insufficient.
2. Implement real trusted-schema state/readback and engine enforcement across
   schema loading, preparation/repreparation and execution, with denied-zero-call
   regressions including stored schemas. Do not relax SQLite assertions or scan
   SQL outside the engine as a substitute.
3. Key/resolve same-name fixed-arity overloads correctly while preserving managed
   context ownership and prepared-program invalidation.
4. Separately resolve stored-generated/expression-index SQL support, then rerun
   those security contexts. Their current rejection establishes neither safe
   native execution nor equivalent allowed-function behavior.

Stop here: no engine patch, variadic fallback or adapter was added. Arbitrary
malformed/corrupted stored schema, exhaustive expression/security paths,
prepared-handle retention/cancellation/concurrent lifetime stress and real
TrailBase migrations remain unproven. The selected managed bridge demonstrates
only these basic typed/error/drop observations, not general application parity.
