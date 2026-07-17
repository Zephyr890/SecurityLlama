"""Persistent multi-turn operator cockpit for tmux."""

from __future__ import annotations

import difflib
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic
from types import TracebackType

from prompt_toolkit import prompt
from rich.console import Console
from rich.panel import Panel
from rich.status import Status
from rich.table import Table

from kali_copilot.attachments import (
    AttachmentBundle,
    AttachmentError,
    attach_file,
    clear_attachments,
    detach_file,
    load_attachment_state,
    merge_redactions,
    read_attachments,
)
from kali_copilot.audit import AuditStore
from kali_copilot.config import AppConfig, ModelProfile
from kali_copilot.context import ContextCollector
from kali_copilot.models import AssistantResponse, ContextPacket, PolicyAssessment
from kali_copilot.ollama import OllamaClient, OllamaError
from kali_copilot.paths import resolve_paths
from kali_copilot.policy import assess_proposal
from kali_copilot.prompting import chat_messages
from kali_copilot.proposal import stage_proposal
from kali_copilot.reporting import markdown_report
from kali_copilot.sanitize import (
    redact_secrets,
    sanitize_for_display,
    strip_terminal_sequences,
    truncate_text,
)
from kali_copilot.scope import active_scope
from kali_copilot.session import clear_session, current_session
from kali_copilot.tmux import copy_to_buffer, validate_pane_id
from kali_copilot.ui import render_response

HELP = """Cockpit commands
  /help                         show this help
  /mode ask|explain|review|suggest
  /context                      inspect the next model request
  /status                       check endpoint, model, scope, and session
  /include terminal|memory|scope on|off
  /attach PATH                   attach a text file to this session
  /attachments                   list session attachments
  /detach PATH|all               remove session attachments
  /profile NAME                 select a configured model profile
  /proposals, /next, /prev      inspect and select proposals
  /diff TEXT                    compare selected proposal with TEXT
  /insert                       stage selected proposal for Alt-I in its shell
  /copy                         copy selected proposal to the tmux paste buffer
  /reject                       mark selected proposal rejected
  /alternative [instruction]    request another proposal
  /note TEXT, /bookmark TEXT    add an operator note
  /name TEXT                    name the current session
  /report PATH                  export a redacted Markdown report
  /new                          begin a new logical session
  /clear                        clear the screen (does not erase audits)
  /quit                         close the cockpit

Ctrl-C cancels the current wait when supported by the HTTP transport. No command
is executed by the cockpit. Alt-I in the originating shell retrieves staged text.
"""


@dataclass
class ProposalItem:
    response: AssistantResponse
    assessment: PolicyAssessment
    interaction_id: str | None


@dataclass
class CockpitState:
    pane_id: str
    mode: str = "ask"
    include_terminal: bool = True
    include_memory: bool = True
    include_scope: bool = True
    profile_name: str = "fast"
    proposals: list[ProposalItem] = field(default_factory=list)
    selected: int = -1
    last_question: str = ""


class RequestProgress:
    """Render request phase and elapsed time without touching the shell prompt."""

    def __init__(self, console: Console, *, reduced_motion: bool) -> None:
        self.console = console
        self.reduced_motion = reduced_motion
        self.started = 0.0
        self._phase = "capturing context"
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._status: Status | None = None

    def __enter__(self) -> RequestProgress:
        self.started = monotonic()
        if self.reduced_motion:
            self.console.print(self._phase)
            return self
        self._status = self.console.status(self._phase, spinner="dots")
        self._status.start()
        self._thread = Thread(target=self._refresh, daemon=True)
        self._thread.start()
        return self

    def _refresh(self) -> None:
        while not self._stop.wait(0.1):
            with self._lock:
                phase = self._phase
            if self._status:
                self._status.update(f"{phase} · {monotonic() - self.started:.1f}s · Ctrl-C cancels")

    def phase(self, value: str) -> None:
        with self._lock:
            self._phase = value
        if self.reduced_motion:
            self.console.print(value)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.5)
        if self._status:
            self._status.stop()


