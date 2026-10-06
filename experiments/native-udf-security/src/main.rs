use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let arg = std::env::args()
        .nth(1)
        .ok_or("expected fresh evidence directory or --versions")?;
    let result = if arg == "--versions" {
        native_udf_security::versions()?
    } else {
        native_udf_security::observations(&PathBuf::from(arg))?
    };
    println!("{}", serde_json::to_string(&result)?);
    Ok(())
}
