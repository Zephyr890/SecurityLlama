"""Command-line interface with stable exit-code mapping."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from kali_copilot import __version__
from kali_copilot.app import ask_model, make_basic_packet
from kali_copilot.audit import AuditStore
from kali_copilot.config import ConfigError, initialize_config, load_config, update_ollama_fields
from kali_copilot.context import ContextCollector
from kali_copilot.doctor import run_doctor
from kali_copilot.install import install_shell, remove_shell_blocks
from kali_copilot.models import ShellWidgetResponse
from kali_copilot.ollama import OllamaClient, OllamaError
from kali_copilot.paths import resolve_paths
from kali_copilot.policy import assess_proposal
from kali_copilot.sanitize import redact_secrets, sanitize_for_display
from kali_copilot.scope import ScopeError, active_scope, initialize_scope, load_scope, use_scope
from kali_copilot.session import clear_session, current_session, new_session
from kali_copilot.shell_bridge import (
    ShellBridgeError,
    create_request,
    extract_response,
    read_request,
    write_response,
)
from kali_copilot.tmux import TmuxError, copy_to_buffer
from kali_copilot.ui import render_response


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="kali-copilot",
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
    popup_parser = subparsers.add_parser("popup")
    popup_parser.add_argument("--pane", required=True)
    popup_parser.add_argument("--read-only", action="store_true")
    widget_parser = subparsers.add_parser("shell-widget")
    widget_parser.add_argument("--request-file", required=True)
    widget_parser.add_argument("--response-file", required=True)
    request_parser = subparsers.add_parser("_make-widget-request")
    request_parser.add_argument("--buffer-file", required=True)
    request_parser.add_argument("--request-file", required=True)
    request_parser.add_argument("--shell", required=True)
    request_parser.add_argument("--cwd", required=True)
    request_parser.add_argument("--cursor", required=True, type=int)
    request_parser.add_argument("--pane")
    request_parser.add_argument("--last-status", type=int)
    response_parser = subparsers.add_parser("_extract-widget-response")
    response_parser.add_argument("--response-file", required=True)
    response_parser.add_argument("--command-file", required=True)
    session_parser = subparsers.add_parser("session")
    session_subparsers = session_parser.add_subparsers(dest="session_command", required=True)
    session_subparsers.add_parser("new")
    session_subparsers.add_parser("status")
    session_subparsers.add_parser("clear")
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
    subparsers.add_parser("install-shell")
    subparsers.add_parser("uninstall-shell")
    subparsers.add_parser("doctor")
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
            if args.session_command == "new":
                state = new_session()
            elif args.session_command == "clear":
                state = clear_session()
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
        if args.command == "install-shell":
            for path in install_shell():
                print(path)
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
        if args.command == "popup":
            from prompt_toolkit import prompt

            config = load_config()
            choice = prompt("Mode [1 ask, 2 explain, 3 review, 4 suggest, q quit]: ").strip()
            modes = {"1": "ask", "2": "explain", "3": "review", "4": "suggest"}
            if choice.lower() in {"q", "quit", "\x1b"}:
                return 0
            mode = modes.get(choice, "ask")
            question = prompt("Question: ").strip() or "Analyze the recent output."
            packet = ContextCollector(config).collect_tmux(args.pane, mode, question)
            response = OllamaClient(config).chat(packet)
            render_response(response)
            if response.proposed_command and args.read_only:
                assessment = assess_proposal(response, active_scope(), config.policy)
                print(assessment.model_dump_json(indent=2))
                action = prompt("Press c then Enter to copy, or Enter to close: ").strip()
                if action == "c" and assessment.insertion_allowed:
                    copy_to_buffer(response.proposed_command)
                    print("Proposal copied to tmux buffer; it was not typed or executed.")
                elif action == "c":
                    print("Copy blocked by local policy: " + "; ".join(assessment.blocked_reasons))
            return 0
        if args.command == "_make-widget-request":
            from pathlib import Path

            create_request(
                Path(args.buffer_file),
                Path(args.request_file),
                shell=args.shell,
                cwd=args.cwd,
                cursor=args.cursor,
                pane=args.pane,
                last_status=args.last_status,
            )
            return 0
        if args.command == "_extract-widget-response":
            from pathlib import Path

            print(extract_response(Path(args.response_file), Path(args.command_file)))
            return 0
        if args.command == "shell-widget":
            from pathlib import Path

            from prompt_toolkit import prompt

            request = read_request(Path(args.request_file))
            config = load_config()
            redacted_buffer = redact_secrets(sanitize_for_display(request.buffer))
            question = (
                prompt("Review question: ").strip() or "Review this command before execution."
            )
            packet = make_basic_packet(
                request.mode_hint or "review",
                question,
                "",
                current_buffer=redacted_buffer.text,
                cwd=request.cwd,
            ).model_copy(
                update={
                    "pane_id": request.tmux_pane,
                    "cursor_position": request.cursor_position,
                    "last_exit_status": request.last_exit_status,
                    "redactions": redacted_buffer.records,
                }
            )
            response = OllamaClient(config).chat(packet)
            render_response(response)
            widget_result = ShellWidgetResponse(action="none", message="No proposal selected.")
            if response.proposed_command:
                assessment = assess_proposal(response, active_scope(), config.policy)
                print(assessment.model_dump_json(indent=2))
                expected = "INSERT" if assessment.confirmation_required else "i"
                confirmation = prompt(
                    f"Type {expected} to place this command at the prompt: "
                ).strip()
                if confirmation == expected and assessment.insertion_allowed:
                    widget_result = ShellWidgetResponse(
                        action="insert", command=response.proposed_command
                    )
                elif not assessment.insertion_allowed:
                    widget_result = ShellWidgetResponse(
                        action="none",
                        message="Insertion blocked: " + "; ".join(assessment.blocked_reasons),
                    )
            write_response(Path(args.response_file), widget_result)
            return 0
        build_parser().print_help()
        return 0
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except OllamaError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except TmuxError as exc:
        print(str(exc), file=sys.stderr)
        return 6
    except ShellBridgeError as exc:
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
