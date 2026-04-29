"""SQLite-backed session and interrupt store."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import HTTPException, status

from ..domain.models import ApprovalRecord, SessionRecord, SessionMode, WorkspaceMode


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class SessionStore:
    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "workbench.sqlite3"
        self._lock = Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    cwd TEXT NOT NULL,
                    workspace_mode TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    model TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS interrupts (
                    run_id TEXT NOT NULL,
                    interrupt_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    PRIMARY KEY (run_id, interrupt_id)
                )
                """
            )

    def create_session(
        self,
        *,
        session_id: str,
        cwd: str,
        workspace_mode: WorkspaceMode,
        mode: SessionMode,
        model: str,
    ) -> SessionRecord:
        created_at = utc_now()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO sessions (id, cwd, workspace_mode, mode, model, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, cwd, workspace_mode, mode, model, created_at),
            )
        return SessionRecord(
            id=session_id,
            cwd=cwd,
            workspaceMode=workspace_mode,
            mode=mode,
            model=model,
            createdAt=created_at,
        )

    def get_session(self, session_id: str) -> SessionRecord:
        normalized_session_id = str(session_id or "").strip()
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (normalized_session_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        return SessionRecord(
            id=row["id"],
            cwd=row["cwd"],
            workspaceMode=row["workspace_mode"],
            mode=row["mode"],
            model=row["model"],
            createdAt=row["created_at"],
        )

    def create_run(self, session_id: str) -> str:
        run_id = uuid4().hex
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO runs (id, session_id, status, created_at) VALUES (?, ?, ?, ?)",
                (run_id, session_id, "running", utc_now()),
            )
        return run_id

    def finish_run(self, run_id: str, status_value: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE runs SET status = ? WHERE id = ?", (status_value, run_id))

    def create_interrupt(self, approval: ApprovalRecord) -> ApprovalRecord:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO interrupts (run_id, interrupt_id, status, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    approval.run_id,
                    approval.interrupt_id,
                    approval.status,
                    json.dumps(approval.model_dump(mode="json", by_alias=True)),
                    utc_now(),
                ),
            )
        return approval

    def decide_interrupt(self, run_id: str, interrupt_id: str, decision: str) -> ApprovalRecord:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM interrupts WHERE run_id = ? AND interrupt_id = ?",
                (run_id, interrupt_id),
            ).fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interrupt not found")
        payload = json.loads(row["payload"])
        payload["status"] = "approved" if decision == "approve" else "rejected"
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE interrupts SET status = ?, payload = ?, decided_at = ? WHERE run_id = ? AND interrupt_id = ?",
                (payload["status"], json.dumps(payload), utc_now(), run_id, interrupt_id),
            )
        return ApprovalRecord(**payload)
