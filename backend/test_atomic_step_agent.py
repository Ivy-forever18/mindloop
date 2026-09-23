import unittest

from atomic_step_agent import TaskPlanAgent
from llm_client import LLMError


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.model = "fake-model"
        self.calls = 0

    async def json_completion(self, **_):
        self.calls += 1
        if self.error:
            raise self.error
        if isinstance(self.result, list):
            return self.result.pop(0)
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
        result = await TaskPlanAgent(FakeClient(error=LLMError("timeout", code="timeout"))).generate_plan(
            task="准备路演", task_type="writing", friction="unclear_first_step", recipe_id=None,
        )
        self.assertEqual(result.source, "rules_fallback")
        self.assertIsNone(result.plan)
        self.assertEqual(result.error_type, "timeout")

    async def test_safe_duration_issue_is_repaired_locally(self):
        invalid = {**VALID_PLAN, "steps": [{**step, "max_minutes": 5} for step in VALID_PLAN["steps"]]}
        client = FakeClient(result=[invalid, VALID_PLAN])
        result = await TaskPlanAgent(client).generate_plan(
            task="准备路演", task_type="writing", friction="unclear_first_step", recipe_id=None,
        )
        self.assertEqual(result.source, "ai")
        self.assertEqual(client.calls, 1)
        self.assertEqual(result.plan.steps[0].max_minutes, 2)

    async def test_cognitively_heavy_first_step_is_repaired(self):
        heavy = {**VALID_PLAN, "steps": [
            {"action": "写下三个核心观点", "success_criteria": "已有三个观点", "max_minutes": 2},
            *VALID_PLAN["steps"][1:],
        ]}
        client = FakeClient(result=[heavy, VALID_PLAN])
        result = await TaskPlanAgent(client).generate_plan(
            task="准备路演", task_type="writing", friction="unclear_first_step", recipe_id=None,
        )
        self.assertEqual(result.source, "ai")
        self.assertEqual(client.calls, 1)
        self.assertEqual(result.plan.steps[0].action, "打开目标文档")

    async def test_complex_duplicate_issue_uses_one_model_repair(self):
        duplicate = {**VALID_PLAN, "steps": [VALID_PLAN["steps"][0], VALID_PLAN["steps"][0], VALID_PLAN["steps"][2]]}
        client = FakeClient(result=[duplicate, VALID_PLAN])
        result = await TaskPlanAgent(client).generate_plan(
            task="准备路演", task_type="writing", friction="unclear_first_step", recipe_id=None,
        )
        self.assertEqual(result.source, "ai")
        self.assertEqual(client.calls, 2)

    async def test_replan_rejects_unchanged_first_step(self):
        current = {"action": "打开路演文档", "success_criteria": "文档已打开", "max_minutes": 1}
        result = await TaskPlanAgent(FakeClient({
            "revised_steps": [current], "reason": "缩小步骤",
        })).replan(task="准备路演", task_type="writing", completed_steps=[],
                   current_step=current, remaining_steps=[], recipe_id=None)
        self.assertEqual(result.source, "rules_fallback")

    async def test_replan_rejects_dropped_remaining_plan(self):
        current = {"action": "写下标题", "success_criteria": "标题已显示", "max_minutes": 2}
        result = await TaskPlanAgent(FakeClient({
            "revised_steps": [
                {"action": "只写一个标题词", "success_criteria": "页面已有一个词", "max_minutes": 1}
            ],
            "reason": "缩小步骤",
        })).replan(
            task="准备路演", task_type="writing", completed_steps=[], current_step=current,
            remaining_steps=[{"action": "检查页面", "success_criteria": "页面已检查", "max_minutes": 3}],
            recipe_id=None,
        )
        self.assertEqual(result.source, "rules_fallback")


if __name__ == "__main__":
    unittest.main()
