# Manual acceptance transcript

Automated evidence on 2026-07-16 is recorded in the living ExecPlan. The current
macOS development host does not provide tmux, zsh, a running Docker daemon, or a
fresh Kali VM, so the following interactive checks remain explicitly unverified
until run in the project's VirtualBox Kali VM.

## Fresh Kali / VirtualBox procedure

1. Configure a VirtualBox host-only adapter. Keep Ollama bound to host loopback
   and create the SSH tunnel documented in the README, or run Ollama in Kali.
2. Clone the repository and run the documented bootstrap command twice. Confirm
   `grep -c '>>> securityllama managed block >>>' ~/.zshrc ~/.bashrc` reports one
   block per file.
3. Start a login zsh and `tmux new -s assessment`; run `securityllama doctor`.
   Type inert text at the prompt, press Alt-Q, close the cockpit, and verify the
   editable text and cursor position are unchanged. Run `bindkey '^[q'` and
   verify it reports `securityllama-open-cockpit`, not zsh's `push-line`.
   Reopen the cockpit and verify Alt-Q closes it from the idle cockpit prompt.
   Repeat with Esc then Q, Ctrl-G, `/q`, `/quit`, and Ctrl-D on an empty prompt.
   Submit a model request and verify the cockpit prompt returns immediately.
   Close the popup, continue using the originating shell, wait for generation,
   and reopen the cockpit. Verify the unseen answer appears, `/jobs` reports it
   completed, `/last` redisplays it, and no command was typed or executed.
4. Print synthetic scan-like output containing ANSI color and a fake bearer
   token. Press Prefix then A and verify the cockpit reports redaction and omits
   both the token and terminal controls. Run `/context` and verify the capture,
   memory, redaction, truncation, and estimated-token fields are visible.
5. Request a proposal and run `/copy`. Run `tmux show-buffer`; verify the command
   is present and the originating pane did not change or execute it.
6. Run `/insert`, return to the originating pane, and press Alt-I at an empty
   prompt. Verify the exact proposal appears but does not run. Clear it with
   Ctrl-C. Verify a second Alt-I reports that no proposal is staged. Stage
   another proposal, wait beyond the configured TTL, and verify it cannot be
   inserted.
7. At a zsh prompt type, without executing,
   `curl -kI https://10.10.10.25/`. Press Alt-A, review, request a lower-impact
   variant, choose insertion, and verify the prompt changes but no request occurs
   until Enter. Discard with Ctrl-C.
8. Repeat step 7 in Bash.
9. Create an authorized scope containing `10.10.10.0/24`. Verify a proposal for
   `10.10.10.25` is in-scope, `192.0.2.10` is blocked, and substitution is
   unknown with typed confirmation.
10. In the cockpit, add a note and bookmark, name the session, and export a
    report. Verify the report is mode `0600`, contains the redacted interaction
    meaning and dispositions, and does not contain the synthetic raw capture.
11. Create a synthetic text file containing ANSI controls and a fake token. Use
    `/attach PATH`, close and reopen the cockpit, and verify `/attachments` still
    lists it. Ask a question and confirm controls and the token are absent from
    the model context. Verify `/context` shows attachment counts and bounds.
    Detach it and confirm it is absent. Reattach it, run `/new`, and confirm the
    new session has no attachments. Also verify symlinks and NUL-containing
    binary files are rejected.
12. Enable reduced motion and monochrome output, reinstall shell integration,
    and confirm the selected settings and custom bindings work.
13. Temporarily make the installed cockpit command fail, invoke Prefix then A,
    and verify the popup remains visible with the error. Restore the command,
    reinstall shell integration, reload `~/.tmux.conf`, and verify the cockpit
    opens from both the repository and an unrelated working directory.
14. Run uninstall without purge. Verify managed blocks and installed package are
    gone while configuration and `sessions.db` remain.

Record the Kali version, VirtualBox version, tmux/zsh/Bash versions, exact
commands, and observed pass/fail results below when this procedure is executed.
