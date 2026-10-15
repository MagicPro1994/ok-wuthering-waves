import unittest

import numpy as np

from src.fishing import detect
from tests.TestFishingDetect import angle_gap, frame_with_minimap

CX, CY = 130, 121      # the boat, at the minimap centre; image y grows downwards


def land(*rects):
    """Mask with land rectangles given as (x0, y0, x1, y1) minimap pixels."""
    mask = np.zeros((260, 260), bool)
    for x0, y0, x1, y1 in rects:
        mask[y0:y1, x0:x1] = True
    return mask


def crosses(mask, route):
    return any(mask[int(round(y)), int(round(x))] for x, y in route.path)


class TestPlanRoute(unittest.TestCase):
    def test_open_water_goes_straight_at_the_target(self):
        for bearing in range(0, 360, 45):
            route = detect.plan_route(land(), bearing, None)
            self.assertLess(angle_gap(route.bearing, bearing), 8, bearing)
            self.assertFalse(route.blocked)

    def test_goes_through_the_gap_in_a_wall(self):
        wall = land((30, 70, 165, 82), (210, 70, 230, 82))      # gap at x 165..210, east of the boat
        route = detect.plan_route(wall, 90, None)
        self.assertLess(route.bearing, 80)                      # heads east of north, towards the gap
        self.assertFalse(crosses(wall, route))

    def test_does_not_enter_a_dead_end_bay(self):
        bay = land((70, 60, 190, 72), (70, 60, 82, 100), (178, 60, 190, 100))   # cup open to the south
        route = detect.plan_route(bay, 90, None)
        self.assertGreater(angle_gap(route.bearing, 90), 30)    # goes round the arm, not into the cup
        self.assertFalse(crosses(bay, route))

    def test_prefers_the_side_already_taken(self):
        island = land((100, 60, 160, 90))                       # centred ahead, equal either way round
        left = detect.plan_route(island, 90, None, prefer=1)    # +1: anticlockwise, west of north
        right = detect.plan_route(island, 90, None, prefer=-1)
        self.assertGreater(left.bearing, 90)
        self.assertLess(right.bearing, 90)

    def test_boxed_in_is_blocked(self):
        self.assertTrue(detect.plan_route(np.ones((260, 260), bool), 90, None).blocked)

    def test_target_inside_the_map_is_approached(self):
        route = detect.plan_route(land(), 30, 50.0)
        self.assertLess(angle_gap(route.bearing, 30), 8)

    def test_a_target_behind_land_is_gone_round(self):
        island = land((100, 60, 160, 90))
        route = detect.plan_route(island, 90, 62.0, prefer=1)   # the icon sits behind the island
        self.assertGreater(angle_gap(route.bearing, 90), 15)
        self.assertFalse(crosses(island, route))

    def test_real_open_sea_frames_do_not_deviate(self):
        for name in ('mini_west.png', 'mini_sea_day.png', 'mini_north.png', 'mini_southeast.png'):
            mask = detect.minimap_danger(frame_with_minimap(name))
            for bearing in range(0, 360, 30):
                route = detect.plan_route(mask, bearing, None)
                self.assertLess(angle_gap(route.bearing, bearing), 15, (name, bearing))

    def test_real_dock_frame_goes_round_the_structure(self):
        mask = detect.minimap_danger(frame_with_minimap('mini_dock.png'))
        route = detect.plan_route(mask, 45, None)
        self.assertGreater(angle_gap(route.bearing, 45), 25)
        self.assertFalse(crosses(mask, route))


if __name__ == '__main__':
    unittest.main()
