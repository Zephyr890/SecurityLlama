# Start Codex here

From the repository root, give Codex this task:

> Read `AGENTS.md`, `.agent/PLANS.md`, and `.agent/EXECPLAN-kali-copilot.md`. Implement the ExecPlan end to end, keeping its living sections current as you work. Complete milestones in order, run `make check` at each stable stopping point, and do not weaken the security invariants. Do not implement autonomous command execution. Finish with the fresh-Kali bootstrap and documented manual acceptance transcript.

The repository may initially contain only the planning packet. Codex should create the source tree described in the ExecPlan.

## Human review gates

Review the implementation after these milestones:

1. Core Ollama client and structured response handling.
2. Terminal capture, sanitization, and read-only popup.
3. zsh/Bash command-buffer insertion.
4. Session memory, scope warnings, and audit storage.
5. Fresh-Kali bootstrap, uninstall, and release smoke tests.

At each gate, inspect the diff and verify that no code path can execute a model-generated command. In particular, search for `eval`, `shell=True`, and `send-keys` usage. A `tmux send-keys` call is acceptable only if it cannot send Enter or otherwise cause execution; the preferred implementation uses shell-buffer assignment and tmux buffers instead.
