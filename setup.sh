#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

is_healthy() {
  "$1" -c 'import sys; from pathlib import Path; raise SystemExit(0 if (Path(sys.base_prefix)/"Lib").is_dir() or (Path(sys.base_prefix)/"lib").is_dir() else 1)' >/dev/null 2>&1
}

pick_python() {
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && is_healthy "$candidate"; then
      ver="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
      case "$ver" in
        3.11|3.12|3.13) echo "$candidate"; return 0 ;;
      esac
    fi
  done
  return 1
}

if ! PY="$(pick_python)"; then
  echo "No healthy Python 3.11-3.13 found."
  echo "On Windows with Chocolatey: choco install python311 -y"
  exit 1
fi

echo "Using: $PY"
exec "$PY" scripts/setup_env.py "$@"
