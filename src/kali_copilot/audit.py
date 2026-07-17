"""Privacy-preserving SQLite audit and bounded conversation memory."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from kali_copilot.models import AssistantResponse, ContextPacket, ConversationTurn, PolicyAssessment
from kali_copilot.paths import ensure_private_directory

SCHEMA_VERSION = 2


def _response_memory(response: AssistantResponse) -> str:
    """Serialize bounded response meaning for follow-ups without raw context."""
    sections = [response.answer]
    if response.findings:
        sections.append(
            "Ranked findings:\n"
            + "\n".join(
                f"{index}. {finding}" for index, finding in enumerate(response.findings, start=1)
            )
        )
    if response.assumptions:
        sections.append("Assumptions:\n" + "\n".join(f"- {item}" for item in response.assumptions))
    if response.warnings:
        sections.append("Warnings:\n" + "\n".join(f"- {item}" for item in response.warnings))
    return "\n\n".join(sections)[:12000]


class AuditStore:
    def __init__(self, path: Path) -> None:
        ensure_private_directory(path.parent)
        self.path = path
        self.connection = sqlite3.connect(path)
        path.chmod(0o600)
        self._migrate()

    def _migrate(self) -> None:
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError("audit database was created by a newer securityllama version")
        if version == 0:
            self.connection.executescript(
                """
                CREATE TABLE interactions (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    cwd TEXT NOT NULL,
                    question TEXT NOT NULL,
                    context_sha256 TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    proposed_command TEXT,
                    policy_json TEXT,
                    disposition TEXT NOT NULL DEFAULT 'none',
                    endpoint_host TEXT NOT NULL,
                    model TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    error_code INTEGER
                );
                CREATE INDEX interactions_session_time ON interactions(session_id, created_at);
                CREATE TABLE session_summaries (
                    session_id TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE session_metadata (
                    session_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE session_notes (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    body TEXT NOT NULL,
                    bookmarked INTEGER NOT NULL DEFAULT 0
                );
                PRAGMA user_version = 2;
                """
            )
            self.connection.commit()
        elif version == 1:
            self.connection.executescript(
                """
                CREATE TABLE session_metadata (
                    session_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE session_notes (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    body TEXT NOT NULL,
                    bookmarked INTEGER NOT NULL DEFAULT 0
                );
                PRAGMA user_version = 2;
                """
            )
            self.connection.commit()

    def record(
        self,
        packet: ContextPacket,
        response: AssistantResponse,
        policy: PolicyAssessment | None,
        *,
        endpoint_host: str,
        model: str,
        duration_ms: int = 0,
        disposition: str = "none",
    ) -> str:
        interaction_id = uuid.uuid4().hex
        packet_json = packet.model_dump_json()
        self.connection.execute(
            """INSERT INTO interactions
            (id, session_id, created_at, mode, cwd, question, context_sha256,
             response_json, proposed_command, policy_json, disposition,
             endpoint_host, model, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                interaction_id,
                packet.session_id,
                packet.timestamp.isoformat(),
                packet.mode,
                packet.cwd,
                packet.question,
                hashlib.sha256(packet_json.encode()).hexdigest(),
                response.model_dump_json(),
                response.proposed_command,
                policy.model_dump_json() if policy else None,
                disposition,
                endpoint_host,
                model,
                duration_ms,
            ),
        )
        self.connection.commit()
        return interaction_id

    def recent_turns(self, session_id: str, limit: int) -> list[ConversationTurn]:
        rows = self.connection.execute(
            "SELECT question, response_json FROM interactions WHERE session_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        turns = []
        for question, response_json in reversed(rows):
            response = AssistantResponse.model_validate_json(response_json)
            turns.append(
                ConversationTurn(question=str(question), answer=_response_memory(response))
            )
        return turns

    def history(self, limit: int = 20) -> list[dict[str, object]]:
        cursor = self.connection.execute(
            "SELECT id, created_at, mode, question, proposed_command, disposition "
            "FROM interactions ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def session_history(self, session_id: str, limit: int = 100) -> list[dict[str, object]]:
        cursor = self.connection.execute(
            "SELECT id, created_at, mode, question, response_json, proposed_command, "
            "policy_json, disposition FROM interactions WHERE session_id=? "
            "ORDER BY created_at ASC LIMIT ?",
            (session_id, limit),
        )
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def update_disposition(self, interaction_id: str, disposition: str) -> None:
        """Record an operator action without changing the proposal text."""
        if disposition not in {"none", "staged", "inserted", "copied", "rejected", "expired"}:
            raise ValueError("invalid proposal disposition")
        self.connection.execute(
            "UPDATE interactions SET disposition=? WHERE id=?", (disposition, interaction_id)
        )
        self.connection.commit()

    def name_session(self, session_id: str, name: str) -> None:
        cleaned = name.strip()[:128]
        if not cleaned:
            raise ValueError("session name cannot be empty")
        now = datetime.now(UTC).isoformat()
        self.connection.execute(
            "INSERT INTO session_metadata(session_id, name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET "
            "name=excluded.name, updated_at=excluded.updated_at",
            (session_id, cleaned, now, now),
        )
        self.connection.commit()

    def session_name(self, session_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT name FROM session_metadata WHERE session_id=?", (session_id,)
        ).fetchone()
        return str(row[0]) if row else None

    def add_note(self, session_id: str, body: str, *, bookmarked: bool = False) -> str:
        cleaned = body.strip()[:12000]
        if not cleaned:
            raise ValueError("note cannot be empty")
        note_id = uuid.uuid4().hex
        self.connection.execute(
            "INSERT INTO session_notes(id, session_id, created_at, body, bookmarked) "
            "VALUES (?, ?, ?, ?, ?)",
            (note_id, session_id, datetime.now(UTC).isoformat(), cleaned, int(bookmarked)),
        )
        self.connection.commit()
        return note_id

    def notes(self, session_id: str) -> list[dict[str, object]]:
        cursor = self.connection.execute(
            "SELECT id, created_at, body, bookmarked FROM session_notes "
            "WHERE session_id=? ORDER BY created_at ASC",
            (session_id,),
        )
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def purge_expired(self, retention_days: int, current_session: str) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        cursor = self.connection.execute(
            "DELETE FROM interactions WHERE created_at < ? AND session_id != ?",
            (cutoff, current_session),
        )
        self.connection.commit()
        return cursor.rowcount

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> AuditStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
