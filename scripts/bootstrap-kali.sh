#!/usr/bin/env bash
set -euo pipefail

missing_core_apt_packages() {
  if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' python3 python3-venv
  elif ! command -v pipx >/dev/null 2>&1; then
    printf '%s\n' python3-venv
  fi
  if ! command -v pipx >/dev/null 2>&1; then
    printf '%s\n' pipx
  fi
}

missing_optional_apt_packages() {
  command -v xclip >/dev/null 2>&1 || printf '%s\n' xclip
  command -v zsh >/dev/null 2>&1 || printf '%s\n' zsh
}

apt_supported() {
  if [[ ! -r /etc/os-release ]]; then
    printf '%s\n' \
      'Warning: cannot identify this operating system; skipping OS package assumptions.' >&2
    return 1
  fi
  # shellcheck disable=SC1091
  . /etc/os-release
  if [[ ${ID:-} != kali && ${ID_LIKE:-} != *debian* && ${ID:-} != debian && ${ID:-} != ubuntu ]]; then
    printf 'Warning: %s is not identified as Kali/Debian-family.\n' "${PRETTY_NAME:-this OS}" >&2
    return 1
  fi
  return 0
}

main() {
  local repo_root ollama_url model scope no_apt dev non_interactive wizard
  repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  ollama_url=""
  model=""
  scope=""
  no_apt=false
  dev=false
  non_interactive=false
  wizard=false
  export PATH="$HOME/.local/bin:$PATH"

  while (($#)); do
    case "$1" in
      --ollama-url) ollama_url=${2:?missing URL}; shift 2 ;;
      --model) model=${2:?missing model}; shift 2 ;;
      --scope) scope=${2:?missing scope}; shift 2 ;;
      --no-apt) no_apt=true; shift ;;
      --dev) dev=true; shift ;;
      --non-interactive) non_interactive=true; shift ;;
      --wizard) wizard=true; shift ;;
      *) printf 'Unknown option: %s\n' "$1" >&2; return 2 ;;
    esac
  done

  if [[ $no_apt == false ]] && ! apt_supported; then
    no_apt=true
  fi

  local -a missing_packages=()
  local package
  while IFS= read -r package; do
    [[ -n $package ]] && missing_packages+=("$package")
  done < <(missing_core_apt_packages)

  if [[ $no_apt == false ]]; then
    if ((${#missing_packages[@]})); then
      while IFS= read -r package; do
        [[ -n $package ]] && missing_packages+=("$package")
      done < <(missing_optional_apt_packages)
      local -a apt=(apt-get)
      if ((EUID != 0)); then apt=(sudo apt-get); fi
      if [[ $non_interactive == true ]]; then export DEBIAN_FRONTEND=noninteractive; fi
      "${apt[@]}" update
      "${apt[@]}" install --yes "${missing_packages[@]}"
    else
      printf '%s\n' 'Required system dependencies are present; skipping apt repository access.'
    fi
  fi

  local -a missing_commands=()
  command -v python3 >/dev/null 2>&1 || missing_commands+=(python3)
  command -v pipx >/dev/null 2>&1 || missing_commands+=(pipx)
  if ((${#missing_commands[@]})); then
    printf 'Missing required command(s):' >&2
    printf ' %s' "${missing_commands[@]}" >&2
    printf '%s\n' '.' >&2
    printf '%s\n' \
      'Install them from a trusted package source, or rerun on Kali/Debian with repository access and without --no-apt.' >&2
    return 2
  fi

  # Remove the pre-rename package if this is an upgrade from kali-copilot.
  pipx uninstall kali-copilot >/dev/null 2>&1 || true

  local -a install_args=(install --force)
  if [[ $dev == true ]]; then install_args+=(--editable); fi
  pipx "${install_args[@]}" "$repo_root"

  if [[ $wizard == true ]]; then
    if [[ -n $ollama_url || -n $model || -n $scope ]]; then
      printf '%s\n' '--wizard cannot be combined with --ollama-url, --model, or --scope.' >&2
      return 2
    fi
    securityllama setup
    return $?
  fi

  local -a config_args=(config init)
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
  securityllama install-desktop
  securityllama doctor

  printf '%s\n' 'Next steps:'
  printf '%s\n' '  securityllama console' '  securityllama doctor'
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  main "$@"
fi
