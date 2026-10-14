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
    """A Catches screen: `shapes` maps slot -> cells, `values` slot -> value text.

    Clicking a slot with a card shows that fish as a coloured draft on the grid; clicking a slot without one leaves the
    draft as it is. Cells in `placed` are part of the cargo and always coloured.
    """

    def __init__(self, shapes, values=None):
        self.shapes = dict(shapes)
        self.values = values if values is not None else {slot: 1200 for slot in shapes}
        self.clicked = []
        self.draft = frozenset()
        self.selected = None
        self.placed = set()
        self.notes = []
        self.keys = []

    def screenshot(self, name=None, **kwargs):
        pass

    def info_set(self, key, value):
        pass

    def log_info(self, message, notify=False, **kwargs):
        self.notes.append(message)

    def fail(self, message):
        raise Exception(message)

    def slot_at(self, fx, fy):
        slots = [cg.card_center(s) for s in range(cg.MAX_CARDS)]
        return min(range(cg.MAX_CARDS), key=lambda s: abs(slots[s][0] - fx) + abs(slots[s][1] - fy))

    def click_at(self, fx, fy, after_sleep=0.4):
        self.clicked.append((fx, fy))
        slot = self.slot_at(fx, fy)
        if slot in self.shapes:
            self.selected = slot
            self.draft = frozenset(self.shapes[slot])

    def rgb_frame(self):
        frame = np.full((1080, 1920, 3), 52, np.uint8)
        for r, c in set(self.draft) | set(self.placed):
            x, y = cg.cell_center(r, c)
            frame[int(y * 1080) - 30:int(y * 1080) + 30, int(x * 1920) - 30:int(x * 1920) + 30] = (90, 160, 230)
        return frame

    def texts(self, x=0, y=0, to_x=1, to_y=1):
        for slot, value in self.values.items():
            if (x, y, to_x, to_y) == cg.card_box(slot):
                return [f'{value:,}']
        return []

    def send_key(self, key, after_sleep=0.2, **kwargs):
        self.keys.append(key)

    def sleep(self, seconds):
        pass


class TestSurvey(unittest.TestCase):
    def test_reads_shapes_and_values_and_stops_at_the_first_empty_slot(self):
        shapes = {0: [(2, 2), (2, 3)], 1: [(3, 3), (4, 3), (4, 4)]}
        task = Surveyor(shapes)
        catches = task.survey_catches()
        self.assertEqual([0, 1], [c.slot for c in catches])
        self.assertEqual(frozenset({(2, 2), (2, 3)}), catches[0].cells)
        self.assertEqual(1200, catches[0].value)
        self.assertEqual(3, len(task.clicked))     # slot 2 was probed: no value, the draft is still slot 1's

    def test_stops_at_a_slot_with_no_value_and_no_draft(self):
        task = Surveyor({})
        self.assertEqual([], task.survey_catches())
        self.assertEqual(1, len(task.clicked))

    def test_a_full_list_reads_every_slot(self):
        shapes = {s: [(s, 1)] for s in range(cg.MAX_CARDS)}
        self.assertEqual(cg.MAX_CARDS, len(Surveyor(shapes).survey_catches()))

    def test_fails_when_a_value_is_read_but_no_draft_shows(self):
        task = Surveyor({0: [(2, 2)]}, values={0: 100, 1: 250})     # slot 1 reads a value but selects nothing
        click = task.click_at

        def click_at(fx, fy, after_sleep=0.4):
            click(fx, fy, after_sleep)
            if task.slot_at(fx, fy) == 1:
                task.draft = frozenset()

        task.click_at = click_at
        with self.assertRaises(Exception) as ctx:
            task.survey_catches()
        self.assertIn('slot 1', str(ctx.exception))

    def test_fails_when_the_first_card_has_a_value_but_no_draft(self):
        task = Surveyor({}, values={0: 100})
        with self.assertRaises(Exception) as ctx:
            task.survey_catches()
        self.assertIn('slot 0', str(ctx.exception))


class TestSurveyValue(unittest.TestCase):
    def test_unreadable_value_with_a_new_draft_uses_the_cell_count(self):
        task = Surveyor({0: [(2, 2), (2, 3)]}, values={})
        catches = task.survey_catches()
        self.assertEqual(2, catches[0].value)
        self.assertTrue(any('value' in n for n in task.notes))


