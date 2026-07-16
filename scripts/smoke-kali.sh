#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  printf '%s\n' 'SKIP: Docker is required for the Kali smoke test.'
  exit 0
fi
if ! docker info >/dev/null 2>&1; then
  printf '%s\n' 'SKIP: Docker is installed but its daemon is unavailable.'
  exit 0
fi

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
docker run --rm -v "$repo_root:/workspace:ro" kalilinux/kali-rolling bash -lc '
  set -euo pipefail
  apt-get update >/dev/null
  DEBIAN_FRONTEND=noninteractive apt-get install --yes python3 python3-venv pipx tmux zsh >/dev/null
  cp -a /workspace /tmp/kali-copilot
  cd /tmp/kali-copilot
  export PATH="$HOME/.local/bin:$PATH"
  python3 -m tests.fake_ollama --host 127.0.0.1 --port 11435 &
  fake_pid=$!
  trap "kill $fake_pid" EXIT
  ./scripts/bootstrap-kali.sh --no-apt --non-interactive --ollama-url http://127.0.0.1:11435 --model fixture-model
  ./scripts/bootstrap-kali.sh --no-apt --non-interactive --ollama-url http://127.0.0.1:11435 --model fixture-model
  test "$(grep -c ">>> kali-copilot managed block >>>" "$HOME/.zshrc")" -eq 1
  kali-copilot --version
  kali-copilot doctor
  kali-copilot ask "smoke test"
  ./scripts/uninstall.sh --non-interactive
  test -d "$HOME/.config/kali-copilot"
'
