import re
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
        self.events = []
        self.draft_is_valid = True
        self.autoplaced = []
        self.q_works = True

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
        self.events.append(('click', slot))
        if self.draft and self.draft_is_valid:
            # clicking another card while a valid draft is up auto-places it
            self.placed |= self.draft
            self.autoplaced.append(self.selected)
            self.draft = frozenset()
        if slot in self.shapes:
            self.selected = slot
            self.draft = frozenset(self.shapes[slot])

    def rgb_frame(self):
        frame = np.full((1080, 1920, 3), 52, np.uint8)
        # while a draft is up the game dims every placed fish
        for cells, colour in ((self.placed, (60, 107, 153) if self.draft else (90, 160, 230)), (self.draft, (90, 160, 230))):
            for r, c in cells:
                x, y = cg.cell_center(r, c)
                frame[int(y * 1080) - 30:int(y * 1080) + 30, int(x * 1920) - 30:int(x * 1920) + 30] = colour
        if self.draft:
            frame[945:1025, 1495:1575] = (128, 175, 129)     # the green check of the Space button
        return frame

    def texts(self, x=0, y=0, to_x=1, to_y=1):
        for slot, value in self.values.items():
            if (x, y, to_x, to_y) == cg.card_box(slot):
                return [f'{value:,}']
        return []

    def send_key(self, key, after_sleep=0.2, **kwargs):
        self.keys.append(key)
        self.events.append(key)
        if key == 'q' and self.q_works:
            self.draft = frozenset()       # back to the list

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


class TestSurveyReturnsDrafts(unittest.TestCase):
    def test_every_draft_goes_back_to_the_list_before_the_next_click(self):
        task = Surveyor({0: [(2, 2), (2, 3)], 1: [(3, 3), (4, 3)], 2: [(5, 5)]})
        catches = task.survey_catches()
        self.assertEqual([0, 1, 2], [c.slot for c in catches])
        self.assertEqual([('click', 0), 'q', ('click', 1), 'q', ('click', 2), 'q', ('click', 3)], task.events)
        self.assertEqual([], task.autoplaced)
        self.assertEqual(set(), task.placed)

    def test_the_survey_stops_at_the_first_slot_with_neither_draft_nor_value(self):
        task = Surveyor({0: [(2, 2)]})
        self.assertEqual([0], [c.slot for c in task.survey_catches()])
        self.assertEqual(2, len(task.clicked))
        self.assertEqual(['q'], task.keys)

    def test_fails_when_q_cannot_clear_a_draft(self):
        task = Surveyor({0: [(2, 2)]})
        task.q_works = False
        with self.assertRaises(Exception) as ctx:
            task.survey_catches()
        self.assertIn('could not clear the draft', str(ctx.exception))
        self.assertNotIn('t', task.keys)


class TestSurveyOverPlacedFish(unittest.TestCase):
    def test_dimmed_placed_fish_are_not_part_of_the_draft(self):
        task = Surveyor({0: [(0, 0), (0, 1)], 1: [(0, 0), (1, 0), (1, 1)]})
        task.placed = {(3, 3), (3, 4), (4, 4)}
        catches = task.survey_catches()
        self.assertEqual([frozenset({(0, 0), (0, 1)}), frozenset({(0, 0), (1, 0), (1, 1)})], [c.cells for c in catches])


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

    def click_at(self, fx, fy, after_sleep=0.4):
        super().click_at(fx, fy, after_sleep)

    def texts(self, x=0, y=0, to_x=1, to_y=1):
        if (x, y, to_x, to_y) == cg.CARGO_COUNT_BOX:
            self.events.append('counter')
            return [f'Cargo: {self.used}/52']
        return super().texts(x, y, to_x, to_y)

    def send_key(self, key, after_sleep=0.2, **kwargs):
        super().send_key(key, after_sleep)
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
        self.assertEqual([('click', 1), 'counter', 'drag', 'space', 'counter'], task.events)
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
        self.assertEqual(['q'], task.keys)
        self.assertFalse(task.draft)
        self.assertTrue(any('did not land' in n for n in task.notes))

    def test_returns_false_when_the_counter_does_not_rise(self):
        cells = frozenset({(2, 2), (2, 3)})
        task = Placer({1: sorted(cells)}, confirm=False)
        self.assertFalse(task.place_catch(Catch(1, cells, 100), Placement(0, frozenset({(4, 4), (4, 5)}), (4, 4))))
        self.assertTrue(any('counter' in n for n in task.notes))
        self.assertEqual(['space', 'q'], task.keys)
        self.assertFalse(task.draft)

    def test_returns_false_when_the_counter_is_unreadable(self):
        cells = frozenset({(2, 2)})
        task = Placer({1: [(2, 2)]})
        task.texts = lambda *a, **k: []
        self.assertFalse(task.place_catch(Catch(1, cells, 5), Placement(0, cells, (2, 2))))
        self.assertNotIn('space', task.keys)
        self.assertEqual(['q'], task.keys)

    def test_returns_false_when_the_card_shows_no_draft(self):
        task = Placer({})
        cells = frozenset({(2, 2)})
        self.assertFalse(task.place_catch(Catch(1, cells, 5), Placement(0, cells, (2, 2))))
        self.assertEqual([], task.keys)

    def test_returns_false_when_it_cannot_rotate_to_the_shape(self):
        task = Placer({1: [(2, 2), (2, 3)]})
        want = frozenset({(2, 2), (3, 2), (4, 2)})
        self.assertFalse(task.place_catch(Catch(1, frozenset({(2, 2), (2, 3)}), 5), Placement(0, want, (2, 2))))
        self.assertEqual(['r'] * 4 + ['q'], task.keys)
        self.assertFalse(task.draft)
        self.assertEqual([], task.drags)


