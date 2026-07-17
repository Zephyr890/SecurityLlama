# securityllama

`securityllama` is a terminal assistant for authorized security testing in Kali
Linux VMs. It sends bounded, sanitized context to an operator-configured Ollama
endpoint and can place a proposed command into an editable zsh or Bash prompt.

The application never executes a model-generated command. A human must inspect
the exact proposal and press Enter in their ordinary shell. Scope classification
is advisory and is not a firewall or proof of authorization.

## Install on Kali

Ollama and the selected model must already be available locally or through an
operator-managed tunnel. From a clone:

```sh
./scripts/bootstrap-kali.sh \
  --ollama-url http://127.0.0.1:11434 \
  --model qwen2.5-coder:3b
exec "$SHELL" -l
tmux new -s assessment
securityllama doctor
```

For an interactive setup after installation, run:

```sh
securityllama setup
```

On a fresh checkout, the install-and-setup wizard can be run directly with:

```sh
./scripts/bootstrap-kali.sh --wizard
```

The wizard configures the Ollama URL and model, keeps extended thinking
disabled by default for faster CPU responses, installs shell integration, and
runs the same diagnostics as `securityllama doctor`. It also records the Mac
SSH tunnel details and prints the command to run manually. Show it later with:

```sh
securityllama tunnel command
```

The default Ollama request disables Qwen-style extended thinking for a faster
interactive experience on CPU-only hosts. Set `[ollama].think = true` in
`~/.config/securityllama/config.toml` when deeper reasoning is worth the added
latency.

The bootstrap installs only required Debian packages, installs this package with
pipx, preserves existing configuration, backs up changed shell files, and is
safe to rerun after `git pull`. Use `--no-apt` when dependencies are already
managed, `--dev` for an editable pipx install, or `--scope NAME` to create/select
a restrictive scope template.

## Use

Prefix then A creates or focuses a persistent tmux window named
`securityllama`. Press the same binding from the chat window to return to the
previous tmux window. This is an ordinary terminal REPL rather than a popup, so
conversation input does not share zsh ZLE, Bash Readline, Meta-key handling, or
the assessment shell's editable buffer. The binding records the invoking pane
and working directory every time; the next request captures that pane even when
the chat was originally opened from another tmux window or directory.

Run `securityllama chat` directly inside tmux when a shortcut is not desired.
The legacy `securityllama cockpit --pane ID` command remains an alias for upgrade
compatibility, but installed integration no longer opens a cockpit popup.

At a zsh or Bash prompt, Alt-A remains an optional one-shot review of the exact
editable command buffer. A validated replacement can be assigned to that buffer
only after confirmation; the operator must still press Enter. No other Alt-key
bindings are installed by default.

The chat shows an animated request indicator, background request status,
model/profile/session status, validated responses, and an estimated context
budget. Use `/context` to inspect included sources and
`/include terminal|memory|scope on|off` to control the next request. Token counts
are estimates because exact tokenization is model-specific. Captured text
remains bounded, sanitized, redacted, and omitted from persistent audit storage.

Attach text evidence to the current logical session with `/attach PATH`:

```text
/attach /home/kali/assessment/nmap-results.txt
/attachments
/detach /home/kali/assessment/nmap-results.txt
/detach all
```

Attachments remain active when the chat window is closed and reopened. They stop
contributing to context when explicitly detached or when `/new`, `session new`,
or `session clear` starts a new logical session. SecurityLlama stores only
private runtime references—not file contents—and re-reads each file for every
request. Replaced files must be detached and reattached. Symlinks, non-regular
files, binary files containing NUL bytes, oversized files, and unreadable files
are rejected. Terminal controls and likely secrets are removed before attached
text is sent to Ollama. All terminal and attachment text shares the configured
context bounds, so `/context` reports when combined input was truncated.

When a proposal passes local policy, `/copy` sends its validated single-line
text to the tmux paste buffer through stdin. Use Prefix then A to return to the
shell and tmux's normal Prefix then ] binding to paste it into the editable
prompt. SecurityLlama never types into a pane or sends Enter; the operator still
reviews the exact text and explicitly executes or discards it.

Useful chat commands include:

