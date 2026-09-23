from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from llm_client import LLMError, OpenAICompatibleClient


logger = logging.getLogger(__name__)
TASK_TYPES = Literal["writing", "coding", "communication", "planning", "studying", "general"]

PLAN_SYSTEM_PROMPT = """你是 MindLoop 的任务规划代理。用户给出一个大任务后，一次性生成完整、按顺序执行的最小可行计划。

规则：
1. 严格保持用户原目标，不得擅自增加交付物、受众、渠道或完成标准。目标模糊时规划一个可执行 MVP，不猜测完整规格。
2. 参考 memory_profile：优先采用 preferred_step_minutes、preferred_tool 和 recent_effective_actions，避开 avoid_patterns 与 recent_stuck_actions。
3. 生成 3–7 个有依赖顺序的 steps，覆盖从开始到整个目标可验证完成，不能只覆盖启动阶段。
4. 前一步的可观察结果必须能作为后一步的输入；步骤不得重复、倒序或互相冲突。
5. 每个 step 只能有一个主要动作，action 以明确动词开头，不使用“并且、然后、接着、以及”串联动作。
6. 第一步只负责进入任务环境，必须以“打开、找到、新建、进入、拿出、选择”之一开头且不超过 2 分钟；不要在第一步要求产出多个观点或做关键决策。其余每步 1–5 分钟。
7. success_criteria 必须是直接可观察的完成证据，不写“感觉更清楚”等主观状态。
8. 最后一步必须检查、提交、发送、运行或确认整个目标；completion_criteria 是整个任务的最低可验证标准。
9. 不输出鼓励、解释、多个方案、Markdown 或医疗建议。

严格返回 JSON：
{"goal":"...","task_type":"writing|coding|communication|planning|studying|general","steps":[{"action":"...","success_criteria":"...","max_minutes":1}],"completion_criteria":"...","reason":"..."}"""

REPAIR_SYSTEM_PROMPT = """你是 MindLoop 的计划质量修复器。根据 validation_issues 修复 candidate_plan。
保持用户原目标，不新增范围；输出 3–7 个有依赖顺序、互不重复的步骤。每步只有一个主要动作，第一步不超过2分钟，其余不超过5分钟，最后一步必须验证整个目标。只返回与原计划相同结构的严格 JSON。"""

REPLAN_SYSTEM_PROMPT = """你是 MindLoop 的任务重规划代理。用户在 current_step 反馈 Stuck。

规则：
1. completed_steps 已经完成，绝不能修改、重复或要求用户重做。
2. 只返回替换 current_step 和 remaining_steps 的 revised_steps；不得缩减原目标范围。
3. 第一个新动作必须比 current_step 更小、更具体，减少点击、文字量或认知决策，不能只是换一种说法。
4. 保留仍然合理的后续步骤，确保最后一步仍然验证整个目标，不能因为当前卡住而丢失剩余计划。
5. 前一步结果必须可供后一步使用；步骤不得重复、倒序或互相冲突。
6. 每步只有一个主要动作，以明确动词开头，不使用“并且、然后、接着、以及”串联动作。
7. 每步 1–5 分钟，success_criteria 必须可直接验证。
8. 使用 memory_profile 的偏好，避开 recent_stuck_actions 和 avoid_patterns。
9. 不输出 Markdown、鼓励、解释或已完成步骤。

严格返回 JSON：
{"revised_steps":[{"action":"...","success_criteria":"...","max_minutes":1}],"reason":"..."}"""


class PlanStep(BaseModel):
    action: str = Field(min_length=2, max_length=160)
    success_criteria: str = Field(min_length=2, max_length=200)
    max_minutes: int = Field(ge=1, le=5)


class TaskPlanResult(BaseModel):
    goal: str = Field(min_length=2, max_length=240)
    task_type: TASK_TYPES
    steps: list[PlanStep] = Field(min_length=3, max_length=7)
    completion_criteria: str = Field(min_length=2, max_length=300)
    reason: str = Field(min_length=2, max_length=240)


class ReplanResult(BaseModel):
    revised_steps: list[PlanStep] = Field(min_length=1, max_length=7)
    reason: str = Field(min_length=2, max_length=240)


@dataclass(frozen=True)
class PlanAgentResult:
    plan: TaskPlanResult | None
    source: str
    error: str | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class ReplanAgentResult:
    revised_steps: list[PlanStep] | None
    source: str
    error: str | None = None
    error_type: str | None = None


