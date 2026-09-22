from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class TaskStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class StepStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class RecordStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    DELETED = "deleted"


class FocusMode(StrEnum):
    LIGHT = "light"
    DEEP = "deep"


class FocusStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.ACTIVE)
    current_step_index: Mapped[int] = mapped_column(Integer, default=0)
    initiated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    steps: Mapped[list[TaskStep]] = relationship(back_populates="task", cascade="all, delete-orphan", order_by="TaskStep.position")


class TaskStep(Base):
    __tablename__ = "task_steps"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(String(500))
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[StepStatus] = mapped_column(Enum(StepStatus), default=StepStatus.PENDING)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task: Mapped[Task] = relationship(back_populates="steps")


class Todo(Base):
    __tablename__ = "todos"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String, index=True)
    content: Mapped[str] = mapped_column(String(500))
    status: Mapped[RecordStatus] = mapped_column(Enum(RecordStatus), default=RecordStatus.OPEN)
    source_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String, index=True)
    content: Mapped[str] = mapped_column(String(500))
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[RecordStatus] = mapped_column(Enum(RecordStatus), default=RecordStatus.OPEN)
    source_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FocusSession(Base):
    __tablename__ = "focus_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String, index=True)
    device_id: Mapped[str] = mapped_column(String, index=True)
    mode: Mapped[FocusMode] = mapped_column(Enum(FocusMode))
    status: Mapped[FocusStatus] = mapped_column(Enum(FocusStatus), default=FocusStatus.ACTIVE)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    camera_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    activity_seconds: Mapped[float] = mapped_column(Float, default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FocusEvent(Base):
    __tablename__ = "focus_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("focus_sessions.id", ondelete="CASCADE"), index=True)
    signal_type: Mapped[str] = mapped_column(String(80))
    confidence: Mapped[float | None] = mapped_column(Float)
    prompted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_feedback: Mapped[str | None] = mapped_column(String(80))
    final_action: Mapped[str | None] = mapped_column(String(80))
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeviceCommand(Base):
    __tablename__ = "device_commands"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StrategyFeedback(Base):
    __tablename__ = "strategy_feedback"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("focus_sessions.id"))
    strategy: Mapped[str] = mapped_column(String(120))
    effective: Mapped[bool] = mapped_column(Boolean)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    return_latency_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
