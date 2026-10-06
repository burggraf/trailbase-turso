//! Pinned SDK/core capability observations, deliberately not a backend adapter.
use rusqlite::{Connection as Sqlite, functions::FunctionFlags, types::Value as SqlValue};
use serde_json::{Value as Json, json};
use std::{
    error::Error,
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex,
        atomic::{AtomicUsize, Ordering},
    },
};
use turso_ext::{ContextDestructor, Value as ExtValue, ValueDestructor, ValueType};
use turso_sdk_kit::{
    IoBackend,
    rsapi::{
        Numeric, TursoConnection, TursoDatabase, TursoDatabaseConfig, TursoError, TursoStatusCode,
        Value as NativeValue,
    },
};

type Result<T> = std::result::Result<T, Box<dyn Error>>;
// Keep the SDK variant, not just its text, for SQL-vs-harness classification.
#[derive(Debug)]
struct SdkError(TursoError);
impl std::fmt::Display for SdkError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:?}: {}", self.0, self.0)
    }
}
impl Error for SdkError {}
fn sdk_error(error: TursoError) -> Box<dyn Error> {
    Box::new(SdkError(error))
}
static SERIAL: Mutex<()> = Mutex::new(());
static VALUE_DROPS: AtomicUsize = AtomicUsize::new(0);
static TEMP_ID: AtomicUsize = AtomicUsize::new(0);
const CONTEXTS: [&str; 8] = [
    "top",
    "check",
    "default",
    "generated",
    "index",
    "view",
    "trigger",
    "stored-view",
];

#[derive(Default)]
struct Counters {
    calls: AtomicUsize,
    drops: AtomicUsize,
}
#[derive(Clone, Copy)]
enum Mode {
    Marker,
    Echo,
    Arity,
}
struct Context {
    counters: Arc<Counters>,
    mode: Mode,
}
impl Drop for Context {
    fn drop(&mut self) {
        self.counters.drops.fetch_add(1, Ordering::SeqCst);
    }
}

// SAFETY: SDK receives a unique Box pointer on successful registration and calls
// this destructor once after the last registry/prepared-program owner releases it.
// Context contains no panic-capable custom destructors; no raw pointer is retained.
unsafe extern "C" fn context_drop(pointer: usize) {
    unsafe {
        drop(Box::from_raw(pointer as *mut Context));
    }
}

// SAFETY: the engine has copied the returned value before invoking this callback.
// We consume exactly one well-formed owned result, replacing its slot with NULL.
// Mirrors upstream managed-scalar tests, with a counter and no dangling slot.
unsafe extern "C" fn value_drop(pointer: *mut ExtValue) {
    if !pointer.is_null() {
        let owned = unsafe { std::mem::replace(&mut *pointer, ExtValue::null()) };
        unsafe {
            owned.__free_internal_type();
        }
        VALUE_DROPS.fetch_add(1, Ordering::SeqCst);
    }
}

unsafe extern "C" fn callback(
    pointer: usize,
    argc: i32,
    argv: *const ExtValue,
    _context_destructor: Option<ContextDestructor>,
    _value_destructor: Option<ValueDestructor>,
) -> ExtValue {
    // Borrow only during this call; never free argv (engine-owned). Every allocated
    // return is a deep copy, owned by the managed value destructor, including errors.
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        if pointer == 0 || argc < 0 || (argc > 0 && argv.is_null()) {
            return ExtValue::error_with_message("invalid probe callback arguments".into());
        }
        let ctx = unsafe { &*(pointer as *const Context) };
        ctx.counters.calls.fetch_add(1, Ordering::SeqCst);
        let args = if argc == 0 {
            &[]
        } else {
            unsafe { std::slice::from_raw_parts(argv, argc as usize) }
        };
        match ctx.mode {
            Mode::Marker => ExtValue::from_integer(1),
            Mode::Arity => ExtValue::from_integer(i64::from(argc)),
            Mode::Echo => {
                let Some(v) = args.first() else {
                    return ExtValue::error_with_message("missing argument".into());
                };
                match v.value_type() {
                    ValueType::Null => ExtValue::null(),
                    ValueType::Integer => {
                        ExtValue::from_integer(v.to_integer().unwrap_or_default())
                    }
                    ValueType::Float => ExtValue::from_float(v.to_float().unwrap_or_default()),
                    ValueType::Text if v.to_text() == Some("__error__") => {
                        ExtValue::error_with_message("probe callback error".into())
                    }
                    ValueType::Text => {
                        ExtValue::from_text(v.to_text().unwrap_or_default().to_owned())
                    }
                    ValueType::Blob => ExtValue::from_blob(v.to_blob().unwrap_or_default()),
                    ValueType::Error => {
                        ExtValue::error_with_message("unexpected error argument".into())
                    }
                }
            }
        }
    }))
    .unwrap_or_else(|_| ExtValue::error_with_message("probe callback panic caught".into()))
}

