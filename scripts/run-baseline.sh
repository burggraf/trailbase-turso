#!/usr/bin/env bash
# Run from any directory; captures live in ignored artifacts/baseline/.
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$script_dir/baseline.py" baseline "$@"
