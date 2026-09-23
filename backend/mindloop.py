from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass
class Session:
    session_id: str
    task_type: str
    friction: str
    action: str
    reduction_count: int
    started_at: str
    recipe_id: str | None
    step_source: str = "rules"
    state: str = "PRESENTING_STEP"


class MindLoopService:
    """Offline-first task-initiation loop for the hackathon demo."""

    def __init__(self, db_path: Path, recipe_id: str | None = None) -> None:
        self.db_path = db_path
        self.recipe_id = recipe_id
        self.sessions: dict[str, Session] = {}
        self._raw_tasks: dict[str, str] = {}
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mindloop_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    friction TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reduction_count INTEGER NOT NULL,
                    elapsed_seconds INTEGER NOT NULL,
                    recipe_id TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def classify_task(task: str) -> str:
        value = task.lower()
        rules = {
            "writing": ("写", "文档", "方案", "稿", "ppt", "汇报", "路演"),
            "coding": ("代码", "开发", "bug", "接口", "编程", "coding"),
            "communication": ("回复", "消息", "邮件", "沟通", "联系"),
            "planning": ("计划", "规划", "安排", "待办"),
            "studying": ("学习", "复习", "论文", "阅读", "考试"),
        }
        for task_type, keywords in rules.items():
            if any(keyword in value for keyword in keywords):
                return task_type
        return "general"

    @staticmethod
    def first_action(task_type: str) -> str:
        return {
            "writing": "打开目标文档，只写下一句话标题",
            "coding": "打开项目，定位一个要修改的文件",
            "communication": "打开对话框，只写一句回复草稿",
            "planning": "新建一条待办，只写下第一件事",
            "studying": "打开材料，只读第一个小标题",
            "general": "打开完成这件事需要的第一个工具",
        }[task_type]

    @staticmethod
    def smaller_action(task_type: str, reduction_count: int) -> str:
        levels = {
            "writing": ["只打开目标文档", "把光标放到空白页上", "输入一个标题字符"],
            "coding": ["只打开代码编辑器", "只打开项目目录", "点击一个相关文件"],
            "communication": ["只打开对应的聊天或邮箱", "点进需要回复的对话", "输入一个称呼"],
            "planning": ["只打开待办工具", "点击新建待办", "输入一个动词"],
            "studying": ["只打开学习材料", "翻到第一页", "圈出第一个标题"],
            "general": ["只把需要的工具打开", "把目标页面放到眼前", "完成一个点击动作"],
        }
        options = levels[task_type]
        return options[min(reduction_count - 1, len(options) - 1)]

    def start(
        self,
        *,
        task: str,
        friction: str,
        generated_action: str | None = None,
        generated_task_type: str | None = None,
        step_source: str = "rules",
    ) -> dict[str, Any]:
        task_type = self.classify_task(task)
        if generated_task_type:
            task_type = generated_task_type
        session = Session(
            session_id=f"session_{uuid4().hex[:12]}",
            task_type=task_type,
            friction=friction,
            action=generated_action or self.first_action(task_type),
            reduction_count=0,
            started_at=datetime.now(UTC).isoformat(),
            recipe_id=self.recipe_id,
            step_source=step_source,
        )
        self.sessions[session.session_id] = session
        # Needed only for a possible Stuck retry; raw text is never persisted.
        self._raw_tasks[session.session_id] = task
        self._record(session, "started")
        return self._response(session)

    def feedback(
        self,
        *,
        session_id: str,
        result: str,
        generated_action: str | None = None,
        step_source: str = "rules",
    ) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        if session.state == "DONE":
            raise ValueError("This session is already complete")
        if result == "done":
            session.state = "DONE"
            self._record(session, "done")
            self._raw_tasks.pop(session_id, None)
            return {**self._response(session), "message": "已记录：这类启动策略对你有效。"}

        session.reduction_count += 1
        session.friction = "previous_step_still_too_large"
        session.action = generated_action or self.smaller_action(
            session.task_type, session.reduction_count
        )
        session.step_source = step_source
        self._record(session, "stuck")
        return {**self._response(session), "message": "步骤已缩小。现在只做这一件事。"}

    def context(self, session_id: str) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        return {
            "task": self._raw_tasks.get(session_id, ""),
            "task_type": session.task_type,
            "friction": session.friction,
            "previous_action": session.action,
            "reduction_count": session.reduction_count,
            "recipe_id": session.recipe_id,
            "state": session.state,
        }

    def memory_profile(self, task_type: str) -> dict[str, Any]:
        """Return anonymous behavioral evidence for personalization."""
        with self._connect() as connection:
            summary = connection.execute(
                """
                SELECT COUNT(DISTINCT session_id) AS sessions,
                  SUM(CASE WHEN event_type='done' THEN 1 ELSE 0 END) AS done,
                  SUM(CASE WHEN event_type='stuck' THEN 1 ELSE 0 END) AS stuck,
                  AVG(CASE WHEN event_type='done' THEN elapsed_seconds END) AS avg_seconds,
                  AVG(CASE WHEN event_type='done' THEN reduction_count END) AS avg_reductions
                FROM mindloop_events WHERE task_type=?
                """,
                (task_type,),
            ).fetchone()
            successful = connection.execute(
                """
                SELECT action FROM mindloop_events
                WHERE task_type=? AND event_type='done'
                ORDER BY id DESC LIMIT 3
                """,
                (task_type,),
            ).fetchall()
            stuck = connection.execute(
                """
                SELECT action FROM mindloop_events
                WHERE task_type=? AND event_type='stuck'
                ORDER BY id DESC LIMIT 3
                """,
                (task_type,),
            ).fetchall()
        sessions = summary["sessions"] or 0
        done = summary["done"] or 0
        stuck_count = summary["stuck"] or 0
        return {
            "task_type": task_type,
            "evidence_count": sessions,
            "done_count": done,
            "stuck_count": stuck_count,
            "success_rate": round(done / sessions, 2) if sessions else None,
            "avg_time_to_action_seconds": round(summary["avg_seconds"] or 0, 1),
            "avg_reduction_count": round(summary["avg_reductions"] or 0, 1),
            "recent_effective_actions": [row["action"] for row in successful],
            "recent_stuck_actions": [row["action"] for row in stuck],
            "guidance": (
                "Prefer a one-minute action and reduce decisions"
                if stuck_count > done and sessions >= 2
                else "Use a two-minute observable action"
            ),
            "privacy": "Contains anonymous action outcomes; no raw task text.",
        }

    def _elapsed(self, session: Session) -> int:
        return max(0, int((datetime.now(UTC) - datetime.fromisoformat(session.started_at)).total_seconds()))

    def _record(self, session: Session, event_type: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO mindloop_events (
                    session_id, event_type, task_type, friction, action,
                    reduction_count, elapsed_seconds, recipe_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session.session_id, event_type, session.task_type, session.friction,
                 session.action, session.reduction_count, self._elapsed(session),
                 session.recipe_id, datetime.now(UTC).isoformat()),
            )

    def _response(self, session: Session) -> dict[str, Any]:
        return {
            **asdict(session),
            "max_minutes": 2 if session.reduction_count == 0 else 1,
            "wearable_command": f"SHOW|{session.action}",
        }

    def metrics(self) -> dict[str, Any]:
        with self._connect() as connection:
            totals = connection.execute(
                """
                SELECT COUNT(DISTINCT session_id) AS sessions,
                  SUM(CASE WHEN event_type='done' THEN 1 ELSE 0 END) AS done,
                  SUM(CASE WHEN event_type='stuck' THEN 1 ELSE 0 END) AS stuck,
                  AVG(CASE WHEN event_type='done' THEN elapsed_seconds END) AS avg_seconds
                FROM mindloop_events
                """
            ).fetchone()
            by_type = connection.execute(
                """
                SELECT task_type,
                  SUM(CASE WHEN event_type='done' THEN 1 ELSE 0 END) AS done,
                  SUM(CASE WHEN event_type='stuck' THEN 1 ELSE 0 END) AS stuck
                FROM mindloop_events GROUP BY task_type ORDER BY task_type
                """
            ).fetchall()
        return {
            "sessions": totals["sessions"] or 0,
            "done": totals["done"] or 0,
            "stuck": totals["stuck"] or 0,
            "avg_time_to_action_seconds": round(totals["avg_seconds"] or 0, 1),
            "by_task_type": [dict(row) for row in by_type],
            "privacy": "Raw task text is not stored.",
        }

    def events(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, event_type, task_type, friction, action,
                  reduction_count, elapsed_seconds, recipe_id, created_at
                FROM mindloop_events ORDER BY id DESC LIMIT ?
                """, (limit,)
            ).fetchall()
        return [dict(row) for row in rows]