enum Db {
    Sqlite(Sqlite),
    Native {
        conn: Arc<TursoConnection>,
        db: Arc<TursoDatabase>,
    },
}
impl Db {
    fn open(engine: &str, path: Option<&Path>) -> Result<Self> {
        let filename = path
            .map(|p| p.to_string_lossy().into_owned())
            .unwrap_or_else(|| ":memory:".into());
        match engine {
            "sqlite" => Ok(Self::Sqlite(Sqlite::open(filename)?)),
            "native" => {
                let db = TursoDatabase::new(TursoDatabaseConfig {
                    path: filename,
                    experimental_features: Some("views,generated_columns".into()),
                    async_io: false,
                    encryption: None,
                    vfs: IoBackend::Default,
                    io: None,
                    db_file: None,
                    page_codec: None,
                    open_flags: Default::default(),
                });
                if db.open().map_err(sdk_error)?.is_io() {
                    return Err("synchronous SDK open unexpectedly requires IO".into());
                }
                let conn = db.connect().map_err(sdk_error)?;
                Ok(Self::Native { conn, db })
            }
            _ => Err("unknown engine".into()),
        }
    }
    fn register(
        &self,
        name: &str,
        argc: i32,
        flag: &str,
        mode: Mode,
        counters: &Arc<Counters>,
    ) -> Result<()> {
        let ctx = Context {
            counters: counters.clone(),
            mode,
        };
        match self {
            Self::Sqlite(conn) => {
                let flags = FunctionFlags::SQLITE_UTF8
                    | FunctionFlags::SQLITE_DETERMINISTIC
                    | match flag {
                        "innocuous" => FunctionFlags::SQLITE_INNOCUOUS,
                        "direct-only" => FunctionFlags::SQLITE_DIRECTONLY,
                        "ordinary" => FunctionFlags::empty(),
                        _ => return Err("unknown SQLite flag".into()),
                    };
                conn.create_scalar_function(name, argc, flags, move |args| {
                    ctx.counters.calls.fetch_add(1, Ordering::SeqCst);
                    match ctx.mode {
                        Mode::Marker => Ok(SqlValue::Integer(1)),
                        Mode::Arity => Ok(SqlValue::Integer(args.len() as i64)),
                        Mode::Echo => {
                            let value: SqlValue = args.get(0)?;
                            if value == SqlValue::Text("__error__".into()) {
                                Err(rusqlite::Error::UserFunctionError(
                                    "probe callback error".into(),
                                ))
                            } else {
                                Ok(value)
                            }
                        }
                    }
                })?;
            }
            Self::Native { conn, .. } => {
                if flag != "ordinary" {
                    return Err("SDK cannot express scalar security flags".into());
                }
                let pointer = Box::into_raw(Box::new(ctx)) as usize;
                // Fixed valid names/arity in this fixture. On SDK failure no registry
                // ownership was accepted (validated before insert); reclaim the Box.
                if let Err(error) = conn.register_external_scalar_function(
                    name.into(),
                    argc,
                    true,
                    pointer,
                    callback,
                    Some(context_drop),
                    Some(value_drop),
                ) {
                    unsafe {
                        drop(Box::from_raw(pointer as *mut Context));
                    }
                    return Err(sdk_error(error));
                }
            }
        }
        Ok(())
    }
    fn query(&self, sql: &str) -> Result<Vec<Vec<Json>>> {
        let mut result = Vec::new();
        match self {
            Self::Sqlite(conn) => {
                let mut statement = conn.prepare(sql)?;
                let columns = statement.column_count();
                let mut rows = statement.query([])?;
                while let Some(row) = rows.next()? {
                    let mut values = Vec::new();
                    for i in 0..columns {
                        values.push(sql_json(row.get::<_, SqlValue>(i)?));
                    }
                    result.push(values);
                }
            }
            Self::Native { conn, .. } => {
                let Some((mut statement, tail)) = conn.prepare_first(sql).map_err(sdk_error)?
                else {
                    return Err("no prepared SQL".into());
                };
                if !sql[tail..].trim().is_empty() {
                    return Err("fixture requires single statement".into());
                }
                loop {
                    match statement.step(None).map_err(sdk_error)? {
                        TursoStatusCode::Done => break,
                        TursoStatusCode::Row => {
                            let mut values = Vec::new();
                            for i in 0..statement.column_count() {
                                values
                                    .push(native_json(statement.row_value(i).map_err(sdk_error)?));
                            }
                            result.push(values);
                        }
                        TursoStatusCode::Io => {
                            return Err("synchronous SDK statement unexpectedly requires IO".into());
                        }
                    }
                }
            }
        }
        Ok(result)
    }
    fn finish(self) -> Result<()> {
        match self {
            Self::Sqlite(conn) => {
                drop(conn);
            }
            Self::Native { conn, db } => {
                conn.close().map_err(sdk_error)?;
                drop(conn);
                drop(db);
            }
        }
        Ok(())
    }
}
fn sql_json(value: SqlValue) -> Json {
    match value {
        SqlValue::Null => Json::Null,
        SqlValue::Integer(v) => json!(v),
        SqlValue::Real(v) => json!(v),
        SqlValue::Text(v) => json!(v),
        SqlValue::Blob(v) => json!({"blob":v}),
    }
}
fn native_json(value: NativeValue) -> Json {
    match value {
        NativeValue::Null => Json::Null,
        NativeValue::Numeric(Numeric::Integer(v)) => json!(v),
        NativeValue::Numeric(Numeric::Float(v)) => json!(f64::from(v)),
        NativeValue::Text(v) => json!(v.as_str()),
        NativeValue::Blob(v) => json!({"blob":v.as_slice()}),
    }
}
fn observe(db: &Db, counters: &Counters, sql: &str) -> Json {
    let before = counters.calls.load(Ordering::SeqCst);
    let result = db.query(sql);
    let calls = counters.calls.load(Ordering::SeqCst) - before;
    match result {
        Ok(rows) => {
            json!({"sql":sql, "ok":true, "calls":calls, "rows":rows, "error":null, "error_kind":null})
        }
        Err(error) => {
            let kind = if let Some(sdk) = error.downcast_ref::<SdkError>() {
                match &sdk.0 {
                    TursoError::Error(_) | TursoError::Constraint(_) => "engine-sql",
                    _ => "harness",
                }
            } else if error.is::<rusqlite::Error>() {
                "engine-sql"
            } else {
                "harness"
            };
            json!({"sql":sql, "ok":false, "calls":calls, "rows":[], "error":error.to_string(), "error_kind":kind})
        }
    }
}
fn contract() -> Result<Json> {
    Ok(serde_json::from_str(include_str!("../contract.json"))?)
}
fn statements(context: &str) -> Result<Vec<String>> {
    contract()?["security"][context]
        .as_array()
        .ok_or("unknown security context")?
        .iter()
        .map(|sql| {
            sql.as_str()
                .map(str::to_owned)
                .ok_or_else(|| "invalid contract SQL".into())
        })
        .collect()
}

