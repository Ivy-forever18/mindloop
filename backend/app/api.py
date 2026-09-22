from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models import DeviceCommand, FocusEvent, FocusMode, FocusSession, FocusStatus, RecordStatus, Reminder, StrategyFeedback, Task, Todo
from app.schemas import (CaptureOut, CaptureRequest, CommandOut, FocusOut, FocusResponse, FocusResponseOut, FocusResponseType,
                         FocusSignal, FocusSignalOut, FocusStart, RecordUpdate, ReminderOut, StrategyFeedbackIn,
                         StrategyFeedbackOut, TaskAction, TaskCreate, TaskOut, TodoOut)
from app.services.agent import agent
from app.services.tasks import apply_action, create_task, task_out

router = APIRouter(prefix="/v1")


async def load_task(db: AsyncSession, task_id: str) -> Task:
    task = await db.scalar(select(Task).where(Task.id == task_id).options(selectinload(Task.steps)))
    if not task:
        raise HTTPException(404, "task not found")
    return task


@router.post("/tasks", response_model=TaskOut, status_code=201)
async def tasks_create(body: TaskCreate, db: AsyncSession = Depends(get_db)):
    return task_out(await create_task(db, body))


@router.get("/tasks", response_model=list[TaskOut])
async def tasks_list(user_id: str = "demo-user", db: AsyncSession = Depends(get_db)):
    items = (await db.scalars(select(Task).where(Task.user_id == user_id).options(selectinload(Task.steps)).order_by(Task.created_at.desc()))).all()
    return [task_out(item) for item in items]


@router.post("/tasks/{task_id}/actions", response_model=TaskOut)
async def tasks_action(task_id: str, body: TaskAction, db: AsyncSession = Depends(get_db)):
    try:
        return task_out(await apply_action(db, await load_task(db, task_id), body))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/captures", response_model=CaptureOut)
async def capture(body: CaptureRequest, db: AsyncSession = Depends(get_db)):
    parsed = agent.parse_capture(body.text, body.now)
    if parsed.clarification:
        return CaptureOut(intent=parsed.intent, status="needs_clarification", message="还差一个时间信息", clarification_question=parsed.clarification)
    if parsed.intent == "task":
        task = await create_task(db, TaskCreate(user_id=body.user_id, title=parsed.content))
        return CaptureOut(intent="task", status="created", message="已拆成可执行步骤", entity_id=task.id, data={"current_step": task.steps[0].content})
    if parsed.intent == "reminder":
        item = Reminder(user_id=body.user_id, content=parsed.content, remind_at=parsed.remind_at, source_text=body.text)
        message = f"已设置提醒：{parsed.content}"
    else:
        item = Todo(user_id=body.user_id, content=parsed.content, source_text=body.text)
        message = f"已记下：{parsed.content}"
    db.add(item)
    await db.commit()
    await db.refresh(item)
    data = {"remind_at": item.remind_at.isoformat()} if isinstance(item, Reminder) else {}
    return CaptureOut(intent=parsed.intent, status="created", message=message, entity_id=item.id, data=data)


@router.get("/todos", response_model=list[TodoOut])
async def todos_list(user_id: str = "demo-user", db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(Todo).where(Todo.user_id == user_id, Todo.status != RecordStatus.DELETED).order_by(Todo.created_at.desc()))).all()


@router.patch("/todos/{item_id}", response_model=TodoOut)
async def todo_update(item_id: str, body: RecordUpdate, db: AsyncSession = Depends(get_db)):
    item = await db.get(Todo, item_id)
    if not item: raise HTTPException(404, "todo not found")
    if body.content is not None: item.content = body.content
    if body.status is not None: item.status = body.status
    await db.commit(); await db.refresh(item)
    return item