def _profiled_config(config: AppConfig, profile: ModelProfile) -> AppConfig:
    return config.model_copy(
        update={
            "ollama": config.ollama.model_copy(
                update={
                    "think": profile.think,
                    "num_ctx": profile.num_ctx,
                    "num_predict": profile.num_predict,
                    "temperature": profile.temperature,
                }
            )
        }
    )


def _safe_response(response: AssistantResponse) -> AssistantResponse:
    def clean(value: str) -> str:
        return redact_secrets(strip_terminal_sequences(value)).text

    return response.model_copy(
        update={
            "answer": clean(response.answer),
            "proposed_command": clean(response.proposed_command or "") or None,
            "command_explanation": clean(response.command_explanation or "") or None,
            "warnings": [clean(item) for item in response.warnings],
            "findings": [clean(item) for item in response.findings],
            "assumptions": [clean(item) for item in response.assumptions],
        }
    )


def context_usage(packet: ContextPacket, config: AppConfig) -> dict[str, int | bool]:
    """Return a transparent approximation; exact tokenization is model-specific."""
    messages = chat_messages(packet)
    message_chars = sum(len(item["content"]) for item in messages)
    estimated_tokens = max(1, (message_chars + 3) // 4)
    return {
        "capacity": config.ollama.num_ctx,
        "reserved_response": config.ollama.num_predict,
        "estimated_request": estimated_tokens,
        "estimated_percent": round(estimated_tokens * 100 / config.ollama.num_ctx),
        "question_chars": len(packet.question),
        "terminal_chars": len(packet.recent_output),
        "buffer_chars": len(packet.current_buffer or ""),
        "memory_turns": len(packet.recent_turns),
        "redactions": sum(record.count for record in packet.redactions),
        "truncated": packet.capture_truncated,
    }


class Cockpit:
    def __init__(self, config: AppConfig, pane_id: str, *, console: Console | None = None) -> None:
        self.base_config = config
        self.state = CockpitState(validate_pane_id(pane_id))
        self.console = console or Console(no_color=config.ui.monochrome)
        self.paths = resolve_paths()
        self._last_attachments = AttachmentBundle("", [], [], False, 0)
        self._last_terminal_chars = 0

    @property
    def config(self) -> AppConfig:
        profile = self.base_config.profiles.get(self.state.profile_name)
        return _profiled_config(self.base_config, profile) if profile else self.base_config

    def _packet(self, question: str) -> ContextPacket:
        safe_question = redact_secrets(strip_terminal_sequences(question))
        if self.state.include_terminal:
            packet = ContextCollector(self.config).collect_tmux(
                self.state.pane_id, self.state.mode, safe_question.text
            )
        else:
            from kali_copilot.app import make_basic_packet

            packet = make_basic_packet(self.state.mode, safe_question.text, "")
            packet = packet.model_copy(update={"pane_id": self.state.pane_id, "redactions": []})
        packet = packet.model_copy(update={"session_id": current_session(self.paths).session_id})
        self._last_terminal_chars = len(packet.recent_output)
        self._last_attachments = read_attachments(
            packet.session_id,
            max_file_bytes=self.config.context.max_attachment_file_bytes,
            paths=self.paths,
        )
        combined_sections = []
        if packet.recent_output:
            combined_sections.append("TERMINAL_CONTEXT_BEGIN\n" + packet.recent_output)
        if self._last_attachments.text:
            combined_sections.append(self._last_attachments.text)
        combined = truncate_text(
            "\n\n".join(combined_sections),
            self.config.context.max_capture_lines,
            self.config.context.max_capture_bytes,
        )
        updates: dict[str, object] = {}
        updates["recent_output"] = combined.text
        updates["capture_truncated"] = (
            packet.capture_truncated or self._last_attachments.truncated or combined.truncated
        )
        updates["redactions"] = merge_redactions(
            [*packet.redactions, *safe_question.records, *self._last_attachments.redactions]
        )
        scope = active_scope(self.paths) if self.state.include_scope else None
        updates["active_scope"] = scope.summary() if scope else None
        if self.state.include_memory and self.config.audit.enabled:
            with AuditStore(self.paths.database_file) as store:
                updates["recent_turns"] = store.recent_turns(
                    packet.session_id, self.config.context.recent_turns
                )
        else:
            updates["recent_turns"] = []
        return packet.model_copy(update=updates)

    def _header(self) -> None:
        session = current_session(self.paths).session_id
        with AuditStore(self.paths.database_file) as store:
            name = store.session_name(session)
        title = f"SecurityLlama cockpit — {name or session[:10]}"
        subtitle = (
            f"pane {self.state.pane_id} · mode {self.state.mode} · "
            f"profile {self.state.profile_name} · model {self.config.ollama.model}"
        )
        attachments = load_attachment_state(session, self.paths).attachments
        if attachments:
            subtitle += f" · {len(attachments)} attached"
        self.console.print(Panel(subtitle, title=title, border_style="cyan"))
        self.console.print("Type a question or /help. Proposals are never executed.", style="dim")
        if self.config.audit.enabled:
            with AuditStore(self.paths.database_file) as store:
                turns = store.recent_turns(session, min(3, self.config.context.recent_turns))
            for turn in turns:
                self.console.print(f"\nYou: {sanitize_for_display(turn.question)}", style="bold")
                self.console.print(sanitize_for_display(turn.answer))

    def _show_context(self, packet: ContextPacket) -> None:
        usage = context_usage(packet, self.config)
        table = Table(title="Next request context (estimated tokens)", show_header=False)
        rows = (
            ("Capacity", f"{usage['capacity']} tokens"),
            ("Estimated request", f"{usage['estimated_request']} ({usage['estimated_percent']}%)"),
            ("Reserved response", str(usage["reserved_response"])),
            ("Question", f"{usage['question_chars']} chars"),
            ("Terminal capture", f"{self._last_terminal_chars} chars"),
            ("Attached files", str(len(self._last_attachments.attachments))),
            ("Attachment source", f"{self._last_attachments.original_bytes} bytes"),
            ("Attachment context", f"{len(self._last_attachments.text)} chars before total bound"),
            ("Editable buffer", f"{usage['buffer_chars']} chars"),
            ("Conversation memory", f"{usage['memory_turns']} turns"),
            ("Redactions", str(usage["redactions"])),
            ("Capture truncated", str(usage["truncated"]).lower()),
            ("Scope included", str(packet.active_scope is not None).lower()),
        )
        for label, value in rows:
            table.add_row(label, value)
        self.console.print(table)

    def _selected(self) -> ProposalItem | None:
        if 0 <= self.state.selected < len(self.state.proposals):
            return self.state.proposals[self.state.selected]
        return None

    def _show_proposal(self) -> None:
        item = self._selected()
        if item is None:
            self.console.print("No proposal selected.")
            return
        self.console.print(
            Panel(
                sanitize_for_display(item.response.proposed_command or ""),
                title=(
                    f"Proposal {self.state.selected + 1}/{len(self.state.proposals)} — NOT EXECUTED"
                ),
                border_style="cyan",
            )
        )
        self.console.print(
            f"Risk {item.assessment.risk_status} · scope {item.assessment.scope_status} · "
            f"insertion {'allowed' if item.assessment.insertion_allowed else 'blocked'}"
        )
        for reason in item.assessment.blocked_reasons:
            self.console.print(f"  - {sanitize_for_display(reason)}", style="yellow")

    def _ask(self, question: str) -> None:
        if len(question) > self.config.context.max_question_chars:
            self.console.print(
                f"Question exceeds the {self.config.context.max_question_chars}-character limit.",
                style="red",
            )
            return
        self.state.last_question = question
        packet: ContextPacket
        try:
            with RequestProgress(
                self.console, reduced_motion=self.config.ui.reduced_motion
            ) as progress:
                packet = self._packet(question)
                progress.phase(f"waiting for {self.config.ollama.model}")
                response = OllamaClient(self.config).chat(packet)
                progress.phase("checking local scope and risk policy")
                assessment = assess_proposal(response, active_scope(self.paths), self.config.policy)
            interaction_id = None
            if self.config.audit.enabled:
                from urllib.parse import urlsplit

                with AuditStore(self.paths.database_file) as store:
                    interaction_id = store.record(
                        packet,
                        _safe_response(response),
                        assessment,
                        endpoint_host=urlsplit(self.config.ollama.base_url).hostname or "unknown",
                        model=self.config.ollama.model,
                    )
            render_response(response, console=self.console)
            if response.proposed_command:
                self.state.proposals.append(ProposalItem(response, assessment, interaction_id))
                self.state.selected = len(self.state.proposals) - 1
                self._show_proposal()
            if self.config.ui.completion_bell:
                sys.stdout.write("\a")
                sys.stdout.flush()
        except KeyboardInterrupt:
            self.console.print("Request cancelled; no proposal was staged.", style="yellow")
        except OllamaError as exc:
            self.console.print(f"Request failed: {sanitize_for_display(str(exc))}", style="red")
        except AttachmentError as exc:
            self.console.print(f"Attachment error: {sanitize_for_display(str(exc))}", style="red")

    def _set_disposition(self, item: ProposalItem, value: str) -> None:
        if item.interaction_id and self.config.audit.enabled:
            with AuditStore(self.paths.database_file) as store:
                store.update_disposition(item.interaction_id, value)

    def _stage(self) -> None:
        item = self._selected()
        if item is None:
            self.console.print("No proposal selected.")
            return
        pending = stage_proposal(
            item.response,
            item.assessment,
            session_id=current_session(self.paths).session_id,
            pane_id=self.state.pane_id,
            ttl_seconds=self.config.ui.proposal_ttl_seconds,
            interaction_id=item.interaction_id,
            paths=self.paths,
        )
        self._set_disposition(item, "staged")
        self.console.print(
            f"Proposal staged until {pending.expires_at.isoformat()}. Focus pane "
            f"{self.state.pane_id} and press Alt-I; it will not execute."
        )

    def _handle(self, line: str) -> bool:
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            self.console.print(f"Invalid command: {exc}", style="red")
            return True
        command = parts[0].lower()
        args = parts[1:]
        if command in {"/quit", "/q"}:
            return False
        if command == "/help":
            self.console.print(HELP)
        elif command == "/clear":
            self.console.clear()
            self._header()
        elif command == "/mode" and args and args[0] in {"ask", "explain", "review", "suggest"}:
            self.state.mode = args[0]
            self.console.print(f"Mode: {args[0]}")
        elif command == "/profile" and args:
            if args[0] not in self.base_config.profiles:
                self.console.print("Available profiles: " + ", ".join(self.base_config.profiles))
            else:
                self.state.profile_name = args[0]
                self.console.print(f"Profile: {args[0]}")
        elif command == "/include" and len(args) == 2:
            mapping = {
                "terminal": "include_terminal",
                "memory": "include_memory",
                "scope": "include_scope",
            }
            if args[0] not in mapping or args[1] not in {"on", "off"}:
                self.console.print("Usage: /include terminal|memory|scope on|off")
            else:
                setattr(self.state, mapping[args[0]], args[1] == "on")
        elif command == "/attach" and len(args) == 1:
            reference = attach_file(
                current_session(self.paths).session_id,
                args[0],
                max_files=self.config.context.max_attachment_files,
                max_file_bytes=self.config.context.max_attachment_file_bytes,
                paths=self.paths,
            )
            self.console.print(f"Attached for this session: {sanitize_for_display(reference.path)}")
        elif command == "/attachments":
            attachment_state = load_attachment_state(
                current_session(self.paths).session_id, self.paths
            )
            if not attachment_state.attachments:
                self.console.print("No files are attached to this session.")
            for index, reference in enumerate(attachment_state.attachments, start=1):
                self.console.print(
                    f"{index}. {sanitize_for_display(reference.path)} "
                    f"(added {reference.added_at.isoformat()})"
                )
        elif command == "/detach" and len(args) == 1:
            session_id = current_session(self.paths).session_id
            if args[0].lower() == "all":
                count = clear_attachments(session_id, self.paths)
                self.console.print(f"Detached {count} file(s) from this session.")
            elif detach_file(session_id, args[0], self.paths):
                self.console.print(f"Detached: {sanitize_for_display(args[0])}")
            else:
                self.console.print("That file is not attached to this session.")
        elif command == "/context":
            self._show_context(
                self._packet(self.state.last_question or "Analyze the recent output.")
            )
        elif command == "/status":
            health = OllamaClient(self.config).check_health()
            scope = active_scope(self.paths)
            self.console.print(
                f"Endpoint: {'reachable' if health.reachable else 'unavailable'} — "
                f"{sanitize_for_display(health.message)}"
            )
            self.console.print(f"Model: {self.config.ollama.model}")
            self.console.print(f"Scope: {scope.name if scope else 'none active'} (advisory)")
            self.console.print(f"Session: {current_session(self.paths).session_id}")
            attachments = load_attachment_state(
                current_session(self.paths).session_id, self.paths
            ).attachments
            self.console.print(f"Attachments: {len(attachments)}")
        elif command == "/proposals":
            self._show_proposal()
        elif command in {"/next", "/prev"}:
            if self.state.proposals:
                delta = 1 if command == "/next" else -1
                self.state.selected = (self.state.selected + delta) % len(self.state.proposals)
            self._show_proposal()
        elif command == "/diff":
            item = self._selected()
            if item and item.response.proposed_command is not None:
                before = " ".join(args)
                diff = difflib.ndiff([before], [item.response.proposed_command])
                self.console.print("\n".join(diff))
            else:
                self.console.print("No proposal selected.")
        elif command == "/insert":
            self._stage()
        elif command == "/copy":
            item = self._selected()
            if item and item.assessment.insertion_allowed and item.response.proposed_command:
                copy_to_buffer(item.response.proposed_command)
                self._set_disposition(item, "copied")
                self.console.print("Copied to tmux buffer; not typed or executed.")
            else:
                self.console.print("No eligible proposal selected.")
        elif command == "/reject":
            item = self._selected()
            if item:
                self._set_disposition(item, "rejected")
                self.console.print("Proposal marked rejected.")
        elif command == "/alternative":
            instruction = " ".join(args) or "Provide a lower-impact alternative."
            self._ask(f"{self.state.last_question}\n\n{instruction}".strip())
        elif command in {"/note", "/bookmark"} and args:
            safe_note = redact_secrets(strip_terminal_sequences(" ".join(args))).text
            with AuditStore(self.paths.database_file) as store:
                store.add_note(
                    current_session(self.paths).session_id,
                    safe_note,
                    bookmarked=command == "/bookmark",
                )
            self.console.print("Operator note saved (redacted input is recommended).")
        elif command == "/name" and args:
            with AuditStore(self.paths.database_file) as store:
                store.name_session(current_session(self.paths).session_id, " ".join(args))
            self.console.print("Session named.")
        elif command == "/report" and args:
            target = Path(args[0]).expanduser().resolve()
            with AuditStore(self.paths.database_file) as store:
                content = markdown_report(store, current_session(self.paths).session_id)
            target.write_text(content, encoding="utf-8")
            target.chmod(0o600)
            self.console.print(f"Redacted report written to {target}")
        elif command == "/new":
            session_state = clear_session(self.paths)
            self.state.proposals.clear()
            self.state.selected = -1
            self.console.print(f"New session: {session_state.session_id}")
        else:
            self.console.print("Unknown cockpit command. Use /help.")
        return True

    def run(self) -> int:
        self._header()
        while True:
            try:
                line = prompt("securityllama> ").strip()
            except (EOFError, KeyboardInterrupt):
                self.console.print("Closing cockpit.")
                return 0
            if not line:
                continue
            if line.startswith("/"):
                try:
                    if not self._handle(line):
                        return 0
                except AttachmentError as exc:
                    self.console.print(
                        f"Attachment error: {sanitize_for_display(str(exc))}", style="red"
                    )
            else:
                self._ask(line)