class DraftClearer(Surveyor):
    """clear_draft with a scripted draft_active: `q` removes the draft unless `stuck`."""

    def __init__(self, active, stuck=False):
        super().__init__({})
        self.active = active
        self.stuck = stuck

    def send_key(self, key, after_sleep=0.2, **kwargs):
        super().send_key(key, after_sleep)
        if key == 'q' and not self.stuck:
            self.active = False


class TestClearDraft(unittest.TestCase):
    def setUp(self):
        self.real_active = cg.draft_active

    def tearDown(self):
        cg.draft_active = self.real_active

    def run_clear(self, task):
        cg.draft_active = lambda frame: task.active
        task.clear_draft()

    def test_a_draft_is_returned_to_the_list_with_q(self):
        task = DraftClearer(True)
        self.run_clear(task)
        self.assertEqual(['q'], task.keys)

    def test_no_draft_presses_nothing(self):
        task = DraftClearer(False)
        self.run_clear(task)
        self.assertEqual([], task.keys)

    def test_fails_when_q_never_clears_it(self):
        task = DraftClearer(True, stuck=True)
        with self.assertRaises(Exception) as ctx:
            self.run_clear(task)
        self.assertIn('could not clear the draft', str(ctx.exception))
        self.assertEqual(['q'] * 3, task.keys)
        self.assertNotIn('t', task.keys)


class TestDraftClearedAroundTheBoard(unittest.TestCase):
    def test_load_cargo_clears_the_draft_at_every_pass_start_and_before_finish(self):
        events = []

        class Task(Loader):
            def clear_draft(self):
                events.append('clear')

            def survey_catches(self):
                events.append('survey')
                return super().survey_catches()

            def click_at(self, fx, fy, after_sleep=0.4):
                super().click_at(fx, fy, after_sleep)
                if (fx, fy) == ui.FINISH_AT:
                    events.append('finish')

        Task([two_catches()], [True, True]).load_cargo()
        self.assertEqual(['clear', 'survey', 'clear', 'finish'], events)

    def test_place_catch_clears_a_leftover_draft_before_taking_its_base(self):
        task = Placer({0: [(2, 2)]})
        cleared = []
        task.clear_draft = lambda: cleared.append(task.events[:])
        cells = frozenset({(2, 2)})
        task.place_catch(Catch(0, cells, 5), Placement(0, cells, (2, 2)))
        self.assertEqual([[]], cleared)         # before the first click


class Loader(Placer):
    """load_cargo with scripted surveys; every pass returns the next list of catches."""

    def __init__(self, surveys, results):
        super().__init__({})
        self.surveys = list(surveys)
        self.results = list(results)
        self.tried = []
        self.sales = []             # results of the scripted quick sales
        self.sold = 0

    def cargo_screen_open(self):
        return True

    def quick_sale(self):
        self.sold += 1
        return self.sales.pop(0) if self.sales else False

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


