import tempfile
import unittest
from pathlib import Path

from mindloop import MindLoopService


class MindLoopTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "test.db"

    def tearDown(self):
        self.tempdir.cleanup()

    def test_start_stuck_done_loop(self):
        service = MindLoopService(self.db_path, "recipe_test_demo")
        started = service.start(task="我要开始写路演方案", friction="unclear_first_step")
        self.assertEqual(started["task_type"], "writing")
        self.assertEqual(started["recipe_id"], "recipe_test_demo")
        self.assertTrue(started["wearable_command"].startswith("SHOW|"))

        smaller = service.feedback(session_id=started["session_id"], result="stuck")
        self.assertEqual(smaller["reduction_count"], 1)
        self.assertEqual(smaller["action"], "只打开目标文档")

        done = service.feedback(session_id=started["session_id"], result="done")
        self.assertEqual(done["state"], "DONE")
        self.assertEqual(service.metrics()["done"], 1)

    def test_raw_task_is_not_persisted(self):
        service = MindLoopService(self.db_path)
        private_task = "给张三写一份非常私密的诊断报告"
        service.start(task=private_task, friction="unclear_first_step")
        content = self.db_path.read_bytes().decode("utf-8", errors="ignore")
        self.assertNotIn(private_task, content)

    def test_generated_action_can_be_used_without_persisting_raw_task(self):
        service = MindLoopService(self.db_path, "recipe_test_demo")
        private_task = "为私密客户准备路演"
        started = service.start(
            task=private_task,
            friction="unclear_first_step",
            generated_action="打开路演文档，在第一页写下项目名称",
            generated_task_type="writing",
            step_source="ai",
        )
        self.assertEqual(started["step_source"], "ai")
        self.assertEqual(started["action"], "打开路演文档，在第一页写下项目名称")
        content = self.db_path.read_bytes().decode("utf-8", errors="ignore")
        self.assertNotIn(private_task, content)

    def test_memory_learns_from_done_and_stuck_without_raw_task(self):
        service = MindLoopService(self.db_path)
        first = service.start(task="写一份方案", friction="unclear_first_step")
        service.feedback(session_id=first["session_id"], result="stuck")
        service.feedback(session_id=first["session_id"], result="done")

        profile = service.memory_profile("writing")
        self.assertEqual(profile["evidence_count"], 1)
        self.assertEqual(profile["done_count"], 1)
        self.assertEqual(profile["stuck_count"], 1)
        self.assertEqual(len(profile["recent_effective_actions"]), 1)
        self.assertNotIn("写一份方案", str(profile))


if __name__ == "__main__":
    unittest.main()
