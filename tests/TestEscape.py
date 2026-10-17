import unittest

import numpy as np

from src.fishing import escape


def trail(points, gap=2.0):
    return [(i * gap, x, y) for i, (x, y) in enumerate(points)]


class TestPocket(unittest.TestCase):
    def test_wandering_in_a_small_area_is_a_pocket(self):
        # live: 6 minutes inside x 6690..6760, y 3358..3416
        points = [(6700 + (i * 7) % 60, 3360 + (i * 11) % 55) for i in range(30)]
        self.assertTrue(escape.in_pocket(trail(points), now=60.0))

    def test_making_headway_is_not_a_pocket(self):
        points = [(6800 - i * 10, 3340) for i in range(30)]
        self.assertFalse(escape.in_pocket(trail(points), now=60.0))

    def test_needs_a_whole_window_of_samples(self):
        self.assertFalse(escape.in_pocket(trail([(6700, 3360)] * 5), now=10.0))

    def test_old_samples_do_not_count(self):
        # the boat sat still for a minute, then moved off: only the last 45 s matter
        points = [(6700, 3360)] * 10 + [(6700 - i * 15, 3360) for i in range(1, 25)]
        self.assertFalse(escape.in_pocket(trail(points), now=68.0))


class TestWorldStep(unittest.TestCase):
    def test_axes(self):
        # minimap east is world +x, north is world -y (y grows to the south)
        dx, dy = escape.world_step(0, 100)
        self.assertAlmostEqual((100, 0), (round(dx), round(dy)))
        dx, dy = escape.world_step(90, 100)
        self.assertAlmostEqual((0, -100), (round(dx), round(dy)))
        dx, dy = escape.world_step(250, 100)       # live: heading 250 moved x down, y up in value
        self.assertLess(dx, 0)
        self.assertGreater(dy, 0)


class TestPickEscape(unittest.TestCase):
    def mask(self):
        return np.zeros((260, 260), bool)

    def test_prefers_open_water_over_a_wall(self):
        mask = self.mask()
        mask[:118, :] = True                    # land over the north, a little way off
        bearing = escape.pick_escape(mask, (0, 0), [])
        self.assertEqual(escape.FREE_REACH, escape.free_length(mask, bearing))
        self.assertFalse(15 < bearing < 165, bearing)       # not into the wall in the north

    def test_prefers_ground_not_visited_yet(self):
        mask = self.mask()
        here = (1000.0, 1000.0)
        west = escape.world_step(180, escape.ESCAPE_LEG)
        visited = [(here[0] + west[0] + i, here[1] + west[1]) for i in range(20)]
        bearing = escape.pick_escape(mask, here, visited)
        self.assertNotEqual(180.0, bearing)

    def test_free_length_stops_at_land(self):
        mask = self.mask()
        mask[121, 160:] = True                  # land 30 px east of the boat
        self.assertAlmostEqual(30, escape.free_length(mask, 0), delta=3)
        self.assertEqual(escape.FREE_REACH, escape.free_length(mask, 180))