class Placer(Surveyor):
    """Dragging moves the draft; Space confirms it: the cells become cargo, the card leaves, the Cargo counter rises."""

    def __init__(self, shapes, values=None, confirm=True):
        super().__init__(shapes, values)
        self.used = 7
        self.confirm = confirm      # False: Space does nothing
        self.drags = []
        self.rotations = None       # successive draft shapes shown by `r`, if set
        self.slip = (0, 0)          # cells the drop misses the target by
        self.real = self
        self.events = []

    def click_at(self, fx, fy, after_sleep=0.4):
        super().click_at(fx, fy, after_sleep)
        self.events.append('click')

    def texts(self, x=0, y=0, to_x=1, to_y=1):
        if (x, y, to_x, to_y) == cg.CARGO_COUNT_BOX:
            self.events.append('counter')
            return [f'Cargo: {self.used}/52']
        return super().texts(x, y, to_x, to_y)

    def send_key(self, key, after_sleep=0.2, **kwargs):
        super().send_key(key, after_sleep)
        self.events.append(key)
        if key == 'r' and self.rotations:
            self.draft = frozenset(self.rotations.pop(0))
        if key == 'space' and self.confirm and self.draft:
            self.placed |= self.draft
            self.used += len(self.draft)
            self.shapes.pop(self.selected, None)
            self.draft = frozenset()

    def drag(self, x0, y0, x1, y1, duration):
        self.events.append('drag')
        self.drags.append(((x0, y0), (x1, y1)))
        # the draft moves by the distance between the two cells
        dr = round((y1 - y0) * 1080 / cg.CELL_PX) + self.slip[0]
        dc = round((x1 - x0) * 1920 / cg.CELL_PX) + self.slip[1]
        self.draft = frozenset((r + dr, c + dc) for r, c in self.draft)

    def wait_until(self, condition, time_out=10, **kwargs):
        return condition()


class TestPlaceCatch(unittest.TestCase):
    def test_drags_the_draft_onto_the_plan_confirms_and_verifies_the_counter(self):
        cells = frozenset({(2, 2), (2, 3)})
        task = Placer({1: sorted(cells)})
        want = frozenset({(4, 4), (4, 5)})
        self.assertTrue(task.place_catch(Catch(1, cells, 100), Placement(0, want, (4, 4))))
        self.assertEqual([(cg.cell_center(2, 2), cg.cell_center(4, 4))], task.drags)
        self.assertEqual(9, task.used)
        self.assertEqual(want, task.placed)
        self.assertEqual(['click', 'counter', 'drag', 'space', 'counter'], task.events)
        self.assertNotIn('t', task.keys)

    def test_a_draft_already_on_target_is_confirmed_without_a_drag(self):
        cells = frozenset({(2, 2), (2, 3)})
        task = Placer({0: sorted(cells)})
        self.assertTrue(task.place_catch(Catch(0, cells, 100), Placement(0, cells, (2, 2))))
        self.assertEqual([], task.drags)
        self.assertEqual(['space'], task.keys)

    def test_rotates_by_reading_the_draft_again(self):
        flat = [(2, 2), (2, 3)]
        upright = [(2, 2), (3, 2)]
        task = Placer({1: flat})
        task.rotations = [flat, upright]
        want = frozenset({(5, 5), (6, 5)})
        self.assertTrue(task.place_catch(Catch(1, frozenset(flat), 5), Placement(0, want, (5, 5))))
        self.assertEqual(['r', 'r', 'space'], task.keys)
        self.assertEqual(cg.cell_center(2, 2), task.drags[0][0])
        self.assertEqual(want, task.placed)

    def test_returns_false_without_confirming_when_the_drop_misses(self):
        cells = frozenset({(2, 2), (2, 3)})
        task = Placer({1: sorted(cells)})
        task.slip = (0, 1)
        self.assertFalse(task.place_catch(Catch(1, cells, 100), Placement(0, frozenset({(4, 4), (4, 5)}), (4, 4))))
        self.assertNotIn('space', task.keys)
        self.assertTrue(any('did not land' in n for n in task.notes))

    def test_returns_false_when_the_counter_does_not_rise(self):
        cells = frozenset({(2, 2), (2, 3)})
        task = Placer({1: sorted(cells)}, confirm=False)
        self.assertFalse(task.place_catch(Catch(1, cells, 100), Placement(0, frozenset({(4, 4), (4, 5)}), (4, 4))))
        self.assertTrue(any('counter' in n for n in task.notes))

    def test_returns_false_when_the_counter_is_unreadable(self):
        cells = frozenset({(2, 2)})
        task = Placer({1: [(2, 2)]})
        task.texts = lambda *a, **k: []
        self.assertFalse(task.place_catch(Catch(1, cells, 5), Placement(0, cells, (2, 2))))
        self.assertNotIn('space', task.keys)

    def test_returns_false_when_the_card_shows_no_draft(self):
        task = Placer({})
        cells = frozenset({(2, 2)})
        self.assertFalse(task.place_catch(Catch(1, cells, 5), Placement(0, cells, (2, 2))))
        self.assertEqual([], task.keys)

    def test_returns_false_when_it_cannot_rotate_to_the_shape(self):
        task = Placer({1: [(2, 2), (2, 3)]})
        want = frozenset({(2, 2), (3, 2), (4, 2)})
        self.assertFalse(task.place_catch(Catch(1, frozenset({(2, 2), (2, 3)}), 5), Placement(0, want, (2, 2))))
        self.assertEqual(['r'] * 4, task.keys)
        self.assertEqual([], task.drags)

    def test_the_first_placement_after_a_survey_ignores_the_draft_the_survey_left(self):
        shapes = {0: [(0, 0), (0, 1)], 1: [(0, 0), (1, 0)]}
        task = Placer(shapes)
        catches = task.survey_catches()                  # the last probed card's draft stays up
        self.assertTrue(task.draft)
        want = frozenset({(3, 3), (4, 3)})
        self.assertTrue(task.place_catch(catches[1], Placement(0, want, (3, 3))))
        self.assertEqual(want, task.placed)


