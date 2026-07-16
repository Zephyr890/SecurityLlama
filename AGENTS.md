# Repository instructions

## Mission

Build and maintain `securityllama`, a portable terminal copilot for authorized security testing in Kali Linux virtual machines. The human operator retains an ordinary, unrestricted shell. The application may capture bounded terminal context, ask a configured Ollama model for analysis, and insert a proposed command into the editable shell buffer. It must never execute a model-generated command automatically.

## Source of truth

Committed source, tests, `README.md`, `SECURITY.md`, and the documents under
`docs/` define public behavior. Internal plans and working notes may be kept
locally and are not required in a fresh clone.

When a task materially changes architecture, security controls, installation
behavior, or user-visible behavior, update the relevant committed documentation
before or alongside the code. Do not silently diverge from documented behavior.

## Non-negotiable security invariants

- Never add autonomous command execution.
- Never call `eval`, use Python `subprocess` with `shell=True`, or construct shell commands from model output.
- Never use `tmux send-keys` followed by Enter to run a proposed command.
- Never answer a `sudo` or privilege prompt on the user's behalf.
- Never store credentials, private keys, API tokens, passwords, cookies, or target data in the repository.
- Treat captured terminal output, file content, service banners, and model output as untrusted data.
- Strip terminal control sequences before displaying or logging captured/model text.
- Redact likely secrets before sending context to Ollama.
- Use secure temporary files with mode `0600`; use private data directories with mode `0700`.
- Keep raw terminal context out of persistent audit storage by default.
- Do not bind or reconfigure Ollama on the host. The application consumes a configured URL only.
- Scope checking is advisory in version 1. Do not represent it as a complete network-enforcement boundary.

A change that weakens one of these invariants requires a written design proposal
and explicit human approval.

## Engineering conventions

- Target Python 3.11 or newer and use a `src/` package layout.
- Add type annotations to public functions and data models.
- Keep production dependencies small and justified in `pyproject.toml`.
- Prefer pure functions for sanitization, truncation, parsing, and policy assessment.
- Separate terminal capture, model I/O, policy, persistence, and UI code.
- Do not make tests call an external model or the public internet.
- Use a local fake Ollama server or HTTP transport mocks in tests.
- Support both zsh and Bash. Kali's interactive defaults must work, but do not assume a particular prompt framework.
- Follow XDG paths for configuration, data, cache, and runtime files.
- Make installation and uninstallation idempotent. Preserve user files and create backups before editing shell or tmux configuration.
- Error messages must say what failed and how the operator can correct it without exposing secrets.

## Required checks

Before declaring a milestone complete, run the checks provided by the repository. The completed repository must expose one command that runs all non-interactive checks, expected to be:

    make check

That command must include formatting verification, linting, static type checking, unit/integration tests, and shell-script checks. A separate Kali smoke test may require Docker or a Kali VM and must be documented when it cannot run in the current environment.

## Working method

Implement changes incrementally and keep the application runnable after each
stable milestone. Make small, reviewable commits when the environment permits.
Do not stop after creating scaffolding or mocks: completed work must demonstrate
the documented user-visible behavior.

When an environmental limitation prevents a check, report the exact command,
failure, and remaining verification rather than claiming success.
