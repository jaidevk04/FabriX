#!/usr/bin/env bash
set -euo pipefail
trap 'printf "\nFabrix startup failed. Resolve the error above and run this launcher again.\n" >&2' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
ok='import sys; sys.exit(sys.version_info < (3, 12))'
PYTHON=""
for candidate in "$ROOT/.venv/bin/python" python3.13 python3.12 python3 python; do
  if command -v "$candidate" >/dev/null && "$candidate" -c "$ok" 2>/dev/null; then
    PYTHON="$(command -v "$candidate")"
    break
  fi
done
if [[ -z "$PYTHON" ]]; then
  printf 'Python 3.12 or newer was not found on PATH.\n' >&2
  false
fi
"$PYTHON" -c 'import venv, ensurepip' 2>/dev/null || { printf 'The venv module is missing for %s.\n' "$PYTHON" >&2; false; }
exec "$PYTHON" "$ROOT/scripts/bootstrap.py" "$@"
