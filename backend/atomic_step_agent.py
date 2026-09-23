from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from llm_client import LLMError, OpenAICompatibleClient


SYSTEM_PROMPT = """你是 MindLoop 的认知启动代理。你的目标不是替用户完成任务，
而是降低启动摩擦，让用户在现实世界中立即做出一个可观察动作。

决策顺序：
1. 理解任务和当前摩擦，但不做疾病、情绪或注意力诊断。
2. 参考 recipe_strategy 和 memory_profile；用户自己的 Done/Stuck 证据优先于通用建议。
3. 只生成一个动作。不能使用“并且、然后、接着”串联多个动作。
4. 动作必须以明确动词开头，例如打开、点击、找到、写下、放到。
5. 动作必须具体、可观察、可判断完成，并能在 max_minutes 内完成。
6. 不要求用户思考、规划、整理、完成整项任务；只降低进入任务环境的摩擦。
7. previous_action 不为空时，说明用户反馈 Stuck。新动作必须是上一步的真子集，
   减少点击、文字量或认知决策，不能只是换一种说法。
8. 不输出鼓励、解释、多个选项、Markdown 或医疗建议。
9. reason 仅供系统审计，不面向穿戴屏幕。

严格返回 JSON：
{"task_type":"...","friction":"...","action":"...","reason":"...","max_minutes":1或2}"""


class AtomicStepResult(BaseModel):
    task_type: Literal["writing", "coding", "communication", "planning", "studying", "general"]
    friction: str = Field(min_length=2, max_length=100)
    action: str = Field(min_length=2, max_length=160)
    reason: str = Field(min_length=2, max_length=240)
    max_minutes: int = Field(ge=1, le=10)


@dataclass(frozen=True)
class AgentResult:
    step: AtomicStepResult | None
    source: str
    error: str | None = None


class AtomicStepAgent:
    def __init__(self, client: OpenAICompatibleClient, *, fallback_enabled: bool = True) -> None:
        self.client = client
        self.fallback_enabled = fallback_enabled

    async def generate(
        self, *, task: str, task_type: str, friction: str, recipe_id: str | None,
        previous_action: str | None = None, reduction_count: int = 0,
        memory_profile: dict[str, Any] | None = None,
    ) -> AgentResult:
        max_minutes = 2 if reduction_count == 0 else 1
        payload: dict[str, Any] = {
            "task": task,
            "task_type": task_type,
            "friction": friction,
            "recipe_strategy": {"recipe_id": recipe_id, "max_action_minutes": max_minutes, "show_full_backlog": False},
            "previous_action": previous_action,
            "reduction_count": reduction_count,
            "max_minutes": max_minutes,
            "memory_profile": memory_profile or {"evidence_count": 0},
        }
        try:
            raw = await self.client.json_completion(system_prompt=SYSTEM_PROMPT, payload=payload)
            step = AtomicStepResult.model_validate(raw)
            if step.max_minutes > max_minutes:
                raise LLMError("AI action exceeds the requested time limit")
            if previous_action and step.action.strip() == previous_action.strip():
                raise LLMError("AI did not make the stuck action smaller")
            return AgentResult(step=step, source="ai")
        except (LLMError, ValidationError) as exc:
            if not self.fallback_enabled:
                raise
            return AgentResult(step=None, source="rules_fallback", error=str(exc))
