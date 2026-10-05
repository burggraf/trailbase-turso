# Integrated first-slice verification

The first slice delivers tooling, source inventories, and a reproducible Route A blocker report—not a working TrailBase-on-Turso server. No upstream sources or locks were changed.

## Final checks

- `python3 -m unittest discover -s tests/tooling -v`: **25 tests passed**.
- `bash -n scripts/run-baseline.sh`, `sh -n scripts/run-compatibility.sh`, and `git diff --check`: passed.
- Raw combined validation: `artifacts/review-fixes-green/20261005T233810Z-cx32u4ny/command.{json,stdout,stderr}`.
- Final integrated `scripts/run-compatibility.sh --library .../artifacts/turso-target/debug/libturso_sqlite3.dylib --timeout 120`: **blocked, exit 1**, as expected from observed engine incompatibilities. Raw result: `artifacts/compatibility/20261005T233844Z-77a7kzog/result.json`; outer capture: `artifacts/final-c-api/20261005T233844Z-45dg5mah/`.
- Both engines pass the bounded subset with identical observations; system SQLite links the required APIs and passes backup. Turso fails the required-API link (exit 1) and aborts in backup (returncode -6 / normalized exit 134). Pin/source checks remain clean.
- The unmodified upstream baseline has **no executed-suite proof**: its four build/test commands exited 101 before tests ran. See [baseline evidence](baseline.md); no broad suite was replaced by these controls.

## Review and corrections

One fresh independent reviewer inspected the integrated slice and raw evidence. The parent reproduced and fixed two findings: POSIX timeout descendant cleanup, and persisted command records for permission/format launch errors. Three regressions failed before the fixes; raw red evidence is `artifacts/review-fixes-red/20261005T233719Z-ma80zd30/`. A targeted follow-up found both resolved and returned **Merge verdict: OK**. The final C rerun above completed after the helper changes.

The parent also fixed combined test discovery's helper import, exposed by running without the isolated worktree's `PYTHONPATH` override. All raw historical runs remain unchanged; checked-in reports retain their original run provenance.

## Missing proof and next gate

No full baseline build/tests, substituted rusqlite build, server/API parity, cloud guarantees, Linux execution, or default isolated-build execution is certified. Interruption cleanup is source-reviewed; its dedicated regression and non-POSIX descendant cleanup are not established. The C API blockers require an explicit upstream-repair versus native-backend decision before further application implementation. Raw artifacts and the isolated spike worktree remain local; only source/docs/structured reports are published.
