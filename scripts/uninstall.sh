#!/usr/bin/env bash
set -euo pipefail

purge=false
non_interactive=false
confirm_purge=false
while (($#)); do
  case "$1" in
    --purge) purge=true; shift ;;
    --non-interactive) non_interactive=true; shift ;;
    --confirm-purge) confirm_purge=true; shift ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
done

securityllama uninstall-shell

config_home=${SECURITYLLAMA_CONFIG_HOME:-${XDG_CONFIG_HOME:-$HOME/.config}/securityllama}
data_home=${SECURITYLLAMA_DATA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/securityllama}
rm -rf -- "$config_home/shell"
if command -v pipx >/dev/null 2>&1; then pipx uninstall securityllama || true; fi

if [[ $purge == true ]]; then
  if [[ $non_interactive == true && $confirm_purge != true ]]; then
    printf '%s\n' '--non-interactive purge requires --confirm-purge.' >&2
    exit 2
  fi
  if [[ $non_interactive != true ]]; then
    read -r -p "Type PURGE to permanently remove configuration and data: " answer
    [[ $answer == PURGE ]] || { printf '%s\n' 'Purge cancelled.'; exit 0; }
  fi
  rm -rf -- "$config_home" "$data_home"
else
  printf 'Preserved configuration: %s\nPreserved data: %s\n' "$config_home" "$data_home"
fi
