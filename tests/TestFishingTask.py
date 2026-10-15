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


from src.task.FishingTask import premium_entry, track_action

# OCR centres (name, y) of the live Fishing Request panel
PANEL = [("Premium Request", 128), ("Night Special: Abyssal Mutants", 187), ("Refresh", 183), ("0/2", 218),
         ("in 13h", 221), ("Common Request", 298), ("Night Challenge: Deceleration .", 358), ("0/4", 388),
         ("Ongoing", 390), ("Challenge: End of Hunt", 558), ("0/4", 589)]


class TestPremiumEntry(unittest.TestCase):
    def test_finds_the_open_premium_entry(self):
        self.assertEqual(218, premium_entry(PANEL))

    def test_ignores_common_requests_when_there_is_no_premium_section(self):
        # the failure seen live: no premium entry, so the first common request sat where the premium one would
        shifted = [("Common Request", 128), ("Night Challenge: Nothing Ventured", 187), ("0/1", 218)]
        self.assertIsNone(premium_entry(shifted))

    def test_premium_header_without_an_entry(self):
        self.assertIsNone(premium_entry([("Premium Request", 128), ("Refresh in 3h", 190), ("Common Request", 298),
                                         ("0/4", 388)]))

    def test_completed_premium_entry(self):
        done = [(n, y) if n != "0/2" else ("2/2", y) for n, y in PANEL]
        self.assertIsNone(premium_entry(done))

    def test_no_boxes(self):
        self.assertIsNone(premium_entry([]))

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


class TestDialHour(unittest.TestCase):
    # OCR (text, x, y) of the live Set Time dial, relative coordinates
    BOXES = [("Set Time", 0.083, 0.065), ("Current Time", 0.499, 0.095), ("09:00", 0.499, 0.137),
             ("Today", 0.083, 0.138), ("09:00", 0.5, 0.654), ("10:00", 0.648, 0.622), ("11:00", 0.785, 0.622),
             ("Today", 0.499, 0.697), ("Confirm", 0.499, 0.92)]

    def test_reads_the_centred_time(self):
        from src.task.FishingTask import dial_hour
        self.assertEqual(9, dial_hour(self.BOXES))

    def test_ignores_the_current_time_label(self):
        from src.task.FishingTask import dial_hour
        boxes = [("14:00", 0.499, 0.137), ("19:00", 0.5, 0.654)]
        self.assertEqual(19, dial_hour(boxes))

    def test_unreadable_gives_none(self):
        from src.task.FishingTask import dial_hour
        self.assertIsNone(dial_hour([("Confirm", 0.499, 0.92)]))

    def test_is_night(self):
        from src.task.FishingTask import is_night_hour
        self.assertTrue(all(is_night_hour(h) for h in (19, 22, 23, 0, 4)))
        self.assertFalse(any(is_night_hour(h) for h in (5, 9, 15, 18)))


class TestTrackedAfterClick(unittest.TestCase):
    def test_game_returns_to_the_hub_with_a_toast(self):
        # live: clicking Track closes the request screen and shows this toast over the dock hub
        from src.task.FishingTask import tracked_after_click
        self.assertTrue(tracked_after_click(["Dock", "Fame", "Tracking the target. Please follow the guide.", "Set Sail!"]))

    def test_cancel_tracking_button_still_counts(self):
        from src.task.FishingTask import tracked_after_click
        self.assertTrue(tracked_after_click(["Cancel Tracking"]))

    def test_the_request_screen_with_a_track_button_does_not(self):
        from src.task.FishingTask import tracked_after_click
        self.assertFalse(tracked_after_click(["Track", "Request Rewards"]))
