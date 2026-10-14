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


from src.task.FishingTask import premium_available, track_action


class TestPremiumAvailable(unittest.TestCase):
    def test_open_entry_with_refresh_timer(self):
        # live screen: the open premium entry shows its refresh countdown too
        self.assertTrue(premium_available(["Night Special: Abyssal Mutants", "0/2", "Refresh", "in 13h"]))

    def test_partly_done(self):
        self.assertTrue(premium_available(["Special: One Last Tear", "1/2"]))

    def test_completed_entry(self):
        self.assertFalse(premium_available(["Night Special: Abyssal Mutants", "2/2", "Refresh", "in 13h"]))

    def test_no_entry(self):
        self.assertFalse(premium_available(["Refresh", "in 13h"]))
        self.assertFalse(premium_available([]))


class TestCoords(unittest.TestCase):
    def test_parses_the_readout(self):
        from src.task.FishingTask import parse_coords
        self.assertEqual((6962, 3089), parse_coords(['6962,3089,0 2026-10-1416:12:29+7* UHD']))

    def test_unreadable_gives_none(self):
        from src.task.FishingTask import parse_coords
        self.assertIsNone(parse_coords(['UHD', '']))
        self.assertIsNone(parse_coords([]))

    def test_moved_after_a_sail_press(self):
        from src.task.FishingTask import moved
        self.assertTrue(moved((6953, 3064), (6962, 3089)))     # live: 2 s of W moved about 27 units

    def test_not_moved_when_stuck(self):
        from src.task.FishingTask import moved
        self.assertFalse(moved((6962, 3089), (6963, 3090)))

    def test_unreadable_counts_as_moved(self):
        from src.task.FishingTask import moved
        self.assertTrue(moved(None, (1, 1)))
        self.assertTrue(moved((1, 1), None))


class TestHubAnchor(unittest.TestCase):
    def test_matches_what_ocr_reads_on_the_hub(self):
        from src.task.FishingTask import HUB_ANCHOR
        # live OCR of the dock hub: the bubble icon makes "Dock Shop" read as "DockShop"
        for texts in (["Dock", "Fame", "DockShop", "Set Sail!"], ["DockShop"], ["Set Sail!"]):
            self.assertTrue(any(HUB_ANCHOR.search(t) for t in texts), texts)

    def test_does_not_match_the_open_world(self):
        from src.task.FishingTask import HUB_ANCHOR
        self.assertFalse(any(HUB_ANCHOR.search(t) for t in ["Planck", "Check the dock", "16776/16776"]))


class TestTrackAction(unittest.TestCase):
    def test_track_button(self):
        self.assertEqual('track', track_action(["Track"]))

    def test_already_tracking(self):
        self.assertEqual('tracking', track_action(["Cancel Tracking"]))

    def test_nothing_readable(self):
        self.assertIsNone(track_action(["Request Rewards"]))


from src.task.FishingTask import next_action


class TestNextAction(unittest.TestCase):
    def test_no_target_is_lost(self):
        self.assertEqual('lost', next_action(0.0, False))

    def test_big_error_turns(self):
        self.assertEqual('turn', next_action(15.0, True))
        self.assertEqual('turn', next_action(-170.0, True))

    def test_small_error_goes_forward(self):
        self.assertEqual('forward', next_action(11.9, True))
        self.assertEqual('forward', next_action(-12.0, True))


class TestSellText(unittest.TestCase):
    def test_no_catch_detected(self):
        from src.task.FishingTask import catch_list_empty
        self.assertTrue(catch_list_empty(["Catch List", "No Catch"]))
        self.assertFalse(catch_list_empty(["Catch List", "Giant Gulper"]))
