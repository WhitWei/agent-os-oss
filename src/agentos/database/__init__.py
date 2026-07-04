"""Database package — SQLite persistence for Agent OS feedback and approvals.

提供以下功能：
- ``init_db()``        — 初始化数据库并创建 schema
- ``FeedbackDB``       — agent_feedback 表的读写封装
"""

from agentos.database.feedback_db import FeedbackDB, init_db, FeedbackRecord

__all__ = [
    "FeedbackDB",
    "FeedbackRecord",
    "init_db",
]