class TestLoadCargoQuickSale(unittest.TestCase):
    def leftover_list(self):
        every = frozenset((r, c) for r in range(7) for c in range(8))
        return [Catch(0, frozenset({(2, 2)}), 100), Catch(1, every, 5)]

    def test_a_successful_quick_sale_runs_another_pass(self):
        task = Loader([self.leftover_list(), two_catches()], [True, True, True])
        task.sales = [True]
        task.load_cargo()
        self.assertEqual(1, task.sold)
        self.assertEqual([], task.surveys)
        self.assertTrue(any('fish left over, trying Quick Sale' in n for n in task.notes))
        self.assertEqual(ui.FINISH_AT, task.clicked[-1])

    def test_a_failed_quick_sale_stops_the_passes(self):
        task = Loader([self.leftover_list(), two_catches()], [True])
        task.sales = [False]
        task.load_cargo()
        self.assertEqual(1, task.sold)
        self.assertEqual(1, len(task.surveys))

    def test_quick_sales_are_bounded(self):
        task = Loader([self.leftover_list() for _ in range(6)], [True] * 20)
        task.sales = [True] * 10
        task.load_cargo()
        self.assertEqual(task.MAX_QUICK_SALES, task.sold)
        self.assertEqual(6 - (task.MAX_QUICK_SALES + 1), len(task.surveys))

    def test_a_pass_without_leftovers_and_a_short_list_stops(self):
        task = Loader([two_catches(), two_catches()], [True, True])
        task.load_cargo()
        self.assertEqual(0, task.sold)
        self.assertEqual(1, len(task.surveys))


class QuickSeller(Placer):
    """The Quick Sale panel: `c` opens it, `e` sells the zone and shows Items Obtained, a click on blank space returns."""

    def __init__(self, price=13606, panel=True, drops=True):
        super().__init__({})
        self.price = price
        self.panel = panel
        self.drops = drops
        self.panel_open = False
        self.items = False
        self.used = 44

    def cargo_screen_open(self):
        return not self.items

    def has_text(self, pattern, *region):
        if 'Quick' in pattern:
            return self.panel_open
        if 'Items' in pattern:
            return self.items
        return False

    def texts(self, x=0, y=0, to_x=1, to_y=1):
        if (x, y, to_x, to_y) == self.QUICK_SALE_PRICE:
            return [str(self.price)] if self.price is not None else ['Total Price']
        return super().texts(x, y, to_x, to_y)

    def send_key(self, key, after_sleep=0.2, **kwargs):
        super().send_key(key, after_sleep)
        if key == 'c' and self.panel:
            self.panel_open = True
        if key == 'e' and self.panel_open:
            self.panel_open = False
            self.items = True

    def click_at(self, fx, fy, after_sleep=0.4):
        self.events.append(('click', fx, fy))
        if (fx, fy) == self.QUICK_SALE_CLOSE_AT:
            self.panel_open = False
        if (fx, fy) == self.REWARD_CLOSE_AT and self.items:
            self.items = False
            if self.drops:
                self.used = 21


class TestQuickSale(unittest.TestCase):
    def test_sells_the_zone_and_returns_to_the_catches_screen(self):
        task = QuickSeller()
        self.assertTrue(task.quick_sale())
        self.assertEqual(['c', 'e'], task.keys)
        self.assertEqual(('click', 0.5, 0.85), [e for e in task.events if isinstance(e, tuple)][-1])
        self.assertLess(task.events.index('e'), task.events.index(('click', 0.5, 0.85)))
        self.assertTrue(any('freed 23 cells, price 13606' in n for n in task.notes))

    def test_returns_false_when_the_panel_never_opens(self):
        task = QuickSeller(panel=False)
        self.assertFalse(task.quick_sale())
        self.assertEqual(['c'], task.keys)

    def test_closes_the_panel_when_the_zone_is_worth_nothing(self):
        for price in (0, None):
            task = QuickSeller(price=price)
            self.assertFalse(task.quick_sale())
            self.assertEqual(['c'], task.keys)
            self.assertIn(('click', 0.366, 0.535), task.events)
            self.assertFalse(task.panel_open)

    def test_fails_when_the_counter_never_drops(self):
        task = QuickSeller(drops=False)
        with self.assertRaises(Exception) as ctx:
            task.quick_sale()
        self.assertIn('did not free any cargo', str(ctx.exception))

    def test_fails_when_items_obtained_never_shows(self):
        task = QuickSeller()
        task.send_key = lambda key, after_sleep=0.2, **k: setattr(task, 'panel_open', key == 'c')
        with self.assertRaises(Exception) as ctx:
            task.quick_sale()
        self.assertIn('Items Obtained', str(ctx.exception))


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

    hover = [True]

    def wheel_open(self):
        return self.wheel.pop(0) if len(self.wheel) > 1 else self.wheel[0]

    def hovering(self, name):
        return self.hover.pop(0) if len(self.hover) > 1 else self.hover[0]

    def log_info(self, message, notify=False, **kwargs):
        self.events.append(('log', message))

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
        self.assertEqual([('down', 'tab'), ('point', 0.5, 0.5), ('point', 0.601, 0.319), ('up', 'tab')], task.events)

    def test_a_missed_wheel_ocr_does_not_stop_the_pick(self):
        task = Equipper([False])
        task.equip('baiting')
        self.assertEqual([('down', 'tab'), ('point', 0.5, 0.5), ('point', 0.601, 0.319), ('up', 'tab')], task.events)

    def test_retries_the_whole_pick_and_then_fails_when_the_name_never_shows(self):
        task = Equipper([False])
        task.hover = [False]
        with self.assertRaises(Exception) as ctx:
            task.equip('sweet_puff')
        self.assertIn('could not pick sweet_puff', str(ctx.exception))
        self.assertEqual(3, len([e for e in task.events if e == ('down', 'tab')]))
        self.assertEqual(3, len([e for e in task.events if e == ('up', 'tab')]))


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


