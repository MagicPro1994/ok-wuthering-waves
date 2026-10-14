import types
import unittest

import numpy as np

from src.fishing import bait_ui as ui, cargo_grid as cg
from src.fishing.cargo_packer import Placement
from src.fishing.cargo_plan import Catch
from src.task.BaitFishingTask import BaitFishingTask


class Fake(BaitFishingTask):
    """BaitFishingTask with every game-facing method replaced, to test the loop."""

    def __init__(self, counts, max_rounds=0):
        self.counts = list(counts)
        self.config = {'Max Rounds': max_rounds}
        self.rounds = 0
        self.notes = []
        self.info = {}

    def bait_count(self):
        return self.counts.pop(0)

    def play_round(self):
        self.rounds += 1

    def info_set(self, key, value):
        self.info[key] = value

    def log_info(self, message, notify=False, **kwargs):
        self.notes.append(message)

    def fail(self, message):
        raise Exception(message)


class TestLoop(unittest.TestCase):
    def test_runs_until_the_bait_is_gone(self):
        task = Fake([3, 2, 1, 0])
        task.loop()
        self.assertEqual(3, task.rounds)
        self.assertTrue(any('no bait' in n.lower() for n in task.notes))
        self.assertEqual(0, task.info['bait'])

    def test_stops_after_max_rounds(self):
        task = Fake([5, 4, 3, 2], max_rounds=2)
        task.loop()
        self.assertEqual(2, task.rounds)

    def test_fails_when_the_count_does_not_drop_twice(self):
        task = Fake([3, 3, 3])
        with self.assertRaises(Exception) as ctx:
            task.loop()
        self.assertIn('did not drop', str(ctx.exception))

    def test_fails_when_the_count_is_unreadable(self):
        task = Fake([None])
        with self.assertRaises(Exception) as ctx:
            task.loop()
        self.assertIn('unreadable', str(ctx.exception))

    def test_starts_at_zero_without_playing(self):
        task = Fake([0])
        task.loop()
        self.assertEqual(0, task.rounds)


class TestRegistration(unittest.TestCase):
    def test_registered_in_config(self):
        from config import config
        self.assertIn(["src.task.BaitFishingTask", "BaitFishingTask"], config["onetime_tasks"])

    def test_tool_key_check_is_inherited(self):
        task = BaitFishingTask.__new__(BaitFishingTask)

        class Keys:
            def get(self, key):
                return "mouse_x2"

        task.key_config = Keys()
        with self.assertRaises(Exception):
            task.check_tool_key()


class Nudger(BaitFishingTask):
    def __init__(self, states):
        self.states = list(states)
        self.presses = []

    def hold_key(self, key, seconds):
        self.presses.append(key)

    def sleep(self, seconds):
        pass

    def fail(self, message):
        raise Exception(message)


class TestNudge(unittest.TestCase):
    def test_nudges_until_the_condition_holds(self):
        task = Nudger([False, False, True])
        task.nudge_until('w', lambda: task.states.pop(0), tries=5, label='x')
        self.assertEqual(['w', 'w'], task.presses)

    def test_fails_after_the_bound(self):
        task = Nudger([False] * 10)
        with self.assertRaises(Exception) as ctx:
            task.nudge_until('s', lambda: task.states.pop(0), tries=3, label='the dock prompt')
        self.assertIn('the dock prompt', str(ctx.exception))
        self.assertEqual(3, len(task.presses))


class Catcher(BaitFishingTask):
    def __init__(self, puff):
        self.puff = puff
        self.calls = []

    def try_sweet_puff(self):
        self.calls.append('puff')
        return self.puff

    def fish_normally(self):
        self.calls.append('normal')


class TestCatchFish(unittest.TestCase):
    def test_uses_sweet_puff_when_available(self):
        task = Catcher(True)
        task.catch_fish()
        self.assertEqual(['puff'], task.calls)

    def test_falls_back_to_normal_fishing(self):
        task = Catcher(False)
        task.catch_fish()
        self.assertEqual(['puff', 'normal'], task.calls)


