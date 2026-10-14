import random
import unittest

from src.fishing import human_input as hi
from src.fishing.bait_logic import (RoundGuard, dialog_open, entry_selected, parse_count, prompt_state,
                                    sandworm_launched)


class TestParseCount(unittest.TestCase):
    def test_reads_the_count_and_skips_ratio_and_key(self):
        self.assertEqual(189, parse_count(["189", "0/3", "T"]))

    def test_count_zero_is_zero_not_none(self):
        self.assertEqual(0, parse_count(["0", "0/3"]))

    def test_unreadable_is_none(self):
        self.assertIsNone(parse_count(["0/3", "T"]))
        self.assertIsNone(parse_count([]))

    def test_ignores_digits_inside_words(self):
        self.assertIsNone(parse_count(["x2 speed"]))


class TestMessages(unittest.TestCase):
    def test_dialog(self):
        self.assertTrue(dialog_open(["Use Bait", "Use Sandworm as bait?", "Cancel", "Confirm"]))
        self.assertFalse(dialog_open(["Fishing Complete"]))

    def test_launched(self):
        self.assertTrue(sandworm_launched(["Sandworm launched"]))
        self.assertFalse(sandworm_launched(["Sandworm", "1"]))


class TestPromptState(unittest.TestCase):
    def test_return_only(self):
        s = prompt_state(["[F] Return to the dock"])
        self.assertTrue(s.return_dock)
        self.assertFalse(s.fish)

    def test_both(self):
        s = prompt_state(["Return to the dock", "Fish"])
        self.assertTrue(s.return_dock and s.fish)

    def test_fishing_complete_is_not_a_fish_prompt(self):
        self.assertFalse(prompt_state(["Fishing Complete"]).fish)

    def test_nothing(self):
        s = prompt_state([])
        self.assertFalse(s.return_dock or s.fish)


class TestEntrySelected(unittest.TestCase):
    def test_selected_when_key_badge_on_same_row(self):
        boxes = [("F", 0.60), ("Fish", 0.605), ("Return to the dock", 0.54)]
        self.assertTrue(entry_selected(boxes, r"^Fish$"))
        self.assertFalse(entry_selected(boxes, r"Return to the dock"))

    def test_missing_entry_is_none(self):
        self.assertIsNone(entry_selected([("F", 0.5)], r"^Fish$"))


class TestRoundGuard(unittest.TestCase):
    def test_a_drop_resets_the_stalls(self):
        g = RoundGuard(2)
        self.assertTrue(g.record(10, 10))
        self.assertTrue(g.record(10, 9))
        self.assertTrue(g.record(9, 9))

    def test_two_stalls_in_a_row_stop(self):
        g = RoundGuard(2)
        self.assertTrue(g.record(10, 10))
        self.assertFalse(g.record(10, 11))


class TestNudge(unittest.TestCase):
    def test_nudge_press_is_short_and_uneven(self):
        values = {hi.nudge_press(random.Random(i)) for i in range(20)}
        self.assertTrue(all(0.35 <= v <= 0.8 for v in values))
        self.assertGreater(len(values), 10)