class Starter(BaitFishingTask):
    class _Keys:
        def get(self, key):
            return 't'

    key_config = _Keys()

    def __init__(self, sailing, on_hub):
        self.sailing, self.on_hub = sailing, on_hub
        self.calls = []

    hwnd = types.SimpleNamespace(hwnd=1)

    def is_sailing(self):
        return self.sailing

    def has_text(self, pattern, *region):
        return self.on_hub

    def ensure_main(self):
        self.calls.append('ensure_main')

    def go_to_dock(self):
        self.calls.append('go_to_dock')

    def prepare_and_sail(self):
        self.calls.append('prepare_and_sail')

    def loop(self):
        self.calls.append('loop')

    def log_info(self, message, notify=False, **kwargs):
        pass


class TestRunStart(unittest.TestCase):
    def run_task(self, sailing, on_hub):
        task = Starter(sailing, on_hub)
        import src.task.BaitFishingTask as module
        saved = (module.WWOneTimeTask.run, module.RealInput)
        module.WWOneTimeTask.run = lambda self: None
        module.RealInput = lambda hwnd: object()
        try:
            task.run()
        finally:
            module.WWOneTimeTask.run, module.RealInput = saved
        return task.calls

    def test_sailing_goes_straight_to_the_loop(self):
        self.assertEqual(['loop'], self.run_task(True, False))

    def test_on_the_dock_hub_only_sets_sail(self):
        self.assertEqual(['prepare_and_sail', 'loop'], self.run_task(False, True))

    def test_elsewhere_travels_to_the_dock_first(self):
        self.assertEqual(['ensure_main', 'go_to_dock', 'prepare_and_sail', 'loop'], self.run_task(False, False))


class Counter(BaitFishingTask):
    def __init__(self, counts):
        self.counts = list(counts)
        self.equipped = []
        self.shots = []

    def equip(self, name):
        self.equipped.append(name)

    def utility_count(self):
        return self.counts.pop(0)

    def screenshot(self, name=None, **kwargs):
        self.shots.append(name)


class TestBaitCount(unittest.TestCase):
    def test_reads_the_count_after_one_equip(self):
        task = Counter([186])
        self.assertEqual(186, task.bait_count())
        self.assertEqual(['baiting'], task.equipped)

    def test_retries_the_equip_once_when_the_count_is_missing(self):
        task = Counter([None, 186])
        self.assertEqual(186, task.bait_count())
        self.assertEqual(['baiting', 'baiting'], task.equipped)
        self.assertEqual(['utility_missed'], task.shots)

    def test_gives_up_after_two_misses(self):
        task = Counter([None, None])
        self.assertIsNone(task.bait_count())
        self.assertEqual(['utility_missed', 'utility_missed'], task.shots)


class Puffer(BaitFishingTask):
    class _Keys:
        def get(self, key):
            return 't'

    key_config = _Keys()

    def __init__(self, count, complete):
        self.count, self.complete = count, complete
        self.events = []

    def info_set(self, *args, **kwargs):
        pass

    def equip(self, name):
        self.events.append(('equip', name))

    def utility_count(self):
        return self.count

    def send_key(self, key, after_sleep=0):
        self.events.append(('key', key))

    def wait_until(self, condition, time_out=10):
        return self.complete

    def click_at(self, fx, fy, after_sleep=0.4):
        self.events.append(('click',))

    def sleep(self, seconds):
        pass

    def log_info(self, message, notify=False, **kwargs):
        self.events.append(('log', message))

    def fail(self, message):
        raise Exception(message)