class Surveyor(BaitFishingTask):
    def __init__(self, shapes):
        self.shapes = shapes          # slot -> list of cells (a missing slot has no preview)
        self.clicked = []
        self.current = None

    def click_at(self, fx, fy, after_sleep=0.4):
        self.clicked.append((fx, fy))
        slots = [cg.card_center(s) for s in range(cg.MAX_CARDS)]
        self.current = min(range(cg.MAX_CARDS), key=lambda s: abs(slots[s][0] - fx) + abs(slots[s][1] - fy))

    def rgb_frame(self):
        frame = np.full((1080, 1920, 3), 52, np.uint8)
        for r, c in self.shapes.get(self.current, []):
            x, y = cg.cell_center(r, c)
            frame[int(y * 1080) - 30:int(y * 1080) + 30, int(x * 1920) - 30:int(x * 1920) + 30] = (90, 160, 230)
        return frame

    def texts(self, x=0, y=0, to_x=1, to_y=1):
        return ["1,200"]

    def sleep(self, seconds):
        pass


class TestSurvey(unittest.TestCase):
    def test_reads_shapes_and_stops_at_the_first_empty_slot(self):
        shapes = {0: [(2, 2), (2, 3)], 1: [(3, 3), (4, 3), (4, 4)]}
        task = Surveyor(shapes)
        base = np.full((1080, 1920, 3), 52, np.uint8)
        catches = task.survey_catches(base)
        self.assertEqual([0, 1], [c.slot for c in catches])
        self.assertEqual(frozenset({(2, 2), (2, 3)}), catches[0].cells)
        self.assertEqual(1200, catches[0].value)
        self.assertEqual(3, len(task.clicked))     # slot 2 was probed and found empty


class Placer(Surveyor):
    """Cards preview their shape when clicked; `space` commits the preview to the cargo for good."""

    def __init__(self, shapes):
        super().__init__(shapes)
        self.placed = set()
        self.keys = []
        self.notes = []

    def rgb_frame(self):
        frame = super().rgb_frame()
        for r, c in self.placed:
            x, y = cg.cell_center(r, c)
            frame[int(y * 1080) - 30:int(y * 1080) + 30, int(x * 1920) - 30:int(x * 1920) + 30] = (90, 160, 230)
        return frame

    def send_key(self, key, after_sleep=0.2, **kwargs):
        self.keys.append(key)
        if key == 'space':
            self.placed |= set(self.shapes[self.current])
            self.current = None

    def log_info(self, message, notify=False, **kwargs):
        self.notes.append(message)


class TestPlaceCatch(unittest.TestCase):
    def test_second_catch_is_placed_after_the_first(self):
        shapes = {1: [(2, 2), (2, 3)], 0: [(5, 5), (6, 5)]}
        task = Placer(shapes)
        for slot in (1, 0):
            cells = frozenset(shapes[slot])
            task.place_catch(Catch(slot, cells, 100), Placement(0, cells, min(cells)))
        self.assertEqual(['space', 'space'], task.keys)
        self.assertEqual({(2, 2), (2, 3), (5, 5), (6, 5)}, task.placed)


class TestSurveyValue(unittest.TestCase):
    def test_unreadable_value_is_logged_and_kept_at_zero(self):
        task = Placer({0: [(2, 2)]})
        task.texts = lambda *a, **k: ['??']
        catches = task.survey_catches(np.full((1080, 1920, 3), 52, np.uint8))
        self.assertEqual(0, catches[0].value)
        self.assertTrue(any('value' in n for n in task.notes))


class TestPlaceCatchResult(unittest.TestCase):
    def test_returns_true_when_placed(self):
        task = Placer({1: [(2, 2), (2, 3)]})
        cells = frozenset({(2, 2), (2, 3)})
        self.assertTrue(task.place_catch(Catch(1, cells, 5), Placement(0, cells, (2, 2))))

    def test_returns_false_when_it_cannot_rotate_to_the_shape(self):
        task = Placer({1: [(2, 2), (2, 3)]})
        want = frozenset({(2, 2), (3, 2), (4, 2)})
        self.assertFalse(task.place_catch(Catch(1, frozenset({(2, 2), (2, 3)}), 5), Placement(0, want, (2, 2))))
        self.assertNotIn('space', task.keys)

    def test_logs_a_stray_preview_from_an_earlier_card(self):
        task = Placer({0: [(2, 2)], 1: [(5, 5)]})
        survey_base = np.full((1080, 1920, 3), 52, np.uint8)
        task.current = 0                     # card 0 is still previewing
        cells = frozenset({(5, 5)})
        task.place_catch(Catch(1, cells, 5), Placement(0, cells, (5, 5)), survey_base)
        self.assertTrue(any('earlier card' in n for n in task.notes))