class TaskPlanAgent:
    def __init__(self, client: OpenAICompatibleClient, *, fallback_enabled: bool = True) -> None:
        self.client = client
        self.fallback_enabled = fallback_enabled

    async def generate_plan(
        self, *, task: str, task_type: str, friction: str, recipe_id: str | None,
        memory_profile: dict[str, Any] | None = None,
    ) -> PlanAgentResult:
        payload = {
            "task": task, "task_type": task_type, "friction": friction,
            "recipe_strategy": {"recipe_id": recipe_id, "plan_all_steps_upfront": True},
            "memory_profile": memory_profile or {"evidence_count": 0},
        }
        try:
            raw = await self.client.json_completion(system_prompt=PLAN_SYSTEM_PROMPT, payload=payload)
            try:
                normalized = self._normalize_candidate(raw, task_type)
                plan = TaskPlanResult.model_validate(normalized)
                self._validate_plan(plan)
            except (ValidationError, LLMError) as first_error:
                issues = self._error_message(first_error)
                repaired = await self.client.json_completion(
                    system_prompt=REPAIR_SYSTEM_PROMPT,
                    payload={"task": task, "candidate_plan": raw, "validation_issues": issues},
                )
                plan = TaskPlanResult.model_validate(self._normalize_candidate(repaired, task_type))
                self._validate_plan(plan)
            return PlanAgentResult(plan=plan, source="ai")
        except (LLMError, ValidationError) as exc:
            return self._plan_fallback(exc)

    async def replan(
        self, *, task: str, task_type: str, completed_steps: list[dict[str, Any]],
        current_step: dict[str, Any], remaining_steps: list[dict[str, Any]],
        recipe_id: str | None, memory_profile: dict[str, Any] | None = None,
    ) -> ReplanAgentResult:
        payload = {
            "goal": task, "task_type": task_type, "completed_steps": completed_steps,
            "current_step": current_step, "remaining_steps": remaining_steps,
            "recipe_strategy": {"recipe_id": recipe_id, "preserve_completed_steps": True},
            "memory_profile": memory_profile or {"evidence_count": 0},
        }
        try:
            raw = await self.client.json_completion(system_prompt=REPLAN_SYSTEM_PROMPT, payload=payload)
            result = ReplanResult.model_validate(raw)
            self._validate_steps(result.revised_steps)
            if result.revised_steps[0].action.strip() == current_step["action"].strip():
                raise LLMError("AI did not make the stuck step smaller", code="quality_failed")
            if remaining_steps and len(result.revised_steps) < 2:
                raise LLMError("AI dropped the remaining task plan", code="quality_failed")
            return ReplanAgentResult(revised_steps=result.revised_steps, source="ai")
        except (LLMError, ValidationError) as exc:
            if not self.fallback_enabled:
                raise
            error_type = self._error_type(exc)
            logger.warning("mindloop_ai_fallback operation=replan error_type=%s model=%s", error_type, self.client.model)
            return ReplanAgentResult(revised_steps=None, source="rules_fallback", error=str(exc), error_type=error_type)

    def _plan_fallback(self, exc: LLMError | ValidationError) -> PlanAgentResult:
        if not self.fallback_enabled:
            raise exc
        error_type = self._error_type(exc)
        logger.warning("mindloop_ai_fallback operation=plan error_type=%s model=%s", error_type, self.client.model)
        return PlanAgentResult(plan=None, source="rules_fallback", error=str(exc), error_type=error_type)

    @classmethod
    def _validate_plan(cls, plan: TaskPlanResult) -> None:
        cls._validate_steps(plan.steps)
        issues: list[str] = []
        if plan.steps[0].max_minutes > 2:
            issues.append("first_step_too_large")
        if not plan.steps[0].action.startswith(("打开", "找到", "新建", "进入", "拿出", "选择")):
            issues.append("first_step_has_too_much_cognitive_load")
        final_text = f"{plan.steps[-1].action} {plan.steps[-1].success_criteria}"
        if not any(word in final_text for word in ("检查", "确认", "提交", "发送", "运行", "测试", "播放", "复核", "通读", "完成", "可用")):
            issues.append("last_step_does_not_verify_goal")
        if issues:
            raise LLMError(",".join(issues), code="quality_failed")

    @staticmethod
    def _normalize_candidate(raw: dict[str, Any], task_type: str) -> dict[str, Any]:
        """Repair safe structural issues locally to avoid a second slow model call."""
        candidate = dict(raw)
        raw_steps = candidate.get("steps")
        if not isinstance(raw_steps, list):
            return candidate
        steps = [dict(step) for step in raw_steps if isinstance(step, dict)]
        for step in steps:
            minutes = step.get("max_minutes")
            if isinstance(minutes, (int, float)):
                step["max_minutes"] = max(1, min(5, int(minutes)))
        if len(steps) > 7:
            steps = [*steps[:6], steps[-1]]
        low_friction = ("打开", "找到", "新建", "进入", "拿出", "选择")
        if steps and not str(steps[0].get("action", "")).startswith(low_friction):
            setup = {
                "writing": {"action": "打开目标文档", "success_criteria": "目标文档已打开", "max_minutes": 1},
                "coding": {"action": "打开代码编辑器", "success_criteria": "代码编辑器已打开", "max_minutes": 1},
                "communication": {"action": "打开对应的聊天或邮箱", "success_criteria": "对应应用已打开", "max_minutes": 1},
                "planning": {"action": "打开待办工具", "success_criteria": "待办工具已打开", "max_minutes": 1},
                "studying": {"action": "打开学习材料", "success_criteria": "学习材料已打开", "max_minutes": 1},
                "general": {"action": "打开需要使用的工具", "success_criteria": "所需工具已打开", "max_minutes": 1},
            }[task_type]
            steps = [setup, *steps]
            if len(steps) > 7:
                steps = [*steps[:6], steps[-1]]
        if steps and isinstance(steps[0].get("max_minutes"), (int, float)):
            steps[0]["max_minutes"] = min(2, int(steps[0]["max_minutes"]))
        candidate["steps"] = steps
        return candidate

    @staticmethod
    def _validate_steps(steps: list[PlanStep]) -> None:
        actions = [step.action.strip() for step in steps]
        issues: list[str] = []
        if len(set(actions)) != len(actions):
            issues.append("duplicate_steps")
        connectors = ("并且", "然后", "接着", "以及")
        if any(any(connector in action for connector in connectors) for action in actions):
            issues.append("multiple_actions_in_step")
        criteria = [step.success_criteria.strip() for step in steps]
        if len(set(criteria)) != len(criteria):
            issues.append("duplicate_success_criteria")
        if issues:
            raise LLMError(",".join(issues), code="quality_failed")

    @staticmethod
    def _error_type(exc: LLMError | ValidationError) -> str:
        return exc.code if isinstance(exc, LLMError) else "validation_failed"

    @classmethod
    def _error_message(cls, exc: LLMError | ValidationError) -> str:
        return f"{cls._error_type(exc)}: {exc}"


AtomicStepAgent = TaskPlanAgent
