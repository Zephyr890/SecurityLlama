#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

python_bin=${PYTHON:-python3}
"$python_bin" -m ruff format --check .
"$python_bin" -m ruff check .
"$python_bin" -m mypy src
"$python_bin" -m pytest
bash -n scripts/*.sh
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck scripts/*.sh
else
  printf '%s\n' 'shellcheck not installed; bash syntax checks passed'
fi
