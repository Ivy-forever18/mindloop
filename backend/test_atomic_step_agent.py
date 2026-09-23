import unittest

from atomic_step_agent import TaskPlanAgent
from llm_client import LLMError


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    async def json_completion(self, **_):
        if self.error:
            raise self.error
        return self.result


VALID_PLAN = {
    "goal": "完成路演PPT",
    "task_type": "writing",
    "steps": [
        {"action": "打开路演文档", "success_criteria": "文档已打开", "max_minutes": 1},
        {"action": "写下第一页标题", "success_criteria": "第一页已有标题", "max_minutes": 2},
        {"action": "检查全部页面", "success_criteria": "所有页面已检查", "max_minutes": 5},
    ],
    "completion_criteria": "PPT可以完整播放",
    "reason": "按依赖顺序推进",
}


class TaskPlanAgentTest(unittest.IsolatedAsyncioTestCase):
    async def test_accepts_complete_plan(self):
        result = await TaskPlanAgent(FakeClient(VALID_PLAN)).generate_plan(
            task="准备路演", task_type="writing", friction="unclear_first_step", recipe_id=None,
        )
        self.assertEqual(result.source, "ai")
        self.assertEqual(len(result.plan.steps), 3)

    async def test_gateway_error_uses_fallback(self):
        result = await TaskPlanAgent(FakeClient(error=LLMError("timeout"))).generate_plan(
            task="准备路演", task_type="writing", friction="unclear_first_step", recipe_id=None,
        )
        self.assertEqual(result.source, "rules_fallback")
        self.assertIsNone(result.plan)

    async def test_replan_rejects_unchanged_first_step(self):
        current = {"action": "打开路演文档", "success_criteria": "文档已打开", "max_minutes": 1}
        result = await TaskPlanAgent(FakeClient({
            "revised_steps": [current], "reason": "缩小步骤",
        })).replan(task="准备路演", task_type="writing", completed_steps=[],
                   current_step=current, remaining_steps=[], recipe_id=None)
        self.assertEqual(result.source, "rules_fallback")


if __name__ == "__main__":
    unittest.main()
