"""SQLite 持久化层 — agent_feedback 表。

存储人机交互审批结果，供事后审计、RL 反馈训练和 Langfuse 关联使用。

表 Schema (agent_feedback)：
    trace_id              TEXT PRIMARY KEY  — Langfuse / OTel trace ID
    reviewer              TEXT NOT NULL     — 审批人的用户 ID (Feishu open_id)
    decision              TEXT NOT NULL     — 'APPROVED' | 'REJECTED'
    reason                TEXT              — 审批意见文本（可空）
    original_agent_output TEXT              — Agent 提出的原始动作 JSON 字符串
    timestamp             TEXT NOT NULL     — ISO-8601 UTC 时间戳

用法：
    from agentos.database.feedback_db import FeedbackDB, init_db

    db = FeedbackDB("agentos_feedback.db")
    init_db(db.conn)
    record_id = db.insert_feedback(
        trace_id="trace-xxx",
        reviewer="ou_abc123",
        decision="REJECTED",
        reason="高管设备需要 CISO 额外审批",
        original_agent_output='{"action": "assign_asset", "asset_id": "mbp-001"}',
    )
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# NOTE: 所有日期时间均以 UTC ISO-8601 字符串存储，避免时区差异
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS agent_feedback (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id              TEXT    NOT NULL UNIQUE,
    reviewer              TEXT    NOT NULL,
    decision              TEXT    NOT NULL CHECK(decision IN ('APPROVED', 'REJECTED')),
    reason                TEXT,
    original_agent_output TEXT,
    timestamp             TEXT    NOT NULL
);
"""

_INSERT_SQL = """
INSERT INTO agent_feedback
    (trace_id, reviewer, decision, reason, original_agent_output, timestamp)
VALUES
    (?, ?, ?, ?, ?, ?);
"""

_SELECT_BY_TRACE_SQL = """
SELECT id, trace_id, reviewer, decision, reason, original_agent_output, timestamp
FROM agent_feedback
WHERE trace_id = ?;
"""

_SELECT_ALL_SQL = """
SELECT id, trace_id, reviewer, decision, reason, original_agent_output, timestamp
FROM agent_feedback
ORDER BY timestamp DESC;
"""


@dataclass
class FeedbackRecord:
    """代表 agent_feedback 表中的一条完整审批记录。"""
    trace_id: str
    reviewer: str
    decision: str
    reason: Optional[str]
    original_agent_output: Optional[str]
    timestamp: str
    id: Optional[int] = field(default=None)


def init_db(conn: sqlite3.Connection) -> None:
    """在指定连接上创建 agent_feedback 表（幂等，多次调用安全）。"""
    conn.execute(_CREATE_TABLE_SQL)
    conn.commit()
    logger.info("agent_feedback 表已初始化（idempotent）")


import threading

class FeedbackDB:
    """agent_feedback SQLite 表的读写封装。"""

    def __init__(self, db_path: str = "agentos_feedback.db") -> None:
        # NOTE: 若目录不存在则自动创建，确保 CI 环境兼容
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()
        logger.info("FeedbackDB initialized: %s", db_path)

    @property
    def conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL;")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        init_db(self.conn)

    def insert_feedback(
        self,
        trace_id: str,
        reviewer: str,
        decision: str,
        reason: Optional[str] = None,
        original_agent_output: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> int:
        """写入一条审批记录，返回新行的自增 id。

        Args:
            trace_id: Langfuse/OTel trace ID，全局唯一。
            reviewer: 审批人 ID（Feishu open_id 或 CLI 用户名）。
            decision: 'APPROVED' 或 'REJECTED'（大小写敏感）。
            reason: 审批理由文本，可为 None。
            original_agent_output: Agent 生成的动作 JSON 字符串，便于事后审计。
            timestamp: ISO-8601 UTC 时间戳；若 None 则自动填充当前时间。

        Returns:
            新插入行的 rowid (int)。

        Raises:
            ValueError: decision 不合法时抛出。
            sqlite3.IntegrityError: trace_id 重复时抛出。
        """
        if decision not in ("APPROVED", "REJECTED"):
            raise ValueError(f"decision 必须是 'APPROVED' 或 'REJECTED'，收到: {decision!r}")

        ts = timestamp or datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            _INSERT_SQL,
            (trace_id, reviewer, decision, reason, original_agent_output, ts),
        )
        self.conn.commit()
        row_id = cursor.lastrowid
        logger.info(
            "反馈已记录 [id=%s, trace=%s, decision=%s, reviewer=%s]",
            row_id, trace_id, decision, reviewer,
        )
        return row_id  # type: ignore[return-value]

    def get_by_trace_id(self, trace_id: str) -> Optional[FeedbackRecord]:
        """按 trace_id 查询单条审批记录，不存在返回 None。"""
        cursor = self.conn.execute(_SELECT_BY_TRACE_SQL, (trace_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return FeedbackRecord(
            id=row[0],
            trace_id=row[1],
            reviewer=row[2],
            decision=row[3],
            reason=row[4],
            original_agent_output=row[5],
            timestamp=row[6],
        )

    def list_all(self) -> list[FeedbackRecord]:
        """返回全部审批记录（按时间倒序）。"""
        cursor = self.conn.execute(_SELECT_ALL_SQL)
        rows = cursor.fetchall()
        return [
            FeedbackRecord(
                id=row[0],
                trace_id=row[1],
                reviewer=row[2],
                decision=row[3],
                reason=row[4],
                original_agent_output=row[5],
                timestamp=row[6],
            )
            for row in rows
        ]

    def close(self) -> None:
        """关闭数据库连接。"""
        self.conn.close()
        logger.info("FeedbackDB 连接已关闭")