class TestSweetPuff(unittest.TestCase):
    def test_an_empty_stock_takes_the_manual_path_without_pressing_the_tool_key(self):
        task = Puffer(0, True)
        self.assertFalse(task.try_sweet_puff())
        self.assertNotIn(('key', 't'), task.events)

    def test_an_unreadable_count_still_tries_the_puff(self):
        task = Puffer(None, True)
        self.assertTrue(task.try_sweet_puff())
        self.assertIn(('key', 't'), task.events)

    def test_an_unreadable_count_and_no_effect_falls_back_quietly(self):
        task = Puffer(None, False)
        self.assertFalse(task.try_sweet_puff())

    def test_a_known_stock_with_no_effect_fails(self):
        with self.assertRaises(Exception) as ctx:
            Puffer(211, False).try_sweet_puff()
        self.assertIn('Fishing Complete', str(ctx.exception))


class TestEquipHover(unittest.TestCase):
    def test_repoints_until_the_name_shows_under_the_cursor(self):
        task = Equipper([True, False])
        task.hover = [False, True]
        task.equip('baiting')
        points = [e for e in task.events if e[0] == 'point']
        self.assertEqual([('point', 0.5, 0.5), ('point', 0.601, 0.319), ('point', 0.5, 0.5), ('point', 0.601, 0.319)],
                         points)
        self.assertEqual(('up', 'tab'), task.events[-1])


class Seller(BaitFishingTask):
    """Plays the Dock Shop: `counts` are the successive hub cargo counts, `texts` what the shop screen shows."""

    def __init__(self, counts, texts):
        self.counts = list(counts)
        self.shown = set(texts)
        self.keys = []
        self.clicked_texts = []
        self.clicked = []

    def info_set(self, *a): pass
    def log_info(self, *a, **k): pass
    def sleep(self, *a): pass
    def screenshot(self, *a, **k): pass
    def fail(self, message): raise Exception(message)
    def hub_cargo_used(self): return self.counts.pop(0)
    def has_text(self, pattern, *box): return any(re.search(pattern, t, re.IGNORECASE) for t in self.shown)
    def click_at(self, x, y, **k): self.clicked.append((x, y))
    def send_key(self, key, **k): self.keys.append(key)
    def wait_until(self, cond, time_out=10, **k): return cond()

    def click_ocr_text(self, pattern, *a, **k):
        for text in list(self.shown):
            if text.lower() in pattern.lower().replace('\s*', ' ') or pattern.lower().replace('\s*', ' ') in text.lower():
                self.clicked_texts.append(text)
                if text == 'Confirm':
                    self.shown.discard('Confirm')
                return True
        return False


class TestSellAll(unittest.TestCase):
    def test_skips_an_empty_cargo(self):
        task = Seller([0], [])
        task.sell_all()
        self.assertEqual([], task.clicked)

    def test_sells_confirms_and_checks_the_cargo(self):
        task = Seller([20, 0], ['Sell All', 'Confirm', 'Dock Shop'])
        task.sell_all()
        self.assertEqual(['Sell All', 'Confirm'], task.clicked_texts)

    def test_opens_the_catch_list_when_the_shop_has_no_sell_all(self):
        task = Seller([20, 0], ['Dock Shop'])
        with self.assertRaises(Exception):
            task.sell_all()
        self.assertIn('c', task.keys)

    def test_fails_when_the_cargo_is_not_empty_afterwards(self):
        task = Seller([20, 7], ['Sell All', 'Dock Shop'])
        with self.assertRaises(Exception):
            task.sell_all()


class HubOpener(BaitFishingTask):
    def __init__(self, opens_on_press):
        self.opens_on_press = opens_on_press
        self.presses = 0

    def send_key(self, key, **k): self.presses += 1
    def sleep(self, *a): pass
    def has_text(self, *a, **k): return self.presses >= self.opens_on_press
    def wait_until(self, cond, time_out=10, **k): return cond()
    def prompt_texts(self): return ['Return to the dock']
    def select_entry(self, *a): pass
    def nudge_until(self, *a, **k): pass
    def fail(self, message): raise Exception(message)


class TestOpenDockHub(unittest.TestCase):
    def test_presses_f_again_when_the_hub_did_not_open(self):
        task = HubOpener(2)
        task.open_dock_hub()
        self.assertEqual(2, task.presses)

    def test_fails_after_four_presses(self):
        task = HubOpener(99)
        with self.assertRaises(Exception):
            task.open_dock_hub()
        self.assertEqual(4, task.presses)
