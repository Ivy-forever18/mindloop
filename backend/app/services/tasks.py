from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import StepStatus, Task, TaskStatus, TaskStep
from app.schemas import TaskAction, TaskActionType, TaskCreate, TaskOut
from app.services.agent import agent


def task_out(task: Task) -> TaskOut:
    current = task.steps[task.current_step_index] if task.status == TaskStatus.ACTIVE and task.current_step_index < len(task.steps) else None
    return TaskOut.model_validate(task).model_copy(update={"current_step": current})


async def create_task(db: AsyncSession, body: TaskCreate) -> Task:
    task = Task(user_id=body.user_id, title=body.title)
    for position, (content, minutes) in enumerate(agent.atomize(body.title, body.context)):
        task.steps.append(TaskStep(position=position, content=content, estimated_minutes=minutes))
    db.add(task)
    await db.commit()
    await db.refresh(task, ["steps"])
    return task


async def apply_action(db: AsyncSession, task: Task, body: TaskAction) -> Task:
    if task.status != TaskStatus.ACTIVE or task.current_step_index >= len(task.steps):
        return task
    step = task.steps[task.current_step_index]
    if body.action == TaskActionType.EDIT:
        if not body.content:
            raise ValueError("content is required for edit")
        step.content = body.content
    elif body.action == TaskActionType.STUCK:
        step.content, step.estimated_minutes = agent.shrink(step.content)
    else:
        step.status = StepStatus.COMPLETED if body.action == TaskActionType.COMPLETE else StepStatus.SKIPPED
        step.completed_at = datetime.now(timezone.utc)
        if task.current_step_index == 0 and body.action == TaskActionType.COMPLETE:
            task.initiated_at = step.completed_at
        task.current_step_index += 1
        if task.current_step_index >= len(task.steps):
            task.status = TaskStatus.COMPLETED
    await db.commit()
    await db.refresh(task, ["steps"])
    return task
