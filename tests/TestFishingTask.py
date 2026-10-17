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


from src.task.FishingTask import common_entry, premium_entry, track_action

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

    def test_a_finished_premium_entry_waits_to_be_delivered(self):
        done = [(n, y) if n != "0/2" else ("2/2", y) for n, y in PANEL]
        self.assertEqual(218, premium_entry(done))

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

    def test_reads_the_hour_when_the_ocr_joins_it_with_today(self):
        from src.task.FishingTask import dial_hour
        self.assertEqual(3, dial_hour([("03:00 Today", 0.5, 0.67), ("04:00", 0.648, 0.622)]))

    def test_current_time_at_the_top(self):
        # live: the dial opened at 20:00 and 02:37, both night, so nothing needs changing
        from src.task.FishingTask import current_hour
        self.assertEqual(2, current_hour([("Current Time", 0.499, 0.095), ("02:37", 0.499, 0.137)]))
        self.assertEqual(9, current_hour(self.BOXES))
        self.assertIsNone(current_hour([("03:00", 0.5, 0.654)]))


class TestFishPrompt(unittest.TestCase):
    def pattern(self):
        import re
        from src.task.FishingTask import FishingTask
        return re.compile(FishingTask.F_PROMPT)

    def test_matches_the_prompt_the_ocr_reads_without_its_key_badge(self):
        # live: the OCR returns "F" and "Fish" as separate boxes
        for text in ("Fish", "[F] Fish", "F Fish"):
            self.assertTrue(self.pattern().search(text), text)

    def test_ignores_other_texts_with_fish_inside(self):
        for text in ("Fried Egg Jellyfish", "Fishing Complete", "Large Fishing Spot", "Rainbow Dolphinfish"):
            self.assertIsNone(self.pattern().search(text), text)

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


# the live Fishing Request screen with a part-done premium entry and four fresh common requests
PANEL_COMMON = [("Premium Request", 128), ("Night Special: The Sun God's .", 188), ("1/3", 218), ("Refresh", 184),
                ("in 16h", 222), ("Common Request", 298), ("Night Challenge: Octopus and .", 358), ("0/5", 390),
                ("Ongoing", 392), ("Challenge: The Solar Surveyor", 458), ("0/4", 490)]


class TestCommonEntry(unittest.TestCase):
    def test_finds_the_first_open_common_entry_not_the_premium_one(self):
        self.assertEqual(390, common_entry(PANEL_COMMON))

    def test_the_premium_entry_is_still_found(self):
        self.assertEqual(218, premium_entry(PANEL_COMMON))

    def test_a_finished_common_entry_is_still_listed_until_delivered(self):
        done = [b for b in PANEL_COMMON if b[0] != "0/5"] + [("5/5", 390)]
        self.assertEqual(390, common_entry(done))

    def test_requests_given_up_on_are_passed_over(self):
        self.assertEqual(490, common_entry(PANEL_COMMON, skip=1))
        self.assertIsNone(common_entry(PANEL_COMMON, skip=2))

    def test_a_request_to_avoid_is_never_chosen_and_does_not_count_as_skipped(self):
        panel = [("Common Request", 128), ("Challenge: It's Coconut!", 188), ("0/1", 218),
                 ("Challenge: The Solar Surveyor", 288), ("0/4", 318), ("Night Challenge: Quick Slash", 388), ("0/5", 418)]
        self.assertEqual(318, common_entry(panel, avoid=['Coconut']))
        self.assertEqual(418, common_entry(panel, skip=1, avoid=['Coconut']))
        self.assertEqual(218, common_entry(panel))

    def test_the_deliver_button_is_its_own_action(self):
        self.assertEqual('deliver', track_action(['Deliver']))
        self.assertEqual('track', track_action(['Track', 'Refresh with 160']))

    def test_no_common_section(self):
        self.assertIsNone(common_entry(PANEL_COMMON[:5]))


from src.task.FishingTask import objective_needs


class TestObjectiveNeeds(unittest.TestCase):
    def test_names_and_counters_in_their_own_boxes(self):
        boxes = [("Night Challenge: Octopus and Starfish", 710), ("Catch Gooberstar", 768), ("(2/2)", 768),
                 ("Catch Dumbo Octopus", 812), ("(2/3)", 812)]
        self.assertEqual({'gooberstar': 0, 'dumbo octopus': 1}, objective_needs(boxes))

    def test_counter_in_the_same_box(self):
        self.assertEqual({'reinfish': 1}, objective_needs([("Catch Reinfish (0/1)", 768)]))

    def test_counters_without_brackets_as_the_catches_screen_prints_them(self):
        self.assertEqual({'sunfish': 2}, objective_needs([("Catch Sunfish", 800), ("0/2", 801)]))

    def test_no_counters(self):
        self.assertIsNone(objective_needs([("No request being tracked", 710)]))
