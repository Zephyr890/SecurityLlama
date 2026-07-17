# securityllama Bash integration: model output is inserted, never executed.

_securityllama_widget() {
  local previous_status=$?
  local runtime_dir="${XDG_RUNTIME_DIR:-/tmp/securityllama-${UID}}"
  local work_dir request_file response_file buffer_file command_file action
  local securityllama_bin
  local -a pane_args=()
  securityllama_bin=$(command -v securityllama) || { printf '%s\n' 'securityllama is not on PATH.' >&2; return 1; }
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
    "$securityllama_bin" shell-widget --request-file "$request_file" --response-file "$response_file"
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

_securityllama_insert_proposal() {
  local runtime_dir="${XDG_RUNTIME_DIR:-/tmp/securityllama-${UID}}"
  local work_dir command_file action securityllama_bin
  securityllama_bin=$(command -v securityllama) || { printf '%s\n' 'securityllama is not on PATH.' >&2; return 1; }
  [[ -n ${TMUX_PANE:-} ]] || { printf '%s\n' 'SecurityLlama insertion requires tmux.' >&2; return 1; }
  if [[ -n "$READLINE_LINE" ]]; then
    printf '%s\n' 'Clear the prompt before inserting a staged SecurityLlama proposal.' >&2
    return 1
  fi
  mkdir -p -m 700 -- "$runtime_dir" || return 1
  work_dir=$(mktemp -d "$runtime_dir/insert.XXXXXXXX") || return 1
  chmod 700 "$work_dir"
  command_file="$work_dir/command"
  action=$("$securityllama_bin" _consume-proposal --pane "$TMUX_PANE" --command-file "$command_file")
  if [[ "$action" == insert && -f "$command_file" ]]; then
    IFS= read -r READLINE_LINE < "$command_file"
    READLINE_POINT=${#READLINE_LINE}
  else
    printf '%s\n' 'No unexpired SecurityLlama proposal is staged for this pane.' >&2
  fi
  rm -rf -- "$work_dir"
}

_securityllama_open_cockpit() {
  local saved_line="$READLINE_LINE" saved_point="$READLINE_POINT" securityllama_bin
  local securityllama_fallback=@SECURITYLLAMA_EXECUTABLE@
  securityllama_bin=$(command -v securityllama) || securityllama_bin=$securityllama_fallback
  if [[ -n ${TMUX:-} && -n ${TMUX_PANE:-} ]]; then
    if [[ -z "$securityllama_bin" || ! -x "$securityllama_bin" ]]; then
      printf '%s\n' 'securityllama executable is unavailable; reinstall with pipx, then run securityllama install-shell.' >&2
    else
      tmux display-popup -EE -d "$PWD" -w 92% -h 85% -T ' SecurityLlama cockpit ' -- \
        "$securityllama_bin" cockpit --pane "$TMUX_PANE"
    fi
  else
    printf '%s\n' 'SecurityLlama cockpit requires tmux; use Alt-A for command review.' >&2
  fi
  READLINE_LINE="$saved_line"
  READLINE_POINT="$saved_point"
}

bind -x '"\ei":_securityllama_insert_proposal'
bind -x '"\eo":_securityllama_open_cockpit'
