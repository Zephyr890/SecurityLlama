"""Privacy-preserving SQLite audit and bounded conversation memory."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from kali_copilot.models import AssistantResponse, ContextPacket, ConversationTurn, PolicyAssessment
from kali_copilot.paths import ensure_private_directory

SCHEMA_VERSION = 1


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
                PRAGMA user_version = 1;
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
        turns = [
            ConversationTurn(
                question=str(question),
                answer=AssistantResponse.model_validate_json(response_json).answer,
            )
            for question, response_json in reversed(rows)
        ]
        return turns

    def history(self, limit: int = 20) -> list[dict[str, object]]:
        cursor = self.connection.execute(
            "SELECT id, created_at, mode, question, proposed_command, disposition "
            "FROM interactions ORDER BY created_at DESC LIMIT ?",
            (limit,),
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