struct Disposable {
    path: PathBuf,
    remove: bool,
}
impl Drop for Disposable {
    fn drop(&mut self) {
        if self.remove {
            for suffix in ["", "-wal", "-shm"] {
                let _ = std::fs::remove_file(format!("{}{suffix}", self.path.display()));
            }
        }
    }
}

/// Records actual execution, including native SQL limitations. A stored view is
/// created on an unregistered connection and executed only after close/reopen.
pub fn security(
    engine: &str,
    flag: &str,
    context: &str,
    stored_path: Option<&Path>,
) -> Result<Json> {
    let _serial = SERIAL.lock().map_err(|_| "fixture mutex poisoned")?;
    let counters = Arc::new(Counters::default());
    let all_sql = statements(context)?;
    let contract = contract()?;
    let mut steps = Vec::new();
    let disposable = if context == "stored-view" {
        let path = stored_path.map(Path::to_owned).unwrap_or_else(|| {
            std::env::temp_dir().join(format!(
                "native-security-{}-{}.db",
                std::process::id(),
                TEMP_ID.fetch_add(1, Ordering::SeqCst)
            ))
        });
        if path.exists() {
            return Err("refusing to reuse stored-schema evidence database".into());
        }
        Some(Disposable {
            path,
            remove: stored_path.is_none(),
        })
    } else {
        None
    };
    let path = disposable.as_ref().map(|p| p.path.as_path());
    if context == "stored-view" {
        let bootstrap = Db::open(engine, path)?;
        steps.push(observe(&bootstrap, &counters, &all_sql[0]));
        bootstrap.finish()?;
    }
    let db = Db::open(engine, path)?;
    db.register("marker", 1, flag, Mode::Marker, &counters)?;
    let setting = observe(
        &db,
        &counters,
        contract["setting_sql"]
            .as_str()
            .ok_or("missing setting SQL")?,
    );
    let readback = observe(
        &db,
        &counters,
        contract["readback_sql"]
            .as_str()
            .ok_or("missing readback SQL")?,
    );
    let positive = observe(
        &db,
        &counters,
        contract["positive_sql"]
            .as_str()
            .ok_or("missing positive SQL")?,
    );
    if steps.iter().all(|s| s["ok"] == true) {
        for sql in all_sql.iter().skip(usize::from(context == "stored-view")) {
            let step = observe(&db, &counters, sql);
            let ok = step["ok"] == true;
            steps.push(step);
            if !ok {
                break;
            } // Do not obscure first rejection with missing-table fallout.
        }
    }
    db.finish()?;
    Ok(
        json!({"engine":engine, "flag":flag, "context":context, "setting":setting, "readback":readback, "positive":positive, "steps":steps, "context_drops":counters.drops.load(Ordering::SeqCst)}),
    )
}

