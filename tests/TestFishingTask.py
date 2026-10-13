import json
import unittest
from pathlib import Path


class TestFishingConfig(unittest.TestCase):
    def test_tool_key_is_sendable(self):
        data = json.loads(Path("configs/Game Hotkey.json").read_text(encoding="utf-8"))
        self.assertEqual("t", data["Tool Key"])


from src.task.FishingTask import FishingTask


class FakeKeys:
    def __init__(self, value):
        self.value = value

    def get(self, key):
        return self.value


class TestFishingTaskBasics(unittest.TestCase):
    def test_check_tool_key_rejects_other_keys(self):
        task = FishingTask.__new__(FishingTask)
        task.key_config = FakeKeys("mouse_x2")
        with self.assertRaises(Exception) as ctx:
            task.check_tool_key()
        self.assertIn("Tool Key", str(ctx.exception))

    def test_check_tool_key_accepts_t(self):
        task = FishingTask.__new__(FishingTask)
        task.key_config = FakeKeys("t")
        task.check_tool_key()

    def test_registered_in_config(self):
        from config import config
        self.assertIn(["src.task.FishingTask", "FishingTask"], config["onetime_tasks"])
