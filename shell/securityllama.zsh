# securityllama zsh integration: model output is inserted, never executed.

function _securityllama_widget() {
  local previous_status=$?
  local runtime_dir="${XDG_RUNTIME_DIR:-/tmp/securityllama-${UID}}"
  local work_dir request_file response_file buffer_file command_file action
  local securityllama_bin
  local -a pane_args
  securityllama_bin=${commands[securityllama]:-}
  [[ -n "$securityllama_bin" ]] || { zle -M 'securityllama is not on PATH'; return 1; }
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

  if ! "$securityllama_bin" _make-widget-request \
      --buffer-file "$buffer_file" --request-file "$request_file" \
      --shell zsh --cwd "$PWD" --cursor "$CURSOR" \
      "${pane_args[@]}" --last-status "$previous_status"; then
    rm -rf -- "$work_dir"
    zle redisplay
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
      BUFFER=$(<"$command_file")
      CURSOR=${#BUFFER}
    fi
  fi
  rm -rf -- "$work_dir"
  zle redisplay
}

zle -N securityllama-widget _securityllama_widget
bindkey '^[a' securityllama-widget

function _securityllama_insert_proposal() {
  local runtime_dir="${XDG_RUNTIME_DIR:-/tmp/securityllama-${UID}}"
  local work_dir command_file action securityllama_bin
  securityllama_bin=${commands[securityllama]:-}
  [[ -n "$securityllama_bin" ]] || { zle -M 'securityllama is not on PATH'; return 1; }
  [[ -n ${TMUX_PANE:-} ]] || { zle -M 'SecurityLlama insertion requires tmux'; return 1; }
  if [[ -n "$BUFFER" ]]; then
    zle -M 'Clear the prompt before inserting a staged SecurityLlama proposal'
    return 1
  fi
  mkdir -p -m 700 -- "$runtime_dir" || return 1
  work_dir=$(mktemp -d "$runtime_dir/insert.XXXXXXXX") || return 1
  chmod 700 "$work_dir"
  command_file="$work_dir/command"
  action=$("$securityllama_bin" _consume-proposal --pane "$TMUX_PANE" --command-file "$command_file")
  if [[ "$action" == insert && -f "$command_file" ]]; then
    BUFFER=$(<"$command_file")
    CURSOR=${#BUFFER}
  else
    zle -M 'No unexpired SecurityLlama proposal is staged for this pane'
  fi
  rm -rf -- "$work_dir"
  zle redisplay
}

function _securityllama_open_cockpit() {
  local saved_buffer="$BUFFER" saved_cursor="$CURSOR" securityllama_bin
  securityllama_bin=${commands[securityllama]:-}
  if [[ -n ${TMUX:-} && -n ${TMUX_PANE:-} ]]; then
    if [[ -z "$securityllama_bin" ]]; then
      zle -M 'securityllama is not on PATH; reinstall with pipx and start a new shell'
    else
      tmux display-popup -EE -d "$PWD" -w 92% -h 85% -T ' SecurityLlama cockpit ' -- \
        "$securityllama_bin" cockpit --pane "$TMUX_PANE"
    fi
  else
    zle -M 'SecurityLlama cockpit requires tmux; use Alt-A for command review'
  fi
  BUFFER="$saved_buffer"
  CURSOR="$saved_cursor"
  zle redisplay
}

zle -N securityllama-insert-proposal _securityllama_insert_proposal
zle -N securityllama-open-cockpit _securityllama_open_cockpit
bindkey '^[i' securityllama-insert-proposal
bindkey '^[q' securityllama-open-cockpit
