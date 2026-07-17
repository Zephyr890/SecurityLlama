# Security policy and trust boundary

`securityllama` is advisory software. It must never execute a model-generated
command, submit a privilege prompt, or claim that advisory scope parsing makes
a command authorized or safe. An eligible validated single-line proposal may be
copied to the system clipboard; the operator explicitly pastes it into an
ordinary shell, inspects it, and decides whether to press Enter.

## Invariants

- Model, pasted, piped, and file content is untrusted data.
- No model output is passed to a shell, `eval`, command substitution, terminal
  input, or an Enter key.
- Proposed commands containing newlines, NULs, or invalid control characters
  are rejected for insertion.
- Context is bounded and likely secrets are redacted before model submission.
- Raw selected context is not persisted by default.
- Detached chat workers receive bounded, sanitized context through an
  anonymous pipe. Private runtime job state contains the explicit question,
  status, and sanitized validated response, but never captured terminal or
  attached-file input. Workers have no shell-input or command-execution path.
- Workers for one logical session use a private owner-only queue lock and run in
  submission order. A queued request refreshes only bounded audited conversation
  turns; it does not reload or persist raw terminal or attachment context.
- Clearly conceptual turns are locally prohibited from returning an insertable
  command. This enforcement does not rely on model compliance; explicit review,
  suggest, or command-building turns continue through normal proposal policy
  assessment.
- Raw attached-file input is not written directly to attachment state, audit
  records, conversation memory, or reports. Private runtime state contains only
  explicit file references tied to a logical session. Contents are freshly
  read, terminal-sanitized, secret-redacted, and bounded for each request.
- Attachments must be regular non-symlink files. A replaced file identity is
  rejected until the operator explicitly detaches and reattaches it.
- The standalone console does not capture another terminal's scrollback. Context
  enters through explicit questions, attachments, or bounded stdin to direct CLI
  commands.
- Eligible proposals reach `pbcopy`, `wl-copy`, `xclip`, or `xsel` only as stdin
  data to a fixed argument list. SecurityLlama never passes proposal text as a
  command-line argument, types into a terminal, or synthesizes Enter.
- The XDG desktop launcher contains only the resolved local SecurityLlama
  executable and the fixed `console` subcommand. Model and context data never
  enter it.
- The default Ollama endpoint is loopback; public endpoints require an explicit
  override and warning.
- The program runs as the invoking user and never handles sudo credentials.

Scope parsing in version 1 is deliberately conservative and advisory. Shell
substitutions, proxies, scripts, interpreters, aliases, and runtime behavior can
make static classification incomplete.

The chat context meter is an estimate, not an exact tokenizer result or a
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
