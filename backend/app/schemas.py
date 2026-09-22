from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import FocusMode, FocusStatus, RecordStatus, StepStatus, TaskStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StepOut(ORMModel):
    id: str
    position: int
    content: str
    estimated_minutes: int
    status: StepStatus


class TaskCreate(BaseModel):
    user_id: str = "demo-user"
    title: str = Field(min_length=1, max_length=300)
    context: str | None = Field(default=None, max_length=1000)


class TaskOut(ORMModel):
    id: str
    user_id: str
    title: str
    status: TaskStatus
    current_step_index: int
    created_at: datetime
    steps: list[StepOut]
    current_step: StepOut | None = None


class TaskActionType(StrEnum):
    COMPLETE = "complete"
    SKIP = "skip"
    EDIT = "edit"
    STUCK = "stuck"


class TaskAction(BaseModel):
    action: TaskActionType
    content: str | None = Field(default=None, min_length=1, max_length=500)


class CaptureRequest(BaseModel):
    user_id: str = "demo-user"
    text: str = Field(min_length=1, max_length=2000)
    now: datetime | None = None


class CaptureOut(BaseModel):
    intent: str
    status: str
    message: str
    clarification_question: str | None = None
    entity_id: str | None = None
    data: dict = Field(default_factory=dict)


class TodoOut(ORMModel):
    id: str
    user_id: str
    content: str
    status: RecordStatus
    source_text: str | None
    created_at: datetime


class ReminderOut(ORMModel):
    id: str
    user_id: str
    content: str
    remind_at: datetime
    status: RecordStatus
    source_text: str | None
    created_at: datetime


class RecordUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=500)
    remind_at: datetime | None = None
    status: RecordStatus | None = None


class FocusStart(BaseModel):
    user_id: str = "demo-user"
    device_id: str = "demo-pendant"
    mode: FocusMode = FocusMode.LIGHT
    task_id: str | None = None
    camera_consent: bool = False

    @model_validator(mode="after")
    def deep_mode_requires_consent(self):
        if self.mode == FocusMode.DEEP and not self.camera_consent:
            raise ValueError("deep focus mode requires explicit camera_consent")
        return self


class FocusOut(ORMModel):
    id: str
    user_id: str
    device_id: str
    mode: FocusMode
    status: FocusStatus
    task_id: str | None
    camera_consent: bool
    cooldown_until: datetime | None
    started_at: datetime
    ended_at: datetime | None


class FocusSignal(BaseModel):
    signal_type: str = Field(pattern="^(movement|standing|walking|rhythm_change|away_from_screen|idle)$")
    duration_seconds: float = Field(default=0, ge=0, le=3600)
    confidence: float | None = Field(default=None, ge=0, le=1)


class FocusSignalOut(BaseModel):
    event_id: str
    prompted: bool
    reason: str
    cooldown_until: datetime | None = None


class FocusResponseType(StrEnum):
    IGNORE = "ignore"
    NEED_HELP = "need_help"
    RETURNED = "returned"
    RESET_2_MIN = "reset_2_min"
    FALSE_INTERVENTION = "false_intervention"


class FocusResponse(BaseModel):
    response: FocusResponseType


class FocusResponseOut(BaseModel):
    message: str
    next_step: str | None = None
    command_id: str | None = None


class CommandOut(ORMModel):
    id: str
    device_id: str
    kind: str
    payload: dict
    acknowledged: bool
    created_at: datetime


class StrategyFeedbackIn(BaseModel):
    user_id: str = "demo-user"
    session_id: str | None = None
    strategy: str
    effective: bool
    completed: bool = False
    return_latency_seconds: int | None = Field(default=None, ge=0)


class StrategyFeedbackOut(ORMModel):
    id: str
    user_id: str
    session_id: str | None
    strategy: str
    effective: bool
    completed: bool
    return_latency_seconds: int | None
    created_at: datetime