class Loader(Placer):
    """load_cargo with scripted surveys; every pass returns the next list of catches."""

    def __init__(self, surveys, results):
        super().__init__({})
        self.surveys = list(surveys)
        self.results = list(results)
        self.tried = []

    def cargo_screen_open(self):
        return True

    def survey_catches(self):
        return self.surveys.pop(0)

    def place_catch(self, catch, placement):
        self.tried.append(catch.slot)
        return self.results.pop(0)


def two_catches():
    return [Catch(0, frozenset({(2, 2)}), 100), Catch(1, frozenset({(5, 5)}), 200)]


def full_list():
    return [Catch(s, frozenset({(s, s + 1)}), 100 + s) for s in range(cg.MAX_CARDS)]


class TestLoadCargo(unittest.TestCase):
    def test_fails_without_finishing_when_a_catch_cannot_be_placed(self):
        task = Loader([two_catches()], [False, True])
        with self.assertRaises(Exception) as ctx:
            task.load_cargo()
        self.assertIn('Finish not pressed', str(ctx.exception))
        self.assertEqual([1], task.tried)
        self.assertNotIn(ui.FINISH_AT, task.clicked)

    def test_finish_can_be_left_to_the_player(self):
        task = Loader([two_catches()], [True, True])
        task.load_cargo(finish=False)
        self.assertNotIn(ui.FINISH_AT, task.clicked)

    def test_places_everything_when_all_succeed_in_one_pass(self):
        task = Loader([two_catches()], [True, True])
        task.load_cargo()
        self.assertEqual([1, 0], task.tried)
        self.assertEqual(ui.FINISH_AT, task.clicked[-1])
        self.assertEqual([], task.surveys)

    def test_a_full_list_gets_another_pass_until_it_runs_short(self):
        task = Loader([full_list(), two_catches(), two_catches()], [True] * 20)
        task.load_cargo()
        self.assertEqual(1, len(task.surveys))      # the third survey was never needed
        self.assertEqual(ui.FINISH_AT, task.clicked[-1])

    def test_a_full_list_that_fits_nothing_is_not_surveyed_again(self):
        every = frozenset((r, c) for r in range(7) for c in range(8))
        task = Loader([[Catch(s, every, 1) for s in range(cg.MAX_CARDS)], two_catches()], [])
        task.load_cargo()
        self.assertEqual([], task.tried)
        self.assertEqual(1, len(task.surveys))
        self.assertEqual(ui.FINISH_AT, task.clicked[-1])

    def test_passes_are_bounded(self):
        task = Loader([full_list() for _ in range(10)], [True] * 100)
        task.load_cargo()
        self.assertEqual(10 - task.LOAD_PASSES, len(task.surveys))

    def test_failure_in_a_later_pass_does_not_finish(self):
        task = Loader([full_list(), two_catches()], [True] * cg.MAX_CARDS + [True, False])
        with self.assertRaises(Exception) as ctx:
            task.load_cargo()
        self.assertIn('Finish not pressed', str(ctx.exception))
        self.assertNotIn(ui.FINISH_AT, task.clicked)


