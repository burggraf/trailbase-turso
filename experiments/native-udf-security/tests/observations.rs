use native_udf_security::{bridge, overload, security};

#[test]
fn typed_callback_results_errors_and_destructors() {
    for engine in ["sqlite", "native"] {
        let r = bridge(engine).expect("fresh callback fixture");
        assert_eq!(r["context_drops"], 1);
        for (s, expected) in r["steps"].as_array().unwrap().iter().zip([
            serde_json::json!(null),
            serde_json::json!(-7),
            serde_json::json!(1.25),
            serde_json::json!("hi"),
            serde_json::json!({"blob":[0,255]}),
        ]) {
            assert_eq!(s["ok"], true);
            assert_eq!(s["calls"], 1);
            assert_eq!(s["rows"], serde_json::json!([[expected]]));
        }
        assert_eq!(r["steps"][5]["ok"], false);
        assert!(
            r["steps"][5]["error"]
                .as_str()
                .unwrap()
                .contains("probe callback error")
        );
        if engine == "native" {
            assert_eq!(r["value_drops"], 6);
        }
    }
}

#[test]
fn sqlite_security_controls_reject_without_forbidden_calls() {
    for context in [
        "top",
        "check",
        "default",
        "generated",
        "index",
        "view",
        "trigger",
        "stored-view",
    ] {
        for flag in ["innocuous", "ordinary", "direct-only"] {
            let r = security("sqlite", flag, context, None).expect("SQLite control fixture");
            assert_eq!(r["readback"]["rows"], serde_json::json!([[0]]));
            assert_eq!(r["positive"]["calls"], 1);
            assert_eq!(r["context_drops"], 1);
            let steps = r["steps"].as_array().unwrap();
            let calls: u64 = steps.iter().map(|s| s["calls"].as_u64().unwrap()).sum();
            if flag == "innocuous" || context == "top" {
                assert!(steps.iter().all(|s| s["ok"] == true));
                assert!(calls > 0);
            } else {
                assert_eq!(calls, 0);
                assert!(steps.iter().any(|s| s["ok"] == false));
                assert!(steps.iter().filter(|s| s["ok"] == false).all(|s| {
                    s["error"]
                        .as_str()
                        .unwrap()
                        .contains("unsafe use of marker")
                }));
            }
        }
    }
}

#[test]
fn native_observations_are_not_assumed_parity() {
    // Security classifications belong to the runner, not a weakened native pass assertion.
    let r = security("native", "ordinary", "top", None).expect("native registration");
    assert_eq!(r["positive"]["rows"], serde_json::json!([[1]]));
    assert_eq!(r["positive"]["calls"], 1);
    assert_eq!(r["context_drops"], 1);
    for engine in ["sqlite", "native"] {
        let r = overload(engine).expect("two registrations");
        assert_eq!(r["before"]["rows"], serde_json::json!([[2]]));
        assert_eq!(r["after3"]["rows"], serde_json::json!([[3]]));
        assert_eq!(r["context_drops"], 2);
        if engine == "sqlite" {
            assert_eq!(r["after2"]["rows"], serde_json::json!([[2]]));
        }
        // Native after2 outcome is emitted, whether error or success.
    }
}
