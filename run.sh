#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

VENV_PY="$ROOT/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "Virtualenv missing. Running setup.sh ..."
  ./setup.sh
fi

if ! "$VENV_PY" -c "import numpy, cv2, PySide6" >/dev/null 2>&1; then
  echo "Environment looks broken. Repairing with setup.sh --force ..."
  ./setup.sh --force
fi

exec "$VENV_PY" "$ROOT/app.py" "$@"
