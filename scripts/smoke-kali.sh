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
  cp -a /workspace /tmp/securityllama
  cd /tmp/securityllama
  export PATH="$HOME/.local/bin:$PATH"
  python3 -m tests.fake_ollama --host 127.0.0.1 --port 11435 &
  fake_pid=$!
  trap "kill $fake_pid" EXIT
  ./scripts/bootstrap-kali.sh --no-apt --non-interactive --ollama-url http://127.0.0.1:11435 --model fixture-model
  ./scripts/bootstrap-kali.sh --no-apt --non-interactive --ollama-url http://127.0.0.1:11435 --model fixture-model
  test "$(grep -c ">>> securityllama managed block >>>" "$HOME/.zshrc")" -eq 1
  tmux -L securityllama-smoke -f "$HOME/.tmux.conf" new-session -d -s assessment -c /tmp
  tmux -L securityllama-smoke list-keys -T prefix | grep "_open-chat"
  launcher=$(command -v securityllama)
  origin_pane=$(tmux -L securityllama-smoke display-message -p -t assessment:0.0 "#{pane_id}")
  tmux -L securityllama-smoke run-shell -t assessment:0.0 \
    "$launcher _open-chat --executable $launcher --pane #{q:pane_id} --cwd #{q:pane_current_path}"
  test "$(tmux -L securityllama-smoke show-options -w -v -t assessment:securityllama @securityllama_chat)" = 1
  test "$(tmux -L securityllama-smoke show-options -w -v -t assessment:securityllama @securityllama_origin_pane)" = "$origin_pane"
  test "$(tmux -L securityllama-smoke list-windows -t assessment -F "#{@securityllama_chat}" | grep -c "^1$")" -eq 1
  tmux -L securityllama-smoke run-shell -t assessment:securityllama \
    "$launcher _open-chat --executable $launcher --pane #{q:pane_id} --cwd #{q:pane_current_path}"
  test "$(tmux -L securityllama-smoke display-message -p -t assessment "#{window_name}")" != securityllama
  tmux -L securityllama-smoke kill-server
  securityllama --version
  securityllama doctor
  securityllama ask "smoke test"
  ./scripts/uninstall.sh --non-interactive
  test -d "$HOME/.config/securityllama"
'