@router.get("/reminders", response_model=list[ReminderOut])
async def reminders_list(user_id: str = "demo-user", due_before: datetime | None = None, db: AsyncSession = Depends(get_db)):
    query = select(Reminder).where(Reminder.user_id == user_id, Reminder.status != RecordStatus.DELETED)
    if due_before: query = query.where(Reminder.remind_at <= due_before)
    return (await db.scalars(query.order_by(Reminder.remind_at))).all()


@router.patch("/reminders/{item_id}", response_model=ReminderOut)
async def reminder_update(item_id: str, body: RecordUpdate, db: AsyncSession = Depends(get_db)):
    item = await db.get(Reminder, item_id)
    if not item: raise HTTPException(404, "reminder not found")
    if body.content is not None: item.content = body.content
    if body.remind_at is not None: item.remind_at = body.remind_at
    if body.status is not None: item.status = body.status
    await db.commit(); await db.refresh(item)
    return item


@router.post("/focus/sessions", response_model=FocusOut, status_code=201)
async def focus_start(body: FocusStart, db: AsyncSession = Depends(get_db)):
    active = await db.scalar(select(FocusSession).where(FocusSession.user_id == body.user_id, FocusSession.status == FocusStatus.ACTIVE))
    if active: raise HTTPException(409, "an active focus session already exists")
    if body.task_id: await load_task(db, body.task_id)
    item = FocusSession(**body.model_dump())
    db.add(item); await db.commit(); await db.refresh(item)
    return item


async def load_session(db: AsyncSession, session_id: str) -> FocusSession:
    item = await db.get(FocusSession, session_id)
    if not item: raise HTTPException(404, "focus session not found")
    return item


@router.post("/focus/sessions/{session_id}/signals", response_model=FocusSignalOut)
async def focus_signal(session_id: str, body: FocusSignal, db: AsyncSession = Depends(get_db)):
    session = await load_session(db, session_id)
    if session.status != FocusStatus.ACTIVE: raise HTTPException(409, "focus session has ended")
    if session.mode == FocusMode.LIGHT and body.signal_type in ("away_from_screen", "idle"):
        raise HTTPException(422, "camera-derived signals are not accepted in light mode")
    if session.mode == FocusMode.DEEP and not session.camera_consent:
        raise HTTPException(403, "camera consent is not active")
    now = datetime.now(timezone.utc)
    event = FocusEvent(session_id=session.id, signal_type=body.signal_type, confidence=body.confidence)
    session.activity_seconds += body.duration_seconds
    reason, prompted = "信号已记录，尚未达到连续活动阈值", False
    cooldown_until = session.cooldown_until
    if cooldown_until and cooldown_until.tzinfo is None:
        cooldown_until = cooldown_until.replace(tzinfo=timezone.utc)
    if cooldown_until and cooldown_until > now:
        reason = "处于冷却期，保持安静"
    elif session.activity_seconds >= settings.focus_activity_threshold_seconds:
        prompted = True
        reason = "活动状态持续变化，已发送一次温和提醒"
        event.prompted_at = now
        session.cooldown_until = now + timedelta(seconds=settings.focus_cooldown_seconds)
        session.activity_seconds = 0
        db.add(DeviceCommand(device_id=session.device_id, kind="gentle_nudge", payload={"vibration": "single_light", "message": "你似乎离开当前任务一会儿了"}))
    db.add(event); await db.commit(); await db.refresh(event)
    return FocusSignalOut(event_id=event.id, prompted=prompted, reason=reason, cooldown_until=session.cooldown_until)


