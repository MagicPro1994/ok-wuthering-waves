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


from src.task.FishingTask import premium_listed


class TestPremiumListed(unittest.TestCase):
    def test_listed(self):
        self.assertTrue(premium_listed(["Premium Request", "Special: One Last Tear"]))

    def test_refreshing_only(self):
        self.assertFalse(premium_listed(["Premium Refresh in 1h"]))

    def test_missing(self):
        self.assertFalse(premium_listed(["Common Request", "Night Challenge"]))


from src.task.FishingTask import next_action


class TestNextAction(unittest.TestCase):
    def test_no_marker_sweeps(self):
        self.assertEqual('sweep', next_action(0.0, False))

    def test_big_error_turns(self):
        self.assertEqual('turn', next_action(7.5, True))
        self.assertEqual('turn', next_action(-12.0, True))

    def test_small_error_goes_forward(self):
        self.assertEqual('forward', next_action(3.9, True))
        self.assertEqual('forward', next_action(-4.0, True))
