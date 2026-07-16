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
- The default Ollama endpoint is loopback; public endpoints require an explicit
  override and warning.
- The program runs as the invoking user and never handles sudo credentials.

Scope parsing in version 1 is deliberately conservative and advisory. Shell
substitutions, proxies, scripts, interpreters, aliases, and runtime behavior can
make static classification incomplete.

## Reporting

Do not open a public issue containing credentials, target data, or exploit
artifacts. Report suspected autonomous execution, secret disclosure, unsafe
temporary-file handling, or endpoint validation bypass privately to the project
maintainers. Include a minimal synthetic reproducer and affected version.
