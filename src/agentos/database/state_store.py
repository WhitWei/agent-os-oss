"""Workflow State Store for SOP execution persistence."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from typing import Optional
from pathlib import Path

from agentos.workflow.sop_schema import SOPRunContext

logger = logging.getLogger(__name__)

class WorkflowStateStore:
    """SQLite-based state store for serializing SOPRunContext instances.
    
    Ensures that when a workflow is suspended (e.g. for HITL approval),
    its state is persisted and can survive service restarts.
    """

    def __init__(self, db_path: str = "agent_state.db"):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            # WAL mode allows concurrent reads and writes
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sop_state (
                    run_id TEXT PRIMARY KEY,
                    sop_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def save_state(self, ctx: SOPRunContext) -> None:
        """Serialize and save the context state."""
        conn = self._get_conn()
        context_json = ctx.model_dump_json()
        with conn:
            conn.execute(
                """
                INSERT INTO sop_state (run_id, sop_id, state, context_json, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(run_id) DO UPDATE SET
                    state = excluded.state,
                    context_json = excluded.context_json,
                    updated_at = excluded.updated_at
                """,
                (ctx.run_id, ctx.sop_id, ctx.state.value, context_json),
            )
        logger.debug("[StateStore] Saved state for run_id=%s, state=%s", ctx.run_id, ctx.state.value)

    def load_state(self, run_id: str) -> Optional[SOPRunContext]:
        """Load and deserialize a context state by run_id."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT context_json FROM sop_state WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        if not row:
            return None
        
        try:
            return SOPRunContext.model_validate_json(row["context_json"])
        except Exception as exc:
            logger.error("[StateStore] Failed to deserialize context for run_id=%s: %s", run_id, exc)
            return None

    def count_by_state(self, state: str) -> int:
        """Count workflow runs by state."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sop_state WHERE state = ?", (state,))
        row = cursor.fetchone()
        return row[0] if row else 0

    def list_runs(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """List workflow runs with pagination."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT run_id, sop_id, state, updated_at FROM sop_state ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        )
        return [dict(row) for row in cursor.fetchall()]
