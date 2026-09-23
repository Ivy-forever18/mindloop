import unittest

from atomic_step_agent import AtomicStepAgent
from llm_client import LLMError


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    async def json_completion(self, **_):
        if self.error:
            raise self.error
        return self.result


class AtomicStepAgentTest(unittest.IsolatedAsyncioTestCase):
    async def test_accepts_valid_atomic_step(self):
        agent = AtomicStepAgent(FakeClient({
            "task_type": "writing",
            "friction": "unclear_first_step",
            "action": "打开路演文档，在第一页写下项目名称",
            "reason": "降低进入任务的摩擦",
            "max_minutes": 2,
        }))
        result = await agent.generate(
            task="准备路演", task_type="writing",
            friction="unclear_first_step", recipe_id="recipe_test_demo",
        )
        self.assertEqual(result.source, "ai")
        self.assertEqual(result.step.max_minutes, 2)

    async def test_gateway_error_uses_rules_fallback(self):
        agent = AtomicStepAgent(FakeClient(error=LLMError("timeout")))
        result = await agent.generate(
            task="准备路演", task_type="writing",
            friction="unclear_first_step", recipe_id=None,
        )
        self.assertEqual(result.source, "rules_fallback")
        self.assertIsNone(result.step)

    async def test_stuck_must_return_a_different_action(self):
        action = "只打开目标文档"
        agent = AtomicStepAgent(FakeClient({
            "task_type": "writing",
            "friction": "previous_step_still_too_large",
            "action": action,
            "reason": "进一步缩小",
            "max_minutes": 1,
        }))
        result = await agent.generate(
            task="准备路演", task_type="writing",
            friction="previous_step_still_too_large", recipe_id=None,
            previous_action=action, reduction_count=1,
        )
        self.assertEqual(result.source, "rules_fallback")


if __name__ == "__main__":
    unittest.main()
