import unittest

from src.fishing.cargo_packer import orientations
from src.fishing.cargo_plan import Catch, grab_and_drop, plan_cargo, shape_matches

SQUARE = frozenset({(0, 0), (0, 1), (1, 0), (1, 1)})
BAR = frozenset({(0, 0), (0, 1), (0, 2), (0, 3)})
L = frozenset({(0, 0), (1, 0), (2, 0), (2, 1)})


def grid(rows, cols):
    return {(r, c) for r in range(rows) for c in range(cols)}


class TestPlanCargo(unittest.TestCase):
    def test_everything_fits(self):
        catches = [Catch(0, SQUARE, 5), Catch(1, BAR, 3)]
        plan = plan_cargo(grid(4, 4), catches)
        self.assertEqual({0, 1}, {c.slot for c, _ in plan})

    def test_high_value_fish_wins_when_only_one_fits(self):
        catches = [Catch(0, SQUARE, 5), Catch(1, SQUARE, 9)]
        plan = plan_cargo(grid(2, 2), catches)
        self.assertEqual([1], [c.slot for c, _ in plan])

    def test_nothing_fits(self):
        self.assertEqual([], plan_cargo(grid(1, 1), [Catch(0, SQUARE, 5)]))

    def test_no_catches(self):
        self.assertEqual([], plan_cargo(grid(3, 3), []))

    def test_placements_do_not_overlap_and_stay_in_free_cells(self):
        free = grid(3, 4)
        plan = plan_cargo(free, [Catch(0, L, 4), Catch(1, SQUARE, 6), Catch(2, BAR, 5)])
        seen = set()
        for _, placement in plan:
            self.assertTrue(placement.cells <= free)
            self.assertTrue(seen.isdisjoint(placement.cells))
            seen |= placement.cells

    def test_sorted_by_slot_descending(self):
        plan = plan_cargo(grid(4, 4), [Catch(0, SQUARE, 5), Catch(1, SQUARE, 5), Catch(2, SQUARE, 5)])
        slots = [c.slot for c, _ in plan]
        self.assertEqual(sorted(slots, reverse=True), slots)


class TestDragTargets(unittest.TestCase):
    def test_shape_matches_after_rotation(self):
        plan = plan_cargo(grid(2, 3), [Catch(0, L, 4)])
        _, placement = plan[0]
        rotated = dict(orientations(L))[placement.rotations]
        self.assertTrue(shape_matches({(r + 5, c + 4) for r, c in rotated}, placement))
        if placement.rotations:
            self.assertFalse(shape_matches(L, placement))

    def test_grab_and_drop_moves_the_preview_onto_the_placement(self):
        preview = {(2, 2), (3, 2), (4, 2), (4, 3)}            # an L at rows 2-4, cols 2-3
        plan = plan_cargo(grid(7, 8), [Catch(0, frozenset({(0, 0), (1, 0), (2, 0), (2, 1)}), 4)])
        placement = plan[0][1]
        grab, drop = grab_and_drop(preview, placement)
        self.assertIn(grab, preview)
        dr, dc = drop[0] - grab[0], drop[1] - grab[1]
        # only valid when the shape already has the target orientation
        if shape_matches(preview, placement):
            self.assertEqual(placement.cells, frozenset((r + dr, c + dc) for r, c in preview))


class TestNeededCatches(unittest.TestCase):
    PLUS = frozenset({(0, 1), (1, 0), (1, 1), (1, 2), (2, 1)})
    TEE = frozenset({(0, 1), (1, 0), (1, 1), (1, 2)})

    def test_shape_key_ignores_rotation_and_position(self):
        from src.fishing.cargo_plan import shape_key
        turned = frozenset({(5, 5), (6, 4), (6, 5), (6, 6), (7, 5)})
        self.assertEqual(shape_key(self.PLUS), shape_key(turned))
        self.assertNotEqual(shape_key(self.PLUS), shape_key(self.TEE))

    def test_unknown_shapes_are_kept_up_to_the_quantity_wanted(self):
        from src.fishing.cargo_plan import Catch, needed_catches
        catches = [Catch(i, self.PLUS, 10) for i in range(4)]
        kept = needed_catches(catches, {}, {'a': 1, 'b': 1})
        self.assertEqual([0, 1], [c.slot for c in kept])

    def test_a_fish_of_a_full_objective_is_left_out(self):
        from src.fishing.cargo_plan import Catch, needed_catches, shape_key
        known = {shape_key(self.PLUS): 'goober', shape_key(self.TEE): 'dumbo'}
        catches = [Catch(0, self.PLUS, 10), Catch(1, self.PLUS, 10), Catch(2, self.TEE, 5)]
        kept = needed_catches(catches, known, {'goober': 1, 'dumbo': 3})
        self.assertEqual([0, 2], [c.slot for c in kept])

    def test_soft_and_softer_the_jellyfish_is_loaded_with_the_eel(self):
        # live: 2 of 3 jellyfish were in the cargo, the list held an eel and a jellyfish, and only the eel was loaded
        from src.fishing.cargo_plan import Catch, needed_catches, shape_key
        known = {shape_key(self.PLUS): 'jellyfish', shape_key(self.TEE): 'eel'}
        catches = [Catch(0, self.TEE, 5), Catch(1, self.PLUS, 10)]
        kept = needed_catches(catches, known, {'eel': 1, 'jellyfish': 1})
        self.assertEqual([0, 1], [c.slot for c in kept])

    def test_nothing_is_needed_when_every_objective_is_full(self):
        from src.fishing.cargo_plan import Catch, needed_catches
        self.assertEqual([], needed_catches([Catch(0, self.PLUS, 10)], {}, {'a': 0, 'b': 0}))
