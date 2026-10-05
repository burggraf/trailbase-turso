#!/bin/sh
# baseline.py is supplied by Phase 0 in scripts; never copy or replace it here.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/compatibility.py" "$@"