pub fn bridge(engine: &str) -> Result<Json> {
    let _serial = SERIAL.lock().map_err(|_| "fixture mutex poisoned")?;
    let counters = Arc::new(Counters::default());
    let value_before = VALUE_DROPS.load(Ordering::SeqCst);
    let db = Db::open(engine, None)?;
    db.register("echo_probe", 1, "ordinary", Mode::Echo, &counters)?;
    let contract = contract()?;
    let steps: Vec<_> = contract["bridge"]
        .as_array()
        .ok_or("missing bridge SQL")?
        .iter()
        .map(|s| {
            s["sql"]
                .as_str()
                .ok_or_else(|| "invalid bridge SQL".into())
                .map(|sql| observe(&db, &counters, sql))
        })
        .collect::<Result<_>>()?;
    db.finish()?;
    Ok(
        json!({"engine":engine, "steps":steps, "context_drops":counters.drops.load(Ordering::SeqCst), "value_drops":if engine == "native" { Some(VALUE_DROPS.load(Ordering::SeqCst)-value_before) } else { None }}),
    )
}

pub fn overload(engine: &str) -> Result<Json> {
    let _serial = SERIAL.lock().map_err(|_| "fixture mutex poisoned")?;
    let counters = Arc::new(Counters::default());
    let db = Db::open(engine, None)?;
    db.register("jsonschema", 2, "ordinary", Mode::Arity, &counters)?;
    let contract = contract()?;
    let before = observe(
        &db,
        &counters,
        contract["overload"]["before"]
            .as_str()
            .ok_or("missing overload SQL")?,
    );
    db.register("jsonschema", 3, "ordinary", Mode::Arity, &counters)?;
    let after2 = observe(
        &db,
        &counters,
        contract["overload"]["after2"]
            .as_str()
            .ok_or("missing overload SQL")?,
    );
    let after3 = observe(
        &db,
        &counters,
        contract["overload"]["after3"]
            .as_str()
            .ok_or("missing overload SQL")?,
    );
    db.finish()?;
    Ok(
        json!({"engine":engine, "before":before, "after2":after2, "after3":after3, "context_drops":counters.drops.load(Ordering::SeqCst)}),
    )
}

pub fn observations(directory: &Path) -> Result<Json> {
    std::fs::create_dir_all(directory)?;
    let mut security_rows = Vec::new();
    for (engine, flags) in [
        ("sqlite", vec!["innocuous", "ordinary", "direct-only"]),
        ("native", vec!["ordinary"]),
    ] {
        for flag in flags {
            for context in CONTEXTS {
                let path = directory.join(format!("{engine}-{flag}-stored-view.db"));
                security_rows.push(security(engine, flag, context, Some(&path))?);
            }
        }
    }
    Ok(
        json!({"schema_version":2, "native_api":"sdk-register-scalar-no-security-flags", "security":security_rows, "bridge":[bridge("sqlite")?,bridge("native")?], "overload":[overload("sqlite")?,overload("native")?]}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn harness_query_errors_are_distinct_from_sql_rejections() {
        let db = Db::open("native", None).expect("fresh SDK database");
        let counters = Counters::default();
        let outcome = observe(&db, &counters, "");
        assert_eq!(outcome["ok"], false);
        assert_eq!(outcome["calls"], 0);
        assert_eq!(outcome["error_kind"], "harness");
        db.finish().expect("close fixture");
    }
}

pub fn versions() -> Result<Json> {
    let db = Db::open("native", None)?;
    let native_sql_version = db.query("SELECT sqlite_version()")?;
    db.finish()?;
    Ok(
        json!({"sqlite_bundled":rusqlite::version(), "native_sql_version":native_sql_version, "native_config":{"async_io":false,"experimental_features":"views,generated_columns","sdk_default_features":false}}),
    )
}
