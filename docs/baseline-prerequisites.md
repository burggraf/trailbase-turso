# Preparing the unchanged SQLite baseline

Status: prerequisite assessment only. No tooling, JS dependencies, or global configuration was installed/changed during the native-backend assessment.

TrailBase remains pinned to `12d3343d7d78c8e4dd65af264a3244f472de450d`. The previous full Rust baseline commands remain blocked; see [baseline evidence](baseline.md). Native driver tests do not replace that baseline.

## Required preparation

1. **Use a compatible test toolchain, preferably upstream CI's exact version.** `.github/workflows/test.yml` specifies Rust `1.98.1`. Only Rust `1.95.0` and older named toolchains are currently installed. The package's declared minimum is not proof its tests compile on that version: the unchanged client integration test imports `std::assert_matches`, and the captured default suite reports E0658 on 1.95.0. Provisioning another toolchain needs explicit approval; use an explicit `+version`, not a changed global default. Successful compilation on 1.98.1 remains untested.
2. **Prepare the pinned JS workspace using its lockfile.** `.github/actions/setup_pnpm/action.yml` uses Node 22, pnpm `^12.0.0`, and `pnpm install`. Local versions are Node 26.7.0 and pnpm 11.22.0. `crates/assets/build.rs` always builds the admin bundle. `crates/build/src/lib.rs::build_js` uses a frozen/offline install when `PNPM_OFFLINE=TRUE`; our baseline runner sets that deliberately to prevent lockfile changes. The previous cache lacked `barrelize` metadata. With approved package/tool provisioning, populate the cache/workspace using a frozen-lockfile install and check that tracked files remain unchanged before rerunning. Do not relax the runner's lock checks or fabricate an asset bundle.
3. **Match native and integration prerequisites.** Upstream Ubuntu setup installs SSL development libraries, pkg-config, libclang, protobuf, and GEOS, plus a fake sendmail executable. The local machine already exposes clang, protoc, pkg-config, and geos-config, but macOS is not Ubuntu CI parity. Additional client/service requirements depend on the suite; do not assume all are ready because a library target builds. The full unfiltered Rust suite must still be attempted, and any service/environment failures classified separately.
4. **Rerun the existing captured baseline.** After approval/provisioning, initialize pinned nested submodules, confirm clean sources/locks, run `scripts/run-baseline.sh --toolchain <verified-installed-version>`, retain raw output, and publish a new result alongside—not over—the old failed run. Establish server/API baseline fixtures before differential application acceptance.

## Scope and estimate

A provisional environment-preparation allowance is **0.5–2 engineer-days**, assuming the exact CI toolchain/packages can be provisioned and no new upstream failures arise. This is a planning allowance, not measured execution time. A containerized CI-matching environment is an alternative if available and explicitly approved; no container/image setup was performed here.

There is no authorization in this assessment to install dependencies, patch the client tests, change upstream pins/locks, skip mandatory suites, or infer a successful application baseline from narrower tests.