```text
/help                       keyboard and command reference
/status                     endpoint, model, scope, and session status
/jobs  /last                list requests or show the newest result
/mode ask|explain|review|suggest
/profile fast|deep
/context
/include terminal|memory|scope on|off
/attach PATH  /attachments  /detach PATH|all
/proposals  /next  /prev
/alternative Prefer a passive validation
/diff CURRENT_COMMAND
/copy  /reject
/note TEXT  /bookmark TEXT
/name ENGAGEMENT_NAME
/report /path/to/redacted-report.md
/new  /clear  /quit  /q
```

Reduced motion, monochrome output, completion bell, the Alt-A review key, and
the tmux chat binding are configurable under `[ui]`. Legacy `popup_*`,
`insert_hotkey`, `ask_hotkey`, and `proposal_ttl_seconds` settings are accepted
so existing files still load, but they are ignored. Rerun
`securityllama install-shell` after changing bindings.

Installed integration records the absolute SecurityLlama launcher for both
Alt-A and Prefix then A, so they work from unrelated directories even when
`~/.local/bin` is absent from `PATH`. After an upgrade, rerun
`securityllama install-shell`, start a new login shell, and reload an existing
tmux server with `tmux source-file ~/.tmux.conf`. `securityllama doctor` checks
the shell and tmux managed blocks separately.

Submitting a question captures and redacts bounded context from the most recent
originating pane, starts a detached request, and immediately returns to the chat
prompt. Prefix then A returns to the shell without stopping the request. `/last`
refreshes the newest request and `/jobs` lists up to 20 recent requests.
Starting `/new` moves to a new logical session, so earlier results remain
associated with the old session.

The chat prompt animates with the active request count and elapsed time.
Completed answers render automatically above the editable prompt; the operator
can keep typing while generation runs. Reduced-motion mode uses a static working
indicator instead of animated frames.

Questions submitted to one logical session are processed in submission order.
Additional questions show as `queued` while the current request runs, preventing
later answers from overtaking earlier ones. Immediately before a queued request
starts, SecurityLlama refreshes its bounded conversation memory with completed
earlier turns when auditing and memory inclusion are enabled. Each result is
rendered as a question/answer card carrying the same short request ID, and any
proposal retains that request identity and its originating pane.

Clearly conceptual questions—such as “explain the basics of web app fuzzing”—
automatically omit unrelated terminal capture so small local models are not
distracted by shell metadata. `/context` reports this as `Terminal auto-omitted`.
Conceptual turns cannot publish a command: even if the model returns
one, SecurityLlama removes it and its action metadata locally. Actionable
requests made through review/suggest mode or explicit command language retain
normal proposal behavior. The chat renders an eligible proposal exactly once.

Raw terminal and attachment context crosses to the detached worker through an
anonymous pipe and is not written to background job state. Private `0600`
runtime state contains the submitted question, status, sanitized validated
answer, and inert proposal metadata so the chat can recover after closing.
Completed answers still follow normal audit retention when auditing is enabled.

Non-interactive modes also accept bounded context on stdin:

```sh
securityllama ask "What does this failure imply?"
journalctl -n 50 | securityllama explain "Identify the likely failure boundary."
securityllama review "Review the current command."
nmap-output-command | securityllama suggest "Propose one low-impact validation."
```

When `explain` receives non-empty stdin, that current tool output is treated as
primary evidence and prior conversation turns are omitted from the model request.
This prevents an earlier interpretation from overriding newly supplied results.
Security-tool ranking responses use a validated `findings` list rendered as
numbered terminal lines. Assumptions and warnings are rendered as separate
bulleted sections rather than compressed into prose.

Management commands include:

```sh
securityllama config init
securityllama session new
securityllama session status
securityllama session clear
securityllama session name lab01-web
securityllama scope init lab01
securityllama scope use lab01
securityllama scope show
securityllama history
securityllama note --bookmark "Validate the TLS observation manually"
securityllama report --format markdown --output ./securityllama-report.md
securityllama redact < captured-output.txt
```

Edit a scope file under `~/.config/securityllama/scopes/` to add the CIDRs,
domains, and permissions actually authorized for an engagement. New scope files
are unauthorized by default. Scope analysis is conservative: substitutions,
interpreters, scripts, redirects, or unclear targets produce an `unknown`
warning. Out-of-scope insertion is disabled by default.

