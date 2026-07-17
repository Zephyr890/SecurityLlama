# securityllama Bash integration: model output is inserted, never executed.

_securityllama_widget() {
  local previous_status=$?
  local runtime_dir="${XDG_RUNTIME_DIR:-/tmp/securityllama-${UID}}"
  local work_dir request_file response_file buffer_file command_file action
  local -a pane_args=()
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

  if ! securityllama _make-widget-request \
      --buffer-file "$buffer_file" --request-file "$request_file" \
      --shell bash --cwd "$PWD" --cursor "$READLINE_POINT" \
      "${pane_args[@]}" --last-status "$previous_status"; then
    rm -rf -- "$work_dir"
    return 1
  fi

  if [[ -n ${TMUX:-} && -n ${TMUX_PANE:-} ]]; then
    tmux display-popup -E -w 92% -h 85% -- \
      securityllama shell-widget --request-file "$request_file" --response-file "$response_file"
  else
    securityllama shell-widget --request-file "$request_file" --response-file "$response_file"
  fi

  if [[ -f "$response_file" ]]; then
    action=$(securityllama _extract-widget-response \
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
  local work_dir command_file action
  [[ -n ${TMUX_PANE:-} ]] || { printf '%s\n' 'SecurityLlama insertion requires tmux.' >&2; return 1; }
  if [[ -n "$READLINE_LINE" ]]; then
    printf '%s\n' 'Clear the prompt before inserting a staged SecurityLlama proposal.' >&2
    return 1
  fi
  mkdir -p -m 700 -- "$runtime_dir" || return 1
  work_dir=$(mktemp -d "$runtime_dir/insert.XXXXXXXX") || return 1
  chmod 700 "$work_dir"
  command_file="$work_dir/command"
  action=$(securityllama _consume-proposal --pane "$TMUX_PANE" --command-file "$command_file")
  if [[ "$action" == insert && -f "$command_file" ]]; then
    IFS= read -r READLINE_LINE < "$command_file"
    READLINE_POINT=${#READLINE_LINE}
  else
    printf '%s\n' 'No unexpired SecurityLlama proposal is staged for this pane.' >&2
  fi
  rm -rf -- "$work_dir"
}

_securityllama_open_cockpit() {
  if [[ -n ${TMUX:-} && -n ${TMUX_PANE:-} ]]; then
    tmux display-popup -E -w 92% -h 85% -T ' SecurityLlama cockpit ' -- \
      securityllama cockpit --pane "$TMUX_PANE"
  else
    printf '%s\n' 'SecurityLlama cockpit requires tmux; use Alt-A for command review.' >&2
  fi
}

bind -x '"\ei":_securityllama_insert_proposal'
bind -x '"\eq":_securityllama_open_cockpit'
