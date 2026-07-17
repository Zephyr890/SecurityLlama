# Manual acceptance transcript

Automated checks cover installation, the standalone console entry point,
background requests, sanitization, policy, persistence, and uninstallation. The
following desktop and clipboard behavior must also be confirmed in the project's
VirtualBox Kali VM.

## Fresh Kali / VirtualBox procedure

1. Configure a VirtualBox host-only adapter. Keep Ollama bound to host loopback
   and create the SSH tunnel documented in the README, or run Ollama in Kali.
2. Clone the repository and run the documented bootstrap command twice. Confirm
   `~/.local/share/applications/securityllama-console.desktop` exists once,
   contains `Terminal=true`, and names the absolute pipx launcher. Confirm no
   SecurityLlama managed block remains in `.zshrc`, `.bashrc`, or `.tmux.conf`.
3. Open **SecurityLlama Console** from Kali's application menu. Confirm it opens
   in a normal terminal window without tmux and shows the configured model,
   working directory, session, and the statement that proposals are never
   executed. Close it with `/q`.
4. From unrelated directories in zsh and Bash, run `securityllama console` and
   the compatibility alias `securityllama chat`. Confirm both open the same
   standalone console without shell hotkeys or terminal-multiplexer state.
5. Submit a model request and verify the console prompt returns immediately and
   animates with elapsed time. Close the console, wait, reopen it, and confirm the
   answer appears automatically and `/jobs` and `/last` report it. Submit two
   questions quickly and verify queued results appear in order with matching
   request IDs.
6. Paste synthetic scan-like text containing ANSI color and a fake bearer token
   into a question. Attach a file containing the same fixtures with `/attach`.
   Confirm controls and the token are absent from model context. Run `/context`
   and verify attachment, memory, redaction, truncation, and token-estimate
   fields. Confirm automatic terminal capture remains zero.
7. Pipe bounded synthetic output through `securityllama explain` and confirm it is
   treated as current evidence. Verify it is sanitized and is absent from the
   persistent audit record.
8. Request an eligible proposal and run `/copy`. Verify `xclip -o -selection
   clipboard` returns the exact single-line proposal. Paste it into an ordinary
   editable shell prompt, inspect it, and discard it with Ctrl-C without pressing
   Enter. Confirm no command ran and no terminal received synthetic keystrokes.
9. Ask `explain the basics of web app fuzzing with burpsuite community` and
   verify no command proposal is retained even if the fixture model returns one.
10. Create an authorized scope containing `10.10.10.0/24`. Verify a proposal for
    `10.10.10.25` is in-scope, `192.0.2.10` is blocked, and substitution is
    unknown with typed confirmation.
11. Add a note and bookmark, name the session, and export a report. Verify mode
    `0600`, redacted interaction meaning and dispositions, and no raw selected
    context. Verify `/new` clears attachments from the new logical session.
12. Enable reduced motion and monochrome output and confirm the console reflects
    both. Confirm legacy popup, shell-hotkey, and tmux-binding settings still load
    but install no shell or tmux integration.
13. Run uninstall without purge. Verify the desktop launcher and installed
    package are gone while configuration and `sessions.db` remain.

Record the Kali version, VirtualBox version, desktop environment, terminal,
clipboard provider, exact commands, and observed pass/fail results below when
this procedure is executed.