## Development

Python 3.11 or newer is required:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
make check
```

Start the local fixture service without external network access:

```sh
make fake-ollama
curl http://127.0.0.1:11435/api/tags
```

Its `--fixture` option supports `success`, `proposal`, `malformed_json`,
`timeout`, `missing_model`, and `control_sequences` responses.

`make check` runs formatting verification, linting, strict type checking, tests,
and shell checks without contacting external services. `make smoke-kali` runs
the install/idempotence/uninstall workflow in `kalilinux/kali-rolling` when a
Docker daemon is available.

## Kali in VirtualBox

The safest default is to run Ollama inside the VM at `127.0.0.1`, or keep
Ollama bound to loopback on the host and use an operator-managed SSH tunnel.
With a VirtualBox host-only adapter, a representative tunnel from Kali is:

```sh
ssh -N \
  -L 127.0.0.1:11434:127.0.0.1:11434 \
  <host-user>@<host-only-host-ip>
```

Then configure `securityllama` for `http://127.0.0.1:11434`. Do not expose
Ollama on a bridged or public interface merely to make the VM connect. The
project does not modify VirtualBox, host firewall, SSH, or Ollama settings.

## Trust boundary

Terminal captures, banners, files, and model output are untrusted. The finished
application strips terminal controls, redacts likely secrets, bounds context,
validates structured model responses, and stores no raw terminal context by
default. It cannot determine whether a real-world action is authorized; that
responsibility remains with the operator.

The architecture keeps five boundaries separate:

1. Shell/tmux integration captures only explicit, bounded context.
2. Sanitization removes terminal controls and redacts likely secrets.
3. Ollama receives a versioned JSON packet labelled as untrusted data.
4. Pydantic validates the structured response before display or insertion.
5. Local policy and audit code assess inert command text and persist only
   redacted metadata plus a context hash.

Session memory includes a bounded number of redacted turns: the answer plus
structured findings, assumptions, and warnings. It does not include historical
terminal captures or raw input files. Audits default to
`~/.local/share/securityllama/sessions.db`, mode `0600`, and omit raw context.
Set `[audit].enabled = false` to disable both audit records and persistent recent
turn memory. Session names, operator-authored notes, bookmarks, proposal
dispositions, and exported reports are stored or written with owner-only
permissions. Reports explicitly omit raw terminal context.

## Troubleshooting and removal

Run `securityllama doctor` first. It reports configuration, private-directory
permissions, tmux, shell sourcing, endpoint reachability, model availability,
scope status, and audit writability independently. Exit code `3` means the
endpoint is unavailable, `4` means the model is not listed, and `5` means two
structured-response validations failed.

For exit code 5, repeat the request with `--debug`. SecurityLlama prints bounded,
terminal-sanitized, secret-redacted previews of the initial and repair model
responses together with Ollama's `done_reason`, `prompt_eval_count`, and
`eval_count`. The previews are written to stderr and are not added to the audit
database. A `done_reason` of `length` indicates output truncation; an empty
preview indicates that Ollama returned no message content; prose, thinking tags,
or incomplete JSON in the preview indicate a model/format compatibility issue.
A preview beginning with ContextPacket fields such as `active_scope`, `cwd`, or
`recent_turns` means the model echoed its input instead of producing an assistant
response; current releases detect that pattern and retry from compact input.
Review redacted debug output before sharing it because target details are not
treated as secrets automatically.

After an update, rerun `./scripts/bootstrap-kali.sh` with the same explicit URL
and model. To remove the package and managed shell blocks while preserving user
configuration and audits:

```sh
./scripts/uninstall.sh
```

Permanent deletion requires `--purge` and an explicit `PURGE` confirmation.
For automated removal, both `--non-interactive` and `--confirm-purge` are
required.

## Limitations

This tool cannot establish authorization, fully parse shell semantics, enforce a
network boundary, detect every secret, or guarantee model accuracy. It does not
install Ollama, download models, modify VirtualBox networking, open firewalls,
manage SSH, escalate privileges, or execute proposed commands. The operator is
responsible for authorization, evidence handling, and normal shell execution.

See [SECURITY.md](SECURITY.md) for security guarantees and reporting guidance.
