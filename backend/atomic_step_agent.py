from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from llm_client import LLMError, OpenAICompatibleClient


TASK_TYPES = Literal["writing", "coding", "communication", "planning", "studying", "general"]

PLAN_SYSTEM_PROMPT = """你是 MindLoop 的任务规划代理。用户给出一个大任务后，你要一次性生成完整、按顺序执行的行动计划。

规则：
1. 理解目标，但不做疾病、情绪或注意力诊断。
2. 参考 memory_profile；用户自己的 Done/Stuck 证据优先于通用建议。
3. 生成 3–7 个有先后依赖的 steps，覆盖从开始到用户目标真正完成，而不是只覆盖“开始”。
4. 每个 step 只能包含一个现实世界中可观察、可判断完成的动作。
5. action 必须以明确动词开头；不要使用“并且、然后、接着、以及”串联多个动作。
6. 每步通常能在 1–5 分钟完成。复杂任务可拆得更细，但不要重复或发明用户未要求的交付物。
7. success_criteria 描述动作完成时可直接观察到的结果，不能写主观感受。
8. completion_criteria 描述整个大任务完成的最低可验证标准。
9. 不输出鼓励、解释、多个方案、Markdown 或医疗建议。

严格返回 JSON：
{"goal":"...","task_type":"writing|coding|communication|planning|studying|general","steps":[{"action":"...","success_criteria":"...","max_minutes":1}],"completion_criteria":"...","reason":"..."}"""

REPLAN_SYSTEM_PROMPT = """你是 MindLoop 的任务重规划代理。用户在 current_step 反馈 Stuck。

规则：
1. completed_steps 已经完成，绝不能修改、重复或要求用户重做。
2. 只返回替换 current_step 和 remaining_steps 的 revised_steps。
3. revised_steps 的第一个动作必须比 current_step 更小、更具体，减少点击、文字量或认知决策，不能只是换一种说法。
4. 后续步骤仍需覆盖原目标；保留仍然合理的剩余步骤，避免无意义地全部重写。
5. 每个 step 只有一个可观察动作，以明确动词开头，不使用“并且、然后、接着、以及”串联动作。
6. 每步 1–5 分钟，success_criteria 必须可直接验证。
7. 参考 memory_profile，避开 recent_stuck_actions 中反复失败的粒度。
8. 不输出 Markdown、鼓励、解释或已完成步骤。

严格返回 JSON：
{"revised_steps":[{"action":"...","success_criteria":"...","max_minutes":1}],"reason":"..."}"""


class PlanStep(BaseModel):
    action: str = Field(min_length=2, max_length=160)
    success_criteria: str = Field(min_length=2, max_length=200)
    max_minutes: int = Field(ge=1, le=10)


class TaskPlanResult(BaseModel):
    goal: str = Field(min_length=2, max_length=240)
    task_type: TASK_TYPES
    steps: list[PlanStep] = Field(min_length=2, max_length=10)
    completion_criteria: str = Field(min_length=2, max_length=300)
    reason: str = Field(min_length=2, max_length=240)


class ReplanResult(BaseModel):
    revised_steps: list[PlanStep] = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=2, max_length=240)


@dataclass(frozen=True)
class PlanAgentResult:
    plan: TaskPlanResult | None
    source: str
    error: str | None = None


@dataclass(frozen=True)
class ReplanAgentResult:
    revised_steps: list[PlanStep] | None
    source: str
    error: str | None = None


class TaskPlanAgent:
    def __init__(self, client: OpenAICompatibleClient, *, fallback_enabled: bool = True) -> None:
        self.client = client
        self.fallback_enabled = fallback_enabled

    async def generate_plan(
        self, *, task: str, task_type: str, friction: str, recipe_id: str | None,
        memory_profile: dict[str, Any] | None = None,
    ) -> PlanAgentResult:
        payload = {
            "task": task,
            "task_type": task_type,
            "friction": friction,
            "recipe_strategy": {"recipe_id": recipe_id, "plan_all_steps_upfront": True},
            "memory_profile": memory_profile or {"evidence_count": 0},
        }
        try:
            raw = await self.client.json_completion(system_prompt=PLAN_SYSTEM_PROMPT, payload=payload)
            plan = TaskPlanResult.model_validate(raw)
            self._validate_steps(plan.steps)
            return PlanAgentResult(plan=plan, source="ai")
        except (LLMError, ValidationError) as exc:
            if not self.fallback_enabled:
                raise
            return PlanAgentResult(plan=None, source="rules_fallback", error=str(exc))

    async def replan(
        self, *, task: str, task_type: str, completed_steps: list[dict[str, Any]],
        current_step: dict[str, Any], remaining_steps: list[dict[str, Any]],
        recipe_id: str | None, memory_profile: dict[str, Any] | None = None,
    ) -> ReplanAgentResult:
        payload = {
            "goal": task,
            "task_type": task_type,
            "completed_steps": completed_steps,
            "current_step": current_step,
            "remaining_steps": remaining_steps,
            "recipe_strategy": {"recipe_id": recipe_id, "preserve_completed_steps": True},
            "memory_profile": memory_profile or {"evidence_count": 0},
        }
        try:
            raw = await self.client.json_completion(system_prompt=REPLAN_SYSTEM_PROMPT, payload=payload)
            result = ReplanResult.model_validate(raw)
            self._validate_steps(result.revised_steps)
            if result.revised_steps[0].action.strip() == current_step["action"].strip():
                raise LLMError("AI did not make the stuck step smaller")
            return ReplanAgentResult(revised_steps=result.revised_steps, source="ai")
        except (LLMError, ValidationError) as exc:
            if not self.fallback_enabled:
                raise
            return ReplanAgentResult(revised_steps=None, source="rules_fallback", error=str(exc))

    @staticmethod
    def _validate_steps(steps: list[PlanStep]) -> None:
        actions = [step.action.strip() for step in steps]
        if len(set(actions)) != len(actions):
            raise LLMError("AI returned duplicate steps")


# Backwards-compatible import name for older integrations.
AtomicStepAgent = TaskPlanAgent
