# securityllama Bash integration: model output is inserted, never executed.

_securityllama_executable() {
  local securityllama_fallback=@SECURITYLLAMA_EXECUTABLE@
  local securityllama_path
  if [[ -n "$securityllama_fallback" && -x "$securityllama_fallback" ]]; then
    printf '%s\n' "$securityllama_fallback"
    return 0
  fi
  securityllama_path=$(type -P securityllama 2>/dev/null) || return 1
  [[ -n "$securityllama_path" && -x "$securityllama_path" ]] || return 1
  printf '%s\n' "$securityllama_path"
}

_securityllama_widget() {
  local previous_status=$?
  local runtime_dir="${XDG_RUNTIME_DIR:-/tmp/securityllama-${UID}}"
  local work_dir request_file response_file buffer_file command_file action
  local securityllama_bin
  local -a pane_args=()
  securityllama_bin=$(_securityllama_executable) || {
    printf '%s\n' 'securityllama executable is unavailable; reinstall with pipx, then run securityllama install-shell.' >&2
    return 1
  }
  mkdir -p -m 700 -- "$runtime_dir" || return 1
  work_dir=$(mktemp -d "$runtime_dir/widget.XXXXXXXX") || return 1
  chmod 700 "$work_dir"
  request_file="$work_dir/request.json"
  response_file="$work_dir/response.json"
  buffer_file="$work_dir/buffer"
  command_file="$work_dir/command"
  umask 077
  printf '%s' "$READLINE_LINE" > "$buffer_file"
  [[ -n ${TMUX_PANE:-} ]] && pane_args=(--pane "$TMUX_PANE")

  if ! "$securityllama_bin" _make-widget-request \
      --buffer-file "$buffer_file" --request-file "$request_file" \
      --shell bash --cwd "$PWD" --cursor "$READLINE_POINT" \
      "${pane_args[@]}" --last-status "$previous_status"; then
    rm -rf -- "$work_dir"
    return 1
  fi

  if [[ -n ${TMUX:-} && -n ${TMUX_PANE:-} ]]; then
    tmux display-popup -EE -d "$PWD" -w 92% -h 85% -- \
      "$securityllama_bin" shell-widget --request-file "$request_file" --response-file "$response_file"
  else
    if [[ ! -r /dev/tty || ! -w /dev/tty ]]; then
      rm -rf -- "$work_dir"
      printf '%s\n' 'securityllama cannot access the controlling terminal; open an interactive terminal and retry.' >&2
      return 1
    fi
    "$securityllama_bin" shell-widget \
      --request-file "$request_file" --response-file "$response_file" \
      </dev/tty >/dev/tty 2>&1
  fi

  if [[ -f "$response_file" ]]; then
    action=$("$securityllama_bin" _extract-widget-response \
      --response-file "$response_file" --command-file "$command_file")
    if [[ "$action" == insert && -f "$command_file" ]]; then
      IFS= read -r READLINE_LINE < "$command_file"
      READLINE_POINT=${#READLINE_LINE}
    fi
  fi
  rm -rf -- "$work_dir"
}

bind -x '"\ea":_securityllama_widget'