class Loader(Placer):
    def __init__(self, shapes, results):
        super().__init__(shapes)
        self.results = list(results)
        self.tried = []

    def cargo_screen_open(self):
        return True

    def wait_until(self, condition, time_out=10, **kwargs):
        return condition()

    def info_set(self, key, value):
        pass

    def survey_catches(self, base):
        return [Catch(0, frozenset({(2, 2)}), 100), Catch(1, frozenset({(5, 5)}), 200)]

    def place_catch(self, catch, placement, survey_base=None, placed=frozenset()):
        self.tried.append(catch.slot)
        return self.results.pop(0)


class TestLoadCargo(unittest.TestCase):
    def test_stops_after_the_first_unplaced_catch_but_still_finishes(self):
        task = Loader({}, [False, True])
        task.load_cargo()
        self.assertEqual([1], task.tried)
        self.assertTrue(any('not placed' in n for n in task.notes))
        self.assertEqual(ui.FINISH_AT, task.clicked[-1])

    def test_places_everything_when_all_succeed(self):
        task = Loader({}, [True, True])
        task.load_cargo()
        self.assertEqual([1, 0], task.tried)
        self.assertEqual(ui.FINISH_AT, task.clicked[-1])


class Prompter(BaitFishingTask):
    height = 1080

    def __init__(self, screens):
        self.screens = list(screens)      # per ocr call: list of (text, y)
        self.scrolls = 0
        self.failed = None

    def ocr(self, *args, **kwargs):
        rows = self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
        return [types.SimpleNamespace(name=t, y=y * 1080 - 10, height=20) for t, y in rows]

    def scroll_relative(self, *args):
        self.scrolls += 1

    def sleep(self, seconds):
        pass

    def fail(self, message):
        self.failed = message
        raise Exception(message)


class TestSelectEntry(unittest.TestCase):
    def test_retries_when_the_entry_is_missing_once(self):
        task = Prompter([[("junk", 0.5)], [("F", 0.6), ("Fish", 0.6)]])
        task.select_entry(r'^Fish$', 'Fish')
        self.assertEqual(0, task.scrolls)

    def test_scrolls_until_selected_and_uses_the_fifth_check(self):
        not_selected = [("Fish", 0.6), ("Return to the dock", 0.5)]
        selected = [("Fish", 0.6), ("F", 0.6)]
        task = Prompter([not_selected] * 4 + [selected])
        task.select_entry(r'^Fish$', 'Fish')
        self.assertEqual(4, task.scrolls)

    def test_fails_after_bounded_tries(self):
        task = Prompter([[("junk", 0.5)]])
        with self.assertRaises(Exception):
            task.select_entry(r'^Fish$', 'Fish')
        self.assertIn('not found', task.failed)

    def test_merged_badge_is_selected(self):
        task = Prompter([[("[F] Fish", 0.6)]])
        task.select_entry(r'^Fish$', 'Fish')


class TestSetSail(unittest.TestCase):
    def make(self, shows, clicks_ok=True):
        task = Surveyor({})
        task.has_text = lambda *a, **k: shows
        task.wait_until = lambda cond, time_out=10, **k: cond()
        task.click_ocr_text = lambda *a, **k: clicks_ok
        task.fail = lambda m: (_ for _ in ()).throw(Exception(m))
        return task

    def test_clicks_only_the_final_button(self):
        task = self.make(True)
        task.set_sail()
        self.assertEqual([BaitFishingTask.SET_SAIL_AT], task.clicked)

    def test_fails_when_set_sail_never_shows(self):
        with self.assertRaises(Exception):
            self.make(False).set_sail()

    def test_fails_when_the_click_misses(self):
        with self.assertRaises(Exception):
            self.make(True, clicks_ok=False).set_sail()
