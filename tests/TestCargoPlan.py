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
