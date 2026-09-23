from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass
class Step:
    id: str
    action: str
    success_criteria: str
    max_minutes: int
    status: str = "pending"


@dataclass
class Session:
    session_id: str
    goal: str
    task_type: str
    friction: str
    steps: list[Step]
    current_step_index: int
    plan_version: int
    reduction_count: int
    started_at: str
    recipe_id: str | None
    step_source: str = "rules"
    state: str = "PRESENTING_STEP"
    hint: str | None = None


class MindLoopService:
    """Task plan state machine with offline fallback and anonymous evidence."""

    def __init__(self, db_path: Path, recipe_id: str | None = None) -> None:
        self.db_path = db_path
        self.recipe_id = recipe_id
        self.sessions: dict[str, Session] = {}
        self._raw_tasks: dict[str, str] = {}
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

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
            existing = {row["name"] for row in connection.execute("PRAGMA table_info(mindloop_events)")}
            migrations = {
                "step_index": "INTEGER NOT NULL DEFAULT 0",
                "max_minutes": "INTEGER NOT NULL DEFAULT 2",
                "plan_version": "INTEGER NOT NULL DEFAULT 1",
            }
            for column, definition in migrations.items():
                if column not in existing:
                    connection.execute(f"ALTER TABLE mindloop_events ADD COLUMN {column} {definition}")

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
    def fallback_plan(task_type: str) -> list[dict[str, Any]]:
        plans = {
            "writing": [
                ("打开目标文档", "目标文档已打开", 1),
                ("写下文档标题", "页面顶部已经出现标题", 2),
                ("列出三个核心要点", "标题下方有三个要点", 3),
                ("为每个要点补充一句内容", "三个要点各有一句说明", 5),
                ("从头读一遍并修正一个明显问题", "文档已完整检查一遍", 5),
            ],
            "coding": [
                ("打开项目并定位相关文件", "相关文件已显示在编辑器中", 2),
                ("写下需要改变的一个预期结果", "预期结果已记录", 2),
                ("完成最小代码修改", "代码中已经出现目标修改", 5),
                ("运行相关测试", "测试结果已经显示", 5),
            ],
            "communication": [
                ("打开需要回复的对话", "目标对话已打开", 1),
                ("写下一句核心回复", "输入框中已有核心句", 2),
                ("补充一个必要细节", "回复中已有必要细节", 2),
                ("检查后发送回复", "消息已发送", 2),
            ],
            "planning": [
                ("打开待办工具", "待办工具已打开", 1),
                ("写下最终目标", "目标已显示在待办中", 2),
                ("列出三个关键节点", "目标下已有三个节点", 3),
                ("为第一个节点设置时间", "第一个节点已有时间", 2),
            ],
            "studying": [
                ("打开需要学习的材料", "材料已打开", 1),
                ("读完第一个小标题的内容", "第一小节已读完", 5),
                ("写下一句内容摘要", "摘要已经写下", 2),
                ("完成下一小节并记录一个问题", "下一小节已读且问题已记录", 5),
            ],
            "general": [
                ("打开完成任务需要的第一个工具", "所需工具已打开", 1),
                ("找到最先需要处理的对象", "目标对象已显示", 2),
                ("完成第一个可见改动", "第一个改动已经出现", 3),
                ("检查结果并处理一个遗漏", "结果已检查且一个遗漏已处理", 5),
            ],
        }
        return [
            {"action": action, "success_criteria": criteria, "max_minutes": minutes}
            for action, criteria, minutes in plans[task_type]
        ]

    @staticmethod
    def smaller_action(task_type: str, current_action: str, reduction_count: int) -> dict[str, Any] | None:
        levels = {
            "writing": [
                ("只打开目标文档", "目标文档已打开"),
                ("找到目标文档图标", "目标文档图标已出现在眼前"),
                ("把光标移到目标文档图标上", "光标已停在目标文档图标上"),
            ],
            "coding": [
                ("只打开代码编辑器", "代码编辑器已打开"),
                ("找到代码编辑器图标", "代码编辑器图标已出现在眼前"),
                ("把光标移到代码编辑器图标上", "光标已停在图标上"),
            ],
            "communication": [
                ("只打开对应的聊天或邮箱", "对应应用已打开"),
                ("找到聊天或邮箱图标", "对应图标已出现在眼前"),
                ("把光标移到对应图标上", "光标已停在对应图标上"),
            ],
            "planning": [
                ("只打开待办工具", "待办工具已打开"),
                ("找到待办工具图标", "待办工具图标已出现在眼前"),
                ("把光标移到待办工具图标上", "光标已停在图标上"),
            ],
            "studying": [
                ("只打开学习材料", "学习材料已打开"),
                ("找到学习材料", "学习材料已出现在眼前"),
                ("把学习材料放到手边", "学习材料已经触手可及"),
            ],
            "general": [
                ("只打开需要使用的工具", "所需工具已打开"),
                ("找到需要使用的工具", "所需工具已出现在眼前"),
                ("把手移到需要使用的工具旁", "工具已经触手可及"),
            ],
        }
        options = levels[task_type]
        start = max(reduction_count - 1, 0)
        if start >= len(options):
            return None
        remaining = options[start:]
        selected = next((item for item in remaining if item[0] != current_action), None)
        if not selected:
            return None
        action, criteria = selected
        return {"action": action, "success_criteria": criteria, "max_minutes": 1}

    @staticmethod
    def step_hint(task_type: str) -> str:
        return "这一步已经很小了，试着完成它吧。"

    def start(
        self, *, task: str, friction: str, generated_plan: dict[str, Any] | None = None,
        step_source: str = "rules_fallback",
    ) -> dict[str, Any]:
        task_type = self.classify_task(task)
        goal = task
        raw_steps = self.fallback_plan(task_type)
        completion_criteria = f"{task}已经达到可使用或可提交状态"
        if generated_plan:
            task_type = generated_plan["task_type"]
            goal = generated_plan["goal"]
            raw_steps = generated_plan["steps"]
            completion_criteria = generated_plan["completion_criteria"]
        steps = [
            Step(id=f"step_{index + 1}", status="active" if index == 0 else "pending", **step)
            for index, step in enumerate(raw_steps)
        ]
        session = Session(
            session_id=f"session_{uuid4().hex[:12]}", goal=goal, task_type=task_type,
            friction=friction, steps=steps, current_step_index=0, plan_version=1,
            reduction_count=0, started_at=datetime.now(UTC).isoformat(),
            recipe_id=self.recipe_id, step_source=step_source,
        )
        self.sessions[session.session_id] = session
        self._raw_tasks[session.session_id] = task
        self._record(session, "started")
        response = self._response(session)
        response["completion_criteria"] = completion_criteria
        return response

    def feedback(
        self, *, session_id: str, result: str,
        revised_steps: list[dict[str, Any]] | None = None,
        step_source: str = "rules_fallback",
    ) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        if session.state == "DONE":
            raise ValueError("This task is already complete")

        current = session.steps[session.current_step_index]
        if result == "done":
            session.hint = None
            current.status = "completed"
            self._record(session, "step_done")
            if session.current_step_index == len(session.steps) - 1:
                session.state = "DONE"
                self._record(session, "done")
                self._raw_tasks.pop(session_id, None)
                return {**self._response(session), "message": "整个任务的所有步骤已完成。"}
            session.current_step_index += 1
            session.steps[session.current_step_index].status = "active"
            session.reduction_count = 0
            return {**self._response(session), "message": "当前步骤已完成，进入下一步。"}

        session.reduction_count += 1
        session.friction = "previous_step_still_too_large"
        if revised_steps:
            replacement = revised_steps
        else:
            # If AI re-planning fails, shrink only the current step and keep the
            # untouched remainder. Falling back must never collapse the goal
            # into a one-step task.
            untouched_remaining = [
                {
                    "action": step.action,
                    "success_criteria": step.success_criteria,
                    "max_minutes": step.max_minutes,
                }
                for step in session.steps[session.current_step_index + 1:]
            ]
            original_current = {
                "action": current.action,
                "success_criteria": current.success_criteria,
                "max_minutes": current.max_minutes,
            }
            smaller = self.smaller_action(session.task_type, current.action, session.reduction_count)
            if smaller is None:
                session.hint = self.step_hint(session.task_type)
                session.step_source = "hint"
                self._record(session, "hint")
                return {**self._response(session), "message": "这一步已经很小了，试着完成它吧。"}
            replacement = [smaller, original_current, *untouched_remaining]
        completed = session.steps[:session.current_step_index]
        new_steps = [
            Step(id=f"step_{len(completed) + index + 1}", status="active" if index == 0 else "pending", **step)
            for index, step in enumerate(replacement)
        ]
        session.steps = completed + new_steps
        session.plan_version += 1
        session.step_source = step_source
        session.hint = None
        self._record(session, "stuck")
        return {**self._response(session), "message": "已调整当前和后续步骤。"}

    def apply_background_replan(
        self, *, session_id: str, expected_plan_version: int, expected_step_index: int,
        revised_steps: list[dict[str, Any]],
    ) -> bool:
        """Apply an AI refinement only if the user has not moved on."""
        session = self.sessions.get(session_id)
        if not session or session.state == "DONE":
            return False
        if session.plan_version != expected_plan_version or session.current_step_index != expected_step_index:
            return False
        completed = session.steps[:session.current_step_index]
        session.steps = completed + [
            Step(id=f"step_{len(completed) + index + 1}", status="active" if index == 0 else "pending", **step)
            for index, step in enumerate(revised_steps)
        ]
        session.plan_version += 1
        session.step_source = "ai"
        session.hint = None
        self._record(session, "ai_replanned")
        return True

    def session_response(self, session_id: str) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        return self._response(session)

    def context(self, session_id: str) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        current = session.steps[session.current_step_index]
        return {
            "task": self._raw_tasks.get(session_id, session.goal),
            "task_type": session.task_type,
            "completed_steps": [asdict(step) for step in session.steps[:session.current_step_index]],
            "current_step": asdict(current),
            "remaining_steps": [asdict(step) for step in session.steps[session.current_step_index + 1:]],
            "recipe_id": session.recipe_id,
        }

    def memory_profile(self, task_type: str) -> dict[str, Any]:
        with self._connect() as connection:
            summary = connection.execute(
                """SELECT COUNT(DISTINCT session_id) AS sessions,
                SUM(CASE WHEN event_type='done' THEN 1 ELSE 0 END) AS done,
                SUM(CASE WHEN event_type='stuck' THEN 1 ELSE 0 END) AS stuck,
                AVG(CASE WHEN event_type='step_done' THEN elapsed_seconds END) AS avg_seconds,
                AVG(CASE WHEN event_type='step_done' THEN max_minutes END) AS preferred_minutes,
                AVG(CASE WHEN event_type='done' THEN reduction_count END) AS avg_reductions
                FROM mindloop_events WHERE task_type=?""", (task_type,),
            ).fetchone()
            successful = connection.execute(
                """SELECT action FROM mindloop_events WHERE task_type=? AND event_type='step_done'
                ORDER BY id DESC LIMIT 3""", (task_type,),
            ).fetchall()
            stuck = connection.execute(
                """SELECT action FROM mindloop_events WHERE task_type=? AND event_type='stuck'
                ORDER BY id DESC LIMIT 3""", (task_type,),
            ).fetchall()
            stuck_position = connection.execute(
                """SELECT step_index, COUNT(*) AS count FROM mindloop_events
                WHERE task_type=? AND event_type='stuck' GROUP BY step_index
                ORDER BY count DESC, step_index ASC LIMIT 1""", (task_type,),
            ).fetchone()
            replans = connection.execute(
                """SELECT AVG(plan_version - 1) AS average FROM mindloop_events
                WHERE task_type=? AND event_type='done'""", (task_type,),
            ).fetchone()
        sessions, done, stuck_count = summary["sessions"] or 0, summary["done"] or 0, summary["stuck"] or 0
        effective_actions = [row["action"] for row in successful]
        stuck_actions = [row["action"] for row in stuck]
        return {
            "task_type": task_type, "evidence_count": sessions, "done_count": done,
            "stuck_count": stuck_count, "success_rate": round(done / sessions, 2) if sessions else None,
            "avg_time_to_action_seconds": round(summary["avg_seconds"] or 0, 1),
            "avg_reduction_count": round(summary["avg_reductions"] or 0, 1),
            "preferred_step_minutes": round(summary["preferred_minutes"] or 2, 1),
            "preferred_tool": self._infer_preferred_tool(effective_actions),
            "frequent_stuck_step_number": (stuck_position["step_index"] + 1) if stuck_position else None,
            "effective_action_patterns": self._action_patterns(effective_actions),
            "avoid_patterns": stuck_actions,
            "avg_replans_to_success": round(replans["average"] or 0, 1),
            "recent_effective_actions": effective_actions,
            "recent_stuck_actions": stuck_actions,
            "guidance": "Prefer smaller steps and fewer decisions" if stuck_count > done and sessions >= 2 else "Use short observable steps",
            "privacy": "Contains anonymous action outcomes; no raw task text.",
        }

    def _current(self, session: Session) -> Step:
        return session.steps[min(session.current_step_index, len(session.steps) - 1)]

    def _elapsed(self, session: Session) -> int:
        return max(0, int((datetime.now(UTC) - datetime.fromisoformat(session.started_at)).total_seconds()))

    def _record(self, session: Session, event_type: str) -> None:
        current = self._current(session)
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO mindloop_events (session_id,event_type,task_type,friction,action,
                reduction_count,elapsed_seconds,recipe_id,created_at,step_index,max_minutes,plan_version)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (session.session_id, event_type, session.task_type, session.friction, current.action,
                 session.reduction_count, self._elapsed(session), session.recipe_id, datetime.now(UTC).isoformat(),
                 session.current_step_index, current.max_minutes, session.plan_version),
            )

    @staticmethod
    def _infer_preferred_tool(actions: list[str]) -> str | None:
        tools = {
            "手机备忘录": ("手机", "备忘录"),
            "电脑文档": ("文档", "PPT", "编辑器", "项目"),
            "纸笔": ("纸", "笔记本", "手写"),
        }
        scores = {tool: sum(any(word.lower() in action.lower() for word in words) for action in actions) for tool, words in tools.items()}
        best = max(scores, key=scores.get) if scores else None
        return best if best and scores[best] > 0 else None

    @staticmethod
    def _action_patterns(actions: list[str]) -> list[str]:
        verbs = ("打开", "点击", "找到", "写下", "列出", "输入", "检查", "发送", "运行", "阅读")
        return list(dict.fromkeys(verb for action in actions for verb in verbs if action.startswith(verb)))[:3]

    def _response(self, session: Session) -> dict[str, Any]:
        current = self._current(session)
        return {
            "session_id": session.session_id, "goal": session.goal,
            "task_type": session.task_type, "friction": session.friction,
            "action": current.action, "success_criteria": current.success_criteria,
            "max_minutes": current.max_minutes, "state": session.state,
            "step_source": session.step_source, "plan_version": session.plan_version,
            "current_step_index": session.current_step_index,
            "current_step_number": session.current_step_index + 1,
            "total_steps": len(session.steps),
            "completed_steps": sum(step.status == "completed" for step in session.steps),
            "reduction_count": session.reduction_count,
            "hint": session.hint,
            "recipe_id": session.recipe_id,
            "wearable_command": f"SHOW|{current.action}",
        }

    def metrics(self) -> dict[str, Any]:
        with self._connect() as connection:
            totals = connection.execute(
                """SELECT COUNT(DISTINCT session_id) AS sessions,
                SUM(CASE WHEN event_type='done' THEN 1 ELSE 0 END) AS done,
                SUM(CASE WHEN event_type='stuck' THEN 1 ELSE 0 END) AS stuck,
                AVG(CASE WHEN event_type='step_done' THEN elapsed_seconds END) AS avg_seconds
                FROM mindloop_events"""
            ).fetchone()
        return {"sessions": totals["sessions"] or 0, "done": totals["done"] or 0,
                "stuck": totals["stuck"] or 0,
                "avg_time_to_action_seconds": round(totals["avg_seconds"] or 0, 1),
                "privacy": "Raw task text is not stored."}

    def events(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT session_id,event_type,task_type,friction,action,reduction_count,
                elapsed_seconds,recipe_id,created_at FROM mindloop_events ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
