# Manual acceptance transcript

Automated evidence on 2026-07-16 is recorded in the living ExecPlan. The current
macOS development host does not provide tmux, zsh, a running Docker daemon, or a
fresh Kali VM, so the following interactive checks remain explicitly unverified
until run in the project's VirtualBox Kali VM.

## Fresh Kali / VirtualBox procedure

1. Configure a VirtualBox host-only adapter. Keep Ollama bound to host loopback
   and create the SSH tunnel documented in the README, or run Ollama in Kali.
2. Clone the repository and run the documented bootstrap command twice. Confirm
   `grep -c '>>> kali-copilot managed block >>>' ~/.zshrc ~/.bashrc` reports one
   block per file.
3. Start a login zsh and `tmux new -s assessment`; run `kali-copilot doctor`.
4. Print synthetic scan-like output containing ANSI color and a fake bearer
   token. Press Prefix then A and verify the popup reports redaction and omits
   both the token and terminal controls.
5. Copy a proposed command with `c`. Run `tmux show-buffer`; verify the command
   is present and the originating pane did not change or execute it.
6. At a zsh prompt type, without executing,
   `curl -kI https://10.10.10.25/`. Press Alt-A, review, request a lower-impact
   variant, choose insertion, and verify the prompt changes but no request occurs
   until Enter. Discard with Ctrl-C.
7. Repeat step 6 in Bash.
8. Create an authorized scope containing `10.10.10.0/24`. Verify a proposal for
   `10.10.10.25` is in-scope, `192.0.2.10` is blocked, and substitution is
   unknown with typed confirmation.
9. Run uninstall without purge. Verify managed blocks and installed package are
   gone while configuration and `sessions.db` remain.

Record the Kali version, VirtualBox version, tmux/zsh/Bash versions, exact
commands, and observed pass/fail results below when this procedure is executed.
