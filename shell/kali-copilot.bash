# kali-copilot Bash integration: model output is inserted, never executed.

_kali_copilot_widget() {
  local previous_status=$?
  local runtime_dir="${XDG_RUNTIME_DIR:-/tmp/kali-copilot-${UID}}"
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

  if ! kali-copilot _make-widget-request \
      --buffer-file "$buffer_file" --request-file "$request_file" \
      --shell bash --cwd "$PWD" --cursor "$READLINE_POINT" \
      "${pane_args[@]}" --last-status "$previous_status"; then
    rm -rf -- "$work_dir"
    return 1
  fi

  if [[ -n ${TMUX:-} && -n ${TMUX_PANE:-} ]]; then
    tmux display-popup -E -w 92% -h 85% -- \
      kali-copilot shell-widget --request-file "$request_file" --response-file "$response_file"
  else
    kali-copilot shell-widget --request-file "$request_file" --response-file "$response_file"
  fi

  if [[ -f "$response_file" ]]; then
    action=$(kali-copilot _extract-widget-response \
      --response-file "$response_file" --command-file "$command_file")
    if [[ "$action" == insert && -f "$command_file" ]]; then
      IFS= read -r READLINE_LINE < "$command_file"
      READLINE_POINT=${#READLINE_LINE}
    fi
  fi
  rm -rf -- "$work_dir"
}

bind -x '"\ea":_kali_copilot_widget'
