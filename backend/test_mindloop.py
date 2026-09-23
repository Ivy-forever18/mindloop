import tempfile
import unittest
from pathlib import Path

from mindloop import MindLoopService


PLAN = {
    "goal": "完成路演PPT", "task_type": "writing",
    "steps": [
        {"action": "打开PPT", "success_criteria": "PPT已打开", "max_minutes": 1},
        {"action": "写下标题", "success_criteria": "标题已显示", "max_minutes": 2},
        {"action": "检查页面", "success_criteria": "页面已检查", "max_minutes": 3},
    ],
    "completion_criteria": "PPT可以完整播放", "reason": "顺序执行",
}


class MindLoopTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.service = MindLoopService(Path(self.tempdir.name) / "test.db", "recipe_test")

    def tearDown(self):
        self.tempdir.cleanup()

    def test_done_advances_until_last_step(self):
        started = self.service.start(task="准备路演", friction="unclear", generated_plan=PLAN, step_source="ai")
        self.assertEqual(started["total_steps"], 3)
        second = self.service.feedback(session_id=started["session_id"], result="done")
        self.assertEqual(second["state"], "PRESENTING_STEP")
        self.assertEqual(second["current_step_number"], 2)
        third = self.service.feedback(session_id=started["session_id"], result="done")
        self.assertEqual(third["current_step_number"], 3)
        finished = self.service.feedback(session_id=started["session_id"], result="done")
        self.assertEqual(finished["state"], "DONE")

    def test_stuck_preserves_completed_and_replaces_unfinished(self):
        started = self.service.start(task="准备路演", friction="unclear", generated_plan=PLAN, step_source="ai")
        self.service.feedback(session_id=started["session_id"], result="done")
        revised = [
            {"action": "只输入一个标题词", "success_criteria": "页面已有一个词", "max_minutes": 1},
            {"action": "补全标题", "success_criteria": "标题已完整", "max_minutes": 2},
            {"action": "检查页面", "success_criteria": "页面已检查", "max_minutes": 3},
        ]
        result = self.service.feedback(session_id=started["session_id"], result="stuck", revised_steps=revised, step_source="ai")
        self.assertEqual(result["current_step_number"], 2)
        self.assertEqual(result["total_steps"], 4)
        self.assertEqual(result["action"], "只输入一个标题词")
        self.assertEqual(result["plan_version"], 2)
        context = self.service.context(started["session_id"])
        self.assertEqual(context["completed_steps"][0]["action"], "打开PPT")

    def test_raw_task_is_not_persisted(self):
        private = "为私密客户准备路演"
        self.service.start(task=private, friction="unclear", generated_plan=PLAN)
        content = self.service.db_path.read_bytes().decode("utf-8", errors="ignore")
        self.assertNotIn(private, content)

    def test_fallback_still_returns_multiple_steps(self):
        started = self.service.start(task="写一份方案", friction="unclear")
        self.assertGreaterEqual(started["total_steps"], 3)

    def test_memory_learns_step_size_and_stuck_position(self):
        started = self.service.start(task="准备路演", friction="unclear", generated_plan=PLAN)
        self.service.feedback(session_id=started["session_id"], result="done")
        self.service.feedback(session_id=started["session_id"], result="stuck")
        profile = self.service.memory_profile("writing")
        self.assertEqual(profile["preferred_step_minutes"], 1.0)
        self.assertEqual(profile["frequent_stuck_step_number"], 2)
        self.assertIn("打开", profile["effective_action_patterns"])

    def test_stuck_fallback_keeps_remaining_plan(self):
        started = self.service.start(task="准备路演", friction="unclear", generated_plan=PLAN)
        result = self.service.feedback(session_id=started["session_id"], result="stuck")
        self.assertEqual(result["current_step_number"], 1)
        self.assertEqual(result["total_steps"], 4)
        self.assertEqual(result["action"], "只打开目标文档")
        context = self.service.context(started["session_id"])
        self.assertEqual([step["action"] for step in context["remaining_steps"]], ["打开PPT", "写下标题", "检查页面"])

    def test_repeated_stuck_keeps_shrinking_instead_of_repeating(self):
        started = self.service.start(task="准备路演", friction="unclear", generated_plan=PLAN)
        first = self.service.feedback(session_id=started["session_id"], result="stuck", step_source="local_adjustment")
        second = self.service.feedback(session_id=started["session_id"], result="stuck", step_source="local_adjustment")
        self.assertNotEqual(first["action"], second["action"])
        self.assertEqual(second["step_source"], "local_adjustment")
        self.assertGreater(second["total_steps"], first["total_steps"])

    def test_minimum_step_returns_hint_instead_of_cycling(self):
        started = self.service.start(task="准备路演", friction="unclear", generated_plan=PLAN)
        result = None
        for _ in range(4):
            result = self.service.feedback(
                session_id=started["session_id"], result="stuck", step_source="local_adjustment",
            )
        self.assertEqual(result["step_source"], "hint")
        self.assertTrue(result["hint"])
        self.assertEqual(result["state"], "PRESENTING_STEP")

    def test_background_replan_applies_only_before_user_moves_on(self):
        started = self.service.start(task="准备路演", friction="unclear", generated_plan=PLAN)
        local = self.service.feedback(session_id=started["session_id"], result="stuck", step_source="local_adjustment")
        revised = [
            {"action": "找到PPT图标", "success_criteria": "PPT图标已显示", "max_minutes": 1},
            {"action": "打开PPT", "success_criteria": "PPT已打开", "max_minutes": 1},
            {"action": "写下标题", "success_criteria": "标题已显示", "max_minutes": 2},
            {"action": "检查页面", "success_criteria": "页面已检查", "max_minutes": 3},
        ]
        applied = self.service.apply_background_replan(
            session_id=started["session_id"], expected_plan_version=local["plan_version"],
            expected_step_index=local["current_step_index"], revised_steps=revised,
        )
        self.assertTrue(applied)
        latest = self.service.session_response(started["session_id"])
        self.assertEqual(latest["step_source"], "ai")
        self.assertEqual(latest["plan_version"], local["plan_version"] + 1)


if __name__ == "__main__":
    unittest.main()
