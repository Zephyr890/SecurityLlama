# Security policy and trust boundary

`securityllama` is advisory software. It must never execute a model-generated
command, submit a privilege prompt, or claim that advisory scope parsing makes
a command authorized or safe. Command insertion means assigning a validated,
single-line string to the shell's editable buffer; execution remains an explicit
operator action.

## Invariants

- Model, terminal, banner, and file content is untrusted data.
- No model output is passed to a shell, `eval`, command substitution, or a tmux
  Enter key.
- Proposed commands containing newlines, NULs, or invalid control characters
  are rejected for insertion.
- Context is bounded and likely secrets are redacted before model submission.
- Raw terminal context is not persisted by default.
- Detached cockpit workers receive bounded, sanitized context through an
  anonymous pipe. Private runtime job state contains the explicit question,
  status, and sanitized validated response, but never captured terminal or
  attached-file input. Workers have no shell-input or command-execution path.
- Raw attached-file input is not written directly to attachment state, audit
  records, conversation memory, or reports. Private runtime state contains only
  explicit file references tied to a logical session. Contents are freshly
  read, terminal-sanitized, secret-redacted, and bounded for each request.
- Attachments must be regular non-symlink files. A replaced file identity is
  rejected until the operator explicitly detaches and reattaches it.
- Cross-pane proposals are staged as validated inert JSON in a private runtime
  directory, are scoped to one logical session and tmux pane, expire, and are
  consumed at most once.
- Only the zsh ZLE or Bash Readline widget may assign a staged proposal to an
  editable command buffer. The cockpit never types into a pane or synthesizes
  Enter.
- The default Ollama endpoint is loopback; public endpoints require an explicit
  override and warning.
- The program runs as the invoking user and never handles sudo credentials.

Scope parsing in version 1 is deliberately conservative and advisory. Shell
substitutions, proxies, scripts, interpreters, aliases, and runtime behavior can
make static classification incomplete.

The cockpit context meter is an estimate, not an exact tokenizer result or a
security boundary. Context-source toggles affect model disclosure but never
disable response validation, terminal-control stripping, secret redaction, or
local proposal policy. Operator notes are persistent by explicit action and
should not contain credentials or unredacted sensitive target data.
Attachment paths and sanitized content are disclosed to the configured Ollama
endpoint by the operator's explicit `/attach` action. A context estimate may
under-count model-specific tokens; configured byte and line limits remain the
authoritative local bounds. Validated model responses can quote or derive
material from attached context and are retained by the normal audit and report
features and by private background result state; inspect those outputs before
retaining or sharing them.

## Reporting

Do not open a public issue containing credentials, target data, or exploit
artifacts. Report suspected autonomous execution, secret disclosure, unsafe
temporary-file handling, or endpoint validation bypass privately to the project
maintainers. Include a minimal synthetic reproducer and affected version.
