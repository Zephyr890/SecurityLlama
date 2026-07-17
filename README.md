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

At a zsh or Bash prompt, Alt-A reviews the exact editable command buffer. A
validated proposal can be assigned to the prompt after confirmation; the
operator must still press Enter. Prefix then A or Alt-Q opens the persistent,
multi-turn tmux cockpit for the originating pane. The cockpit keeps assistant
conversation separate from assessment commands and shell history.

The cockpit shows an elapsed request animation, model/profile/session status,
validated responses, and an estimated context-window budget. Use `/context` to
inspect included sources and `/include terminal|memory|scope on|off` to control
the next request. Token counts are estimates because exact tokenization is
model-specific. Captured text remains bounded, sanitized, redacted, and omitted
from persistent audit storage.

Attach text evidence to the current logical session with `/attach PATH`:

```text
/attach /home/kali/assessment/nmap-results.txt
/attachments
/detach /home/kali/assessment/nmap-results.txt
/detach all
```

Attachments remain active when the cockpit is closed and reopened. They stop
contributing to context when explicitly detached or when `/new`, `session new`,
or `session clear` starts a new logical session. SecurityLlama stores only
private runtime references—not file contents—and re-reads each file for every
request. Replaced files must be detached and reattached. Symlinks, non-regular
files, binary files containing NUL bytes, oversized files, and unreadable files
are rejected. Terminal controls and likely secrets are removed before attached
text is sent to Ollama. All terminal and attachment text shares the configured
context bounds, so `/context` reports when combined input was truncated.

When a proposal passes local policy, `/insert` stages it for the originating
pane in a private, expiring runtime file. Return to an empty shell prompt and
press Alt-I to place that exact single-line proposal in the editable buffer.
SecurityLlama does not type into the pane or send Enter. `/copy` uses the tmux
paste buffer instead. Staged proposals expire after five minutes by default and
are consumed at most once.

Useful cockpit commands include:

```text
/help                       keyboard and command reference
/status                     endpoint, model, scope, and session status
/mode ask|explain|review|suggest
/profile fast|deep
/context
/include terminal|memory|scope on|off
/attach PATH  /attachments  /detach PATH|all
/proposals  /next  /prev
/alternative Prefer a passive validation
/diff CURRENT_COMMAND
/insert  /copy  /reject
/note TEXT  /bookmark TEXT
/name ENGAGEMENT_NAME
/report /path/to/redacted-report.md
/new  /clear  /quit
```

Ctrl-C cancels a model wait when supported by the HTTP transport. Reduced
motion, monochrome output, completion bell, popup size, proposal lifetime, and
all three shell shortcuts are configurable under `[ui]`. Rerun
`securityllama install-shell` after changing bindings.

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
