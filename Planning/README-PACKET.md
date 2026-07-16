# Kali Copilot Codex planning packet

Commit the files in this packet at the root of a new repository. The main implementation specification is:

    .agent/EXECPLAN-kali-copilot.md

`AGENTS.md` contains repository-wide rules. `.agent/PLANS.md` defines how the living plan must be maintained. `CODEX_START_HERE.md` contains the initial task to give Codex.

The target result is a clone-and-bootstrap package for fresh Kali virtual machines. Version 1 is deliberately a human-in-the-loop copilot: it can inspect bounded terminal context, explain output, review a command, and insert a proposed command into the editable prompt, but it cannot execute that command.