class TestCargoHelper(unittest.TestCase):
    def test_registered_in_config(self):
        from config import config
        self.assertIn(["src.task.CargoHelperTask", "CargoHelperTask"], config["onetime_tasks"])

    def test_arranges_the_cargo_without_pressing_finish(self):
        from src.task import CargoHelperTask as module

        class Stub(module.CargoHelperTask):
            hwnd = types.SimpleNamespace(hwnd=1)

        task = Stub.__new__(Stub)
        calls = []
        task.load_cargo = lambda finish=True: calls.append(finish)
        task.log_info = lambda *a, **k: calls.append('log')
        original = (module.WWOneTimeTask.run, module.RealInput)
        module.WWOneTimeTask.run = lambda self: None
        module.RealInput = lambda hwnd: 'real'
        try:
            task.run()
        finally:
            module.WWOneTimeTask.run, module.RealInput = original
        self.assertEqual([False, 'log'], calls)
        self.assertEqual('real', task.real)


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


class Equipper(BaitFishingTask):
    """Plays the utility wheel: `wheel` is the open/closed state sequence seen by wheel_open."""

    class _Keys:
        def get(self, key):
            return 'tab'

    key_config = _Keys()

    def __init__(self, wheel):
        self.wheel = list(wheel)
        self.events = []

    def wheel_open(self):
        return self.wheel.pop(0) if len(self.wheel) > 1 else self.wheel[0]

    def send_key_down(self, key, after_sleep=0):
        self.events.append(('down', key))

    def send_key_up(self, key, after_sleep=0):
        self.events.append(('up', key))

    def point_cursor(self, fx, fy):
        self.events.append(('point', round(fx, 3), round(fy, 3)))

    def sleep(self, seconds):
        pass

    def wait_until(self, condition, time_out=10):
        return condition()

    def fail(self, message):
        raise Exception(message)


class TestEquip(unittest.TestCase):
    def test_holds_the_key_points_at_the_slot_and_releases(self):
        task = Equipper([True, False])
        task.equip('baiting')
        self.assertEqual([('down', 'tab'), ('point', 0.601, 0.319), ('up', 'tab')], task.events)

    def test_releases_the_key_when_the_wheel_never_opens(self):
        task = Equipper([False])
        with self.assertRaises(Exception) as ctx:
            task.equip('baiting')
        self.assertIn('did not open', str(ctx.exception))
        self.assertEqual([('down', 'tab'), ('up', 'tab')], task.events)

    def test_fails_when_the_wheel_never_closes(self):
        with self.assertRaises(Exception) as ctx:
            Equipper([True]).equip('sweet_puff')
        self.assertIn('did not close', str(ctx.exception))


class Launcher(BaitFishingTask):
    class _Keys:
        def get(self, key):
            return 't'

    key_config = _Keys()

    def __init__(self, confirm_found):
        self.confirm_found = confirm_found
        self.events = []

    def info_set(self, *args, **kwargs):
        pass

    def equip(self, name):
        self.events.append(('equip', name))

    def send_key(self, key, after_sleep=0):
        self.events.append(('key', key))

    def wait_until(self, condition, time_out=10):
        return True

    def click_ocr_text(self, pattern, *region):
        self.events.append(('confirm', pattern))
        return self.confirm_found

    def sleep(self, seconds):
        pass

    def fail(self, message):
        raise Exception(message)


class TestLaunchBait(unittest.TestCase):
    def test_equips_baiting_presses_the_tool_key_and_clicks_confirm_by_text(self):
        task = Launcher(True)
        task.launch_bait()
        self.assertEqual(['equip', 'key', 'confirm'], [e[0] for e in task.events])
        self.assertEqual(('equip', 'baiting'), task.events[0])
        self.assertEqual(('key', 't'), task.events[1])

    def test_fails_when_confirm_is_not_found(self):
        with self.assertRaises(Exception) as ctx:
            Launcher(False).launch_bait()
        self.assertIn('Confirm', str(ctx.exception))


class Docking(Prompter):
    """return_to_dock with a scripted prompt list."""

    def __init__(self, texts):
        super().__init__([])
        self.texts_seen = texts
        self.selected = []

    def prompt_texts(self):
        return self.texts_seen

    def nudge_until(self, key, done, tries, label):
        pass

    def select_entry(self, pattern, label):
        self.selected.append(label)

    def info_set(self, key, value):
        pass


class TestReturnToDock(unittest.TestCase):
    def test_a_lone_entry_is_not_scrolled_to(self):
        task = Docking(["Return to the dock"])
        task.return_to_dock()
        self.assertEqual([], task.selected)

    def test_two_entries_select_the_dock_one(self):
        task = Docking(["Return to the dock", "Fish"])
        task.return_to_dock()
        self.assertEqual(['Return to the dock'], task.selected)