@router.post("/focus/sessions/{session_id}/respond", response_model=FocusResponseOut)
async def focus_respond(session_id: str, body: FocusResponse, db: AsyncSession = Depends(get_db)):
    session = await load_session(db, session_id)
    event = await db.scalar(select(FocusEvent).where(FocusEvent.session_id == session.id, FocusEvent.prompted_at.is_not(None)).order_by(FocusEvent.prompted_at.desc()))
    if not event: raise HTTPException(409, "no prompted event to respond to")
    event.user_feedback = body.response.value
    next_step, command = None, None
    if body.response == FocusResponseType.NEED_HELP:
        if session.task_id:
            task = await load_task(db, session.task_id)
            current = task_out(task).current_step
            next_step = current.content if current else "选择一个想继续的小动作"
        else: next_step = "打开当前任务材料，完成一个最小动作"
        command = DeviceCommand(device_id=session.device_id, kind="show_next_step", payload={"message": next_step})
        event.final_action = "return_to_next_step"
    elif body.response == FocusResponseType.RESET_2_MIN:
        command = DeviceCommand(device_id=session.device_id, kind="reset_timer", payload={"seconds": 120})
        event.final_action = "reset_2_min"
    elif body.response == FocusResponseType.RETURNED:
        event.returned_at = datetime.now(timezone.utc); event.final_action = "returned"
    elif body.response == FocusResponseType.FALSE_INTERVENTION:
        event.final_action = "false_intervention"
    else: event.final_action = "ignored"
    if command: db.add(command)
    await db.commit()
    return FocusResponseOut(message="反馈已记录", next_step=next_step, command_id=command.id if command else None)


@router.post("/focus/sessions/{session_id}/end", response_model=FocusOut)
async def focus_end(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await load_session(db, session_id)
    session.status = FocusStatus.ENDED; session.ended_at = datetime.now(timezone.utc)
    await db.commit(); await db.refresh(session)
    return session


@router.get("/devices/{device_id}/commands", response_model=list[CommandOut])
async def commands(device_id: str, pending_only: bool = True, db: AsyncSession = Depends(get_db)):
    query = select(DeviceCommand).where(DeviceCommand.device_id == device_id)
    if pending_only: query = query.where(DeviceCommand.acknowledged.is_(False))
    return (await db.scalars(query.order_by(DeviceCommand.created_at))).all()


@router.post("/devices/{device_id}/commands/{command_id}/ack", response_model=CommandOut)
async def command_ack(device_id: str, command_id: str, db: AsyncSession = Depends(get_db)):
    item = await db.get(DeviceCommand, command_id)
    if not item or item.device_id != device_id: raise HTTPException(404, "command not found")
    item.acknowledged = True; await db.commit(); await db.refresh(item)
    return item


@router.post("/strategy-feedback", response_model=StrategyFeedbackOut, status_code=201)
async def feedback(body: StrategyFeedbackIn, db: AsyncSession = Depends(get_db)):
    item = StrategyFeedback(**body.model_dump()); db.add(item); await db.commit(); await db.refresh(item); return item


@router.get("/metrics/summary")
async def metrics(user_id: str = "demo-user", db: AsyncSession = Depends(get_db)):
    tasks_total = await db.scalar(select(func.count(Task.id)).where(Task.user_id == user_id)) or 0
    tasks_started = await db.scalar(select(func.count(Task.id)).where(Task.user_id == user_id, Task.initiated_at.is_not(None))) or 0
    sessions = await db.scalar(select(func.count(FocusSession.id)).where(FocusSession.user_id == user_id)) or 0
    prompted = await db.scalar(select(func.count(FocusEvent.id)).join(FocusSession).where(FocusSession.user_id == user_id, FocusEvent.prompted_at.is_not(None))) or 0
    returned = await db.scalar(select(func.count(FocusEvent.id)).join(FocusSession).where(FocusSession.user_id == user_id, FocusEvent.returned_at.is_not(None))) or 0
    false_hits = await db.scalar(select(func.count(FocusEvent.id)).join(FocusSession).where(FocusSession.user_id == user_id, FocusEvent.final_action == "false_intervention")) or 0
    return {"task_count": tasks_total, "task_first_step_completion_rate": tasks_started / tasks_total if tasks_total else 0,
            "focus_session_count": sessions, "intervention_count": prompted,
            "return_to_task_rate": returned / prompted if prompted else 0,
            "false_intervention_rate": false_hits / prompted if prompted else 0}
