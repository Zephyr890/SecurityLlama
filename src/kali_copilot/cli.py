"""Command-line interface with stable exit-code mapping."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections.abc import Sequence

from kali_copilot import __version__
from kali_copilot.app import ask_model
from kali_copilot.audit import AuditStore
from kali_copilot.config import (
    AppConfig,
    ConfigError,
    initialize_config,
    load_config,
    update_ollama_fields,
    update_tunnel_fields,
)
from kali_copilot.doctor import run_doctor
from kali_copilot.install import (
    InstallError,
    install_desktop,
    remove_desktop,
    remove_shell_blocks,
)
from kali_copilot.ollama import InvalidModelResponseError, OllamaError
from kali_copilot.paths import resolve_paths
from kali_copilot.reporting import json_report, markdown_report
from kali_copilot.sanitize import redact_secrets, sanitize_for_display
from kali_copilot.scope import ScopeError, active_scope, initialize_scope, load_scope, use_scope
from kali_copilot.session import clear_session, current_session
from kali_copilot.ui import render_response


def _ask_with_default(prompt_text: str, default: str) -> str:
    """Read a setup answer while showing the selected default."""
    answer = input(f"{prompt_text} [{default}]: ").strip()
    return answer or default


def _run_setup() -> int:
    """Interactively configure Ollama and install the desktop console launcher."""
    try:
        config = load_config()
    except ConfigError:
        initialize_config()
        config = load_config()
    print("SecurityLlama setup")
    print("Press Enter to accept a default. The SSH tunnel must already be running.\n")
    base_url = _ask_with_default("Ollama URL", config.ollama.base_url)
    model = _ask_with_default("Model", config.ollama.model)
    default_think = "y" if config.ollama.think else "n"
    think_answer = _ask_with_default("Enable extended thinking? (y/n)", default_think)
    think = think_answer.lower() in {"y", "yes"}
    path = update_ollama_fields(base_url=base_url, model=model, think=think)
    tunnel_user = _ask_with_default("Mac SSH username", config.tunnel.ssh_user or "admin")
    tunnel_host = _ask_with_default("Mac host-only IP", config.tunnel.ssh_host or "192.168.56.100")
    update_tunnel_fields(ssh_user=tunnel_user, ssh_host=tunnel_host)
    print(f"Configuration saved to {path}")
    installed = install_desktop()
    print(f"Installed console launcher: {installed}")
    print("\nChecking the setup...")
    checks = run_doctor()
    for check in checks:
        status = "PASS" if check.passed else ("WARN" if not check.required else "FAIL")
        print(f"[{status}] {check.name}: {check.message}")
    print("\nStart the Ollama tunnel in a separate Kali terminal:")
    print(_tunnel_command(load_config()))
    return 0 if all(check.passed or not check.required for check in checks) else 2


def _tunnel_command(config: AppConfig) -> str:
    """Render the configured SSH forward without executing it."""
    tunnel = config.tunnel
    if not tunnel.ssh_user or not tunnel.ssh_host:
        raise ConfigError("run `securityllama setup` to configure the SSH tunnel first")
    args = [
        "ssh",
        "-N",
        "-o",
        "ExitOnForwardFailure=yes",
        "-L",
        f"127.0.0.1:{tunnel.local_port}:{tunnel.remote_host}:{tunnel.remote_port}",
        f"{tunnel.ssh_user}@{tunnel.ssh_host}",
    ]
    return shlex.join(args)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="securityllama",
        description="Human-in-the-loop terminal copilot (never executes model commands).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--debug", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    for mode in ("ask", "explain", "review", "suggest"):
        mode_parser = subparsers.add_parser(mode)
        mode_parser.add_argument("question", nargs="?", default="")
    config_parser = subparsers.add_parser("config")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    config_init = config_subparsers.add_parser("init")
    config_init.add_argument("--ollama-url")
    config_init.add_argument("--model")
    config_subparsers.add_parser("show")
    session_parser = subparsers.add_parser("session")
    session_subparsers = session_parser.add_subparsers(dest="session_command", required=True)
    session_subparsers.add_parser("new")
    session_subparsers.add_parser("status")
    session_subparsers.add_parser("clear")
    session_name = session_subparsers.add_parser("name")
    session_name.add_argument("name")
    scope_parser = subparsers.add_parser("scope")
    scope_subparsers = scope_parser.add_subparsers(dest="scope_command", required=True)
    scope_init = scope_subparsers.add_parser("init")
    scope_init.add_argument("name")
    scope_init.add_argument("--authorized", action="store_true")
    scope_use = scope_subparsers.add_parser("use")
    scope_use.add_argument("name")
    scope_show = scope_subparsers.add_parser("show")
    scope_show.add_argument("name", nargs="?")
    history_parser = subparsers.add_parser("history")
    history_parser.add_argument("--limit", type=int, default=20)
    subparsers.add_parser("console", help="run the standalone interactive terminal console")
    subparsers.add_parser("chat", help="compatibility alias for console")
    note_parser = subparsers.add_parser("note", help="add a redacted operator note")
    note_parser.add_argument("text")
    note_parser.add_argument("--bookmark", action="store_true")
    report_parser = subparsers.add_parser("report", help="export the current redacted session")
    report_parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    report_parser.add_argument("--output")
    subparsers.add_parser("install-desktop")
    subparsers.add_parser("uninstall-desktop")
    subparsers.add_parser("install-shell", help="deprecated alias for install-desktop")
    subparsers.add_parser("uninstall-shell")
    subparsers.add_parser("doctor")
    subparsers.add_parser("setup", help="configure Ollama and install the console launcher")
    tunnel_parser = subparsers.add_parser("tunnel", help="show the configured Ollama SSH tunnel")
    tunnel_subparsers = tunnel_parser.add_subparsers(dest="tunnel_command", required=True)
    tunnel_subparsers.add_parser("command", help="print the SSH tunnel command")
    subparsers.add_parser("redact")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "config":
            if args.config_command == "init":
                if args.ollama_url or args.model:
                    print(update_ollama_fields(base_url=args.ollama_url, model=args.model))
                else:
                    print(initialize_config())
            else:
                print(json.dumps(load_config().model_dump(mode="json"), indent=2, sort_keys=True))
            return 0
        if args.command == "session":
            if args.session_command == "new" or args.session_command == "clear":
                state = clear_session()
            elif args.session_command == "name":
                state = current_session()
                with AuditStore(resolve_paths().database_file) as store:
                    store.name_session(state.session_id, args.name)
            else:
                state = current_session()
            print(state.session_id)
            return 0
        if args.command == "scope":
            if args.scope_command == "init":
                print(initialize_scope(args.name, args.authorized))
            elif args.scope_command == "use":
                print(use_scope(args.name).model_dump_json(indent=2))
            else:
                scope = load_scope(args.name) if args.name else active_scope()
                print(scope.model_dump_json(indent=2) if scope else "No active scope.")
            return 0
        if args.command == "history":
            with AuditStore(resolve_paths().database_file) as store:
                for item in store.history(max(1, min(args.limit, 100))):
                    print(json.dumps(item, sort_keys=True))
            return 0
        if args.command == "note":
            state = current_session()
            safe_note = redact_secrets(sanitize_for_display(args.text)).text
            with AuditStore(resolve_paths().database_file) as store:
                print(store.add_note(state.session_id, safe_note, bookmarked=args.bookmark))
            return 0
        if args.command == "report":
            from pathlib import Path

            state = current_session()
            with AuditStore(resolve_paths().database_file) as store:
                content = (
                    markdown_report(store, state.session_id)
                    if args.format == "markdown"
                    else json_report(store, state.session_id)
                )
            if args.output:
                output = Path(args.output).expanduser().resolve()
                output.write_text(content, encoding="utf-8")
                output.chmod(0o600)
                print(output)
            else:
                print(content)
            return 0
        if args.command in {"console", "chat"}:
            from kali_copilot.console import SecurityLlamaConsole

            return SecurityLlamaConsole(load_config()).run()
        if args.command in {"install-desktop", "install-shell"}:
            print(install_desktop())
            if args.command == "install-shell":
                print("install-shell is retired; installed the standalone console launcher.")
            print("Launch it from the Kali application menu or run: securityllama console")
            return 0
        if args.command == "uninstall-desktop":
            remove_desktop()
            return 0
        if args.command == "uninstall-shell":
            remove_shell_blocks()
            return 0
        if args.command == "doctor":
            checks = run_doctor()
            for check in checks:
                status = "PASS" if check.passed else ("WARN" if not check.required else "FAIL")
                print(f"[{status}] {check.name}: {check.message}")
            return 0 if all(check.passed or not check.required for check in checks) else 2
        if args.command == "setup":
            return _run_setup()
        if args.command == "tunnel":
            if args.tunnel_command == "command":
                print(_tunnel_command(load_config()))
            return 0
        if args.command == "redact":
            redact_result = redact_secrets(sanitize_for_display(sys.stdin.read()))
            sys.stdout.write(redact_result.text)
            if redact_result.records:
                summary = ", ".join(
                    f"{item.category}={item.count}" for item in redact_result.records
                )
                print(f"\nRedactions: {summary}", file=sys.stderr)
            return 0
        if args.command in {"ask", "explain", "review", "suggest"}:
            config = load_config()
            question = str(args.question).strip()
            if not question:
                question = "Analyze the supplied context."
            if len(question) > config.context.max_question_chars:
                raise ConfigError("question exceeds context.max_question_chars")
            recent_output = (
                "" if sys.stdin.isatty() else sys.stdin.read(config.context.max_capture_bytes + 1)
            )
            if len(recent_output.encode("utf-8")) > config.context.max_capture_bytes:
                recent_output = recent_output.encode("utf-8")[
                    -config.context.max_capture_bytes :
                ].decode("utf-8", errors="replace")
            response = ask_model(config, args.command, question, recent_output)
            render_response(response)
            return 0
        build_parser().print_help()
        return 0
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except OllamaError as exc:
        print(str(exc), file=sys.stderr)
        if getattr(args, "debug", False) and isinstance(exc, InvalidModelResponseError):
            print(exc.debug_report(), file=sys.stderr)
        return exc.exit_code
    except InstallError as exc:
        print(str(exc), file=sys.stderr)
        return 6
    except ScopeError as exc:
        print(f"scope error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI must suppress tracebacks by default
        if getattr(args, "debug", False):
            raise
        print(f"unexpected error: {exc}", file=sys.stderr)
        return 10
