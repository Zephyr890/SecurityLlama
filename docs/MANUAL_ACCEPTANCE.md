# Manual acceptance transcript

Automated evidence on 2026-07-16 is recorded in the living ExecPlan. The current
macOS development host does not provide tmux, a running Docker daemon, or a fresh
Kali VM, so the following interactive checks remain explicitly unverified
until run in the project's VirtualBox Kali VM.

## Fresh Kali / VirtualBox procedure

1. Configure a VirtualBox host-only adapter. Keep Ollama bound to host loopback
   and create the SSH tunnel documented in the README, or run Ollama in Kali.
2. Clone the repository and run the documented bootstrap command twice. Confirm
   `grep -c '>>> securityllama managed block >>>' ~/.zshrc ~/.bashrc` reports one
   block per file.
3. Start a login zsh and `tmux new -s assessment`; run `securityllama doctor`.
   Verify it reports both shell integration and the tmux chat binding. Press
   Prefix then A and confirm tmux creates a normal window named
   `securityllama`, not a popup. Press Prefix then A from the chat and confirm it
   returns to the previous window without terminating the chat process. Run
   `/q`, reopen with Prefix then A, and confirm a new chat window starts.
4. Submit a model request and verify the chat prompt returns immediately and
   animates with elapsed time. Return to the shell with Prefix then A, wait, and
   reopen the same chat. Verify the answer appears automatically and `/jobs` and
   `/last` report it. Submit two questions quickly and verify queued results
   appear in order with matching request IDs. Ask `explain the basics of web app
   fuzzing with burpsuite community` and verify terminal auto-omission and no
   command proposal.
5. Print synthetic scan-like output containing ANSI color and a fake bearer
   token in the originating pane. Open chat with Prefix then A, ask for analysis,
   and verify terminal controls and the token are absent. Run `/context` and
   verify capture, memory, redaction, truncation, and token-estimate fields.
6. Request an eligible proposal and run `/copy`. Verify `tmux show-buffer`
   contains the exact single-line proposal and no pane changed or executed it.
   Return with Prefix then A, paste with Prefix then ], inspect the editable
   prompt, and discard it with Ctrl-C without pressing Enter.
7. At a zsh prompt type, without executing,
   `curl -kI https://10.10.10.25/`. Press Alt-A, review, request a lower-impact
   variant, choose insertion, and verify the prompt changes but does not run.
   Discard with Ctrl-C. Repeat in Bash. Repeat outside tmux in a separate macOS
   or Kali terminal and verify the reviewer receives normal keyboard input
   without an `Input is not a terminal` warning.
8. Create an authorized scope containing `10.10.10.0/24`. Verify a proposal for
   `10.10.10.25` is in-scope, `192.0.2.10` is blocked, and substitution is
   unknown with typed confirmation.
9. In chat, add a note and bookmark, name the session, and export a report.
   Verify mode `0600`, redacted interaction meaning and dispositions, and no raw
   synthetic capture.
10. Attach a synthetic text file containing ANSI controls and a fake token.
    Close and reopen chat and verify `/attachments` still lists it. Confirm
    controls and the token are absent from model context, then detach it. Reattach,
    run `/new`, and verify the new session has no attachments. Verify symlinks,
    NUL-containing binaries, oversized files, and unreadable files are rejected.
11. Enable reduced motion and monochrome output, customize `shell_hotkey` and
    `tmux_binding`, reinstall, and confirm both bindings work. Confirm legacy
    popup and Alt-I/Alt-O settings are accepted but install no corresponding
    shell bindings.
12. Open a second tmux window in an unrelated directory and remove
    `~/.local/bin` from that shell's `PATH`. Verify Alt-A and Prefix then A still
    work. Prefix then A must focus the existing chat instead of creating another
    one. Ask a question and verify context comes from the second originating
    pane. Confirm no tmux command or source file contains `send-keys`.
13. Run uninstall without purge. Verify managed blocks and installed package are
    gone while configuration and `sessions.db` remain.

Record the Kali version, VirtualBox version, tmux/zsh/Bash versions, exact
commands, and observed pass/fail results below when this procedure is executed.
