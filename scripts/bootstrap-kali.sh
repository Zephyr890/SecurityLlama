#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ollama_url=""
model=""
scope=""
no_apt=false
dev=false
non_interactive=false
wizard=false

while (($#)); do
  case "$1" in
    --ollama-url) ollama_url=${2:?missing URL}; shift 2 ;;
    --model) model=${2:?missing model}; shift 2 ;;
    --scope) scope=${2:?missing scope}; shift 2 ;;
    --no-apt) no_apt=true; shift ;;
    --dev) dev=true; shift ;;
    --non-interactive) non_interactive=true; shift ;;
    --wizard) wizard=true; shift ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
done

if [[ ! -r /etc/os-release ]]; then
  printf '%s\n' 'Warning: cannot identify this operating system; skipping OS package assumptions.' >&2
  no_apt=true
else
  # shellcheck disable=SC1091
  . /etc/os-release
  if [[ ${ID:-} != kali && ${ID_LIKE:-} != *debian* && ${ID:-} != debian && ${ID:-} != ubuntu ]]; then
    printf 'Warning: %s is not identified as Kali/Debian-family.\n' "${PRETTY_NAME:-this OS}" >&2
    no_apt=true
  fi
fi

if [[ $no_apt == false ]]; then
  apt=(apt-get)
  if ((EUID != 0)); then apt=(sudo apt-get); fi
  if [[ $non_interactive == true ]]; then export DEBIAN_FRONTEND=noninteractive; fi
  "${apt[@]}" update
  "${apt[@]}" install --yes python3 python3-venv pipx tmux zsh
fi

if ! command -v pipx >/dev/null 2>&1; then
  printf '%s\n' 'pipx is required; install it or rerun without --no-apt.' >&2
  exit 2
fi

# Remove the pre-rename package if this is an upgrade from kali-copilot.
pipx uninstall kali-copilot >/dev/null 2>&1 || true

install_args=(install --force)
if [[ $dev == true ]]; then install_args+=(--editable); fi
pipx "${install_args[@]}" "$repo_root"
export PATH="$HOME/.local/bin:$PATH"

if [[ $wizard == true ]]; then
  if [[ -n $ollama_url || -n $model || -n $scope ]]; then
    printf '%s\n' '--wizard cannot be combined with --ollama-url, --model, or --scope.' >&2
    exit 2
  fi
  securityllama setup
  exit $?
fi

config_args=(config init)
[[ -n $ollama_url ]] && config_args+=(--ollama-url "$ollama_url")
[[ -n $model ]] && config_args+=(--model "$model")
securityllama "${config_args[@]}"
if [[ -n $scope ]]; then
  if ! securityllama scope show "$scope" >/dev/null 2>&1; then
    securityllama scope init "$scope"
    printf 'Scope %s was created unauthorized; edit it before enabling network insertion.\n' "$scope"
  fi
  securityllama scope use "$scope"
fi
securityllama install-shell
securityllama doctor

printf '%s\n' 'Next steps:'
printf '  exec %s -l\n' "${SHELL:-zsh}"
printf '%s\n' '  tmux new-session -A -s assessment' '  securityllama doctor'
