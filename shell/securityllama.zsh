# securityllama zsh integration: model output is inserted, never executed.

function _securityllama_widget() {
  local previous_status=$?
  local runtime_dir="${XDG_RUNTIME_DIR:-/tmp/securityllama-${UID}}"
  local work_dir request_file response_file buffer_file command_file action
  local -a pane_args
  mkdir -p -m 700 -- "$runtime_dir" || return 1
  work_dir=$(mktemp -d "$runtime_dir/widget.XXXXXXXX") || return 1
  chmod 700 "$work_dir"
  request_file="$work_dir/request.json"
  response_file="$work_dir/response.json"
  buffer_file="$work_dir/buffer"
  command_file="$work_dir/command"
  umask 077
  printf '%s' "$BUFFER" >| "$buffer_file"
  pane_args=()
  [[ -n ${TMUX_PANE:-} ]] && pane_args=(--pane "$TMUX_PANE")

  if ! securityllama _make-widget-request \
      --buffer-file "$buffer_file" --request-file "$request_file" \
      --shell zsh --cwd "$PWD" --cursor "$CURSOR" \
      "${pane_args[@]}" --last-status "$previous_status"; then
    rm -rf -- "$work_dir"
    zle redisplay
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
      BUFFER=$(<"$command_file")
      CURSOR=${#BUFFER}
    fi
  fi
  rm -rf -- "$work_dir"
  zle redisplay
}

zle -N securityllama-widget _securityllama_widget
bindkey '^[a' securityllama-widget
