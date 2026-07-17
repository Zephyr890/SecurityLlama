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
  DEBIAN_FRONTEND=noninteractive apt-get install --yes python3 python3-venv pipx xclip zsh >/dev/null
  cp -a /workspace /tmp/securityllama
  cd /tmp/securityllama
  export PATH="$HOME/.local/bin:$PATH"
  python3 -m tests.fake_ollama --host 127.0.0.1 --port 11435 &
  fake_pid=$!
  trap "kill $fake_pid" EXIT
  ./scripts/bootstrap-kali.sh --no-apt --non-interactive --ollama-url http://127.0.0.1:11435 --model fixture-model
  ./scripts/bootstrap-kali.sh --no-apt --non-interactive --ollama-url http://127.0.0.1:11435 --model fixture-model
  launcher=$(command -v securityllama)
  desktop_file="$HOME/.local/share/applications/securityllama-console.desktop"
  grep -F "Exec=\"$launcher\" console" "$desktop_file"
  grep -F "Terminal=true" "$desktop_file"
  ! grep -q ">>> securityllama managed block >>>" "$HOME/.zshrc"
  printf "/q\n" | script -qec "securityllama console" /dev/null | grep "SecurityLlama console"
  securityllama --version
  securityllama doctor
  securityllama ask "smoke test"
  ./scripts/uninstall.sh --non-interactive
  test ! -e "$desktop_file"
  test -d "$HOME/.config/securityllama"
'
