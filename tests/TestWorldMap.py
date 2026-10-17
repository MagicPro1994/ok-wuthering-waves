import math
import unittest

import numpy as np

from src.fishing import worldmap
from src.fishing.detect import MINIMAP_CENTRE
from src.fishing.worldmap import TargetTracker, UNITS_PER_PX, WorldMap, bearing_of

STEP = 17.0


class Sea:
    """Rectangles of land in the world; the boat sees them through a north-up minimap disc."""

    def __init__(self, lands, start, target):
        self.lands, self.pos, self.target = lands, start, target
        self.bumps = 0

    def land(self, x, y):
        return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in self.lands)

    def minimap(self):
        cx, cy = MINIMAP_CENTRE
        ys, xs = np.mgrid[0:260, 0:260]
        wx = self.pos[0] + (xs - cx) * UNITS_PER_PX
        wy = self.pos[1] + (ys - cy) * UNITS_PER_PX
        mask = np.zeros((260, 260), dtype=bool)
        for x0, y0, x1, y1 in self.lands:
            mask |= (wx >= x0) & (wx <= x1) & (wy >= y0) & (wy <= y1)
        return mask

    def icon(self):
        dx, dy = self.target[0] - self.pos[0], self.target[1] - self.pos[1]
        radius = math.hypot(dx, dy) / UNITS_PER_PX
        bearing = bearing_of(dx, dy)
        return bearing, min(radius, 77.0)

    def sail(self, bearing):
        a = math.radians(bearing)
        x, y = self.pos[0] + STEP * math.cos(a), self.pos[1] - STEP * math.sin(a)
        if self.land(x, y):
            self.bumps += 1
            return
        self.pos = (x, y)


def drive(sea, steps=400, goal=40.0):
    world, tracker = WorldMap(), TargetTracker()
    path = [sea.pos]
    for _ in range(steps):
        world.observe(sea.minimap(), sea.pos)
        bearing, radius = sea.icon()
        tracker.observe(sea.pos, bearing, radius)
        if math.hypot(sea.target[0] - sea.pos[0], sea.target[1] - sea.pos[1]) < goal:
            return True, path, world
        target = tracker.estimate(sea.pos, bearing)
        plan = world.plan(sea.pos, target)
        if plan.blocked:
            return False, path, world
        sea.sail(plan.bearing(sea.pos))
        path.append(sea.pos)
    return False, path, world


class TestWorldMap(unittest.TestCase):
    def test_remembers_land_in_world_coordinates(self):
        sea = Sea([(1030, 960, 1200, 1040)], (1000.0, 1000.0), (2000.0, 1000.0))
        world = WorldMap()
        world.observe(sea.minimap(), sea.pos)
        self.assertTrue(world.land_at(1040, 1000))
        self.assertFalse(world.land_at(1000, 1040))
        # after the boat moved on, the land stays where it was
        sea.pos = (900.0, 1000.0)
        world.observe(sea.minimap(), sea.pos)
        self.assertTrue(world.land_at(1040, 1000))

    def test_a_wall_bumped_into_is_land(self):
        world = WorldMap()
        world.mark_wall((1000.0, 1000.0), 0.0)
        self.assertTrue(world.land_at(1014, 1000))
        self.assertTrue(world.land_at(1014, 1020))

    def test_plan_goes_round_land_on_the_way(self):
        sea = Sea([(1030, 900, 1060, 1100)], (1000.0, 1000.0), (1400.0, 1000.0))
        world = WorldMap()
        world.observe(sea.minimap(), sea.pos)
        plan = world.plan(sea.pos, sea.target)
        self.assertGreater(abs(((plan.bearing(sea.pos) + 180) % 360) - 180), 15)

    def test_a_far_target_is_found_round_an_island(self):
        sea = Sea([(1040, 800, 1240, 1200)], (950.0, 1000.0), (1500.0, 1000.0))
        reached, path, _ = drive(sea, steps=300)
        self.assertTrue(reached, 'never got round the island')
        self.assertLessEqual(sea.bumps, 3)

    def test_a_bay_closed_on_the_far_side_is_left_again(self):
        # a U-shaped bay opens towards the boat; the target lies beyond its closed end
        lands = [(1040, 940, 1240, 950), (1040, 1050, 1240, 1060), (1240, 940, 1250, 1060)]
        sea = Sea(lands, (950.0, 1000.0), (1500.0, 1000.0))
        reached, path, _ = drive(sea, steps=300)
        self.assertTrue(reached, 'trapped in the bay')
        self.assertLessEqual(sea.bumps, 4)


class TestTargetByLand(unittest.TestCase):
    def test_a_target_right_beside_an_islet_is_approached_not_circled(self):
        # the request icon sits 20 units from an islet, inside the clearance kept from land
        sea = Sea([(1000, 960, 1060, 1040)], (800.0, 1000.0), (1080.0, 1000.0))
        reached, path, _ = drive(sea, steps=120, goal=40.0)
        self.assertTrue(reached, 'circled the target without getting to it')


class TestHarbour(unittest.TestCase):
    def test_a_target_inside_a_harbour_with_a_narrow_mouth_is_reached(self):
        # walls on all sides of a pool but a 40 unit gap: too tight for the usual clearance, wide enough for a boat
        lands = [(1000, 900, 1200, 940), (1000, 1060, 1200, 1100), (1200, 900, 1240, 1100),
                 (1000, 940, 1040, 980), (1000, 1020, 1040, 1060)]
        sea = Sea(lands, (850.0, 1000.0), (1120.0, 1000.0))
        world = WorldMap()
        for x in range(850, 1000, 20):          # the boat has been round here and seen the walls and the pool
            sea.pos = (float(x), 1000.0)
            world.observe(sea.minimap(), sea.pos)
        for pos in ((1060.0, 1000.0), (1110.0, 1000.0)):
            world.observe(sea.minimap(), pos) if False else None
        sea.pos = (900.0, 1000.0)
        for _ in range(60):
            plan = world.plan(sea.pos, sea.target)
            self.assertFalse(plan.blocked)
            sea.sail(plan.bearing(sea.pos))
            world.observe(sea.minimap(), sea.pos)
            if math.hypot(sea.target[0] - sea.pos[0], sea.target[1] - sea.pos[1]) < 40:
                break
        self.assertLess(math.hypot(sea.target[0] - sea.pos[0], sea.target[1] - sea.pos[1]), 40, 'never got into the harbour')


class TestKeepingTheMap(unittest.TestCase):
    def test_a_saved_map_comes_back(self):
        import tempfile
        from pathlib import Path
        sea = Sea([(1030, 960, 1200, 1040)], (1000.0, 1000.0), (2000.0, 1000.0))
        world = WorldMap()
        world.observe(sea.minimap(), sea.pos)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'map.npz'
            world.save(path)
            again = WorldMap()
            self.assertTrue(again.load(path))
        self.assertTrue(again.land_at(1040, 1000))
        self.assertFalse(again.load('missing.npz'))


class TestTargetTracker(unittest.TestCase):
    def test_inside_the_disc_the_icon_is_exact(self):
        tracker = TargetTracker()
        bearing = bearing_of(30.0, -40.0)
        tracker.observe((1000.0, 1000.0), bearing, math.hypot(30, 40) / UNITS_PER_PX)
        x, y = tracker.estimate((1000.0, 1000.0), bearing)
        self.assertAlmostEqual(1030.0, x, delta=3)
        self.assertAlmostEqual(960.0, y, delta=3)

    def test_two_rim_bearings_cross_at_the_target(self):
        target = (1500.0, 800.0)
        tracker = TargetTracker()
        for pos in ((1000.0, 1000.0), (1000.0, 1120.0), (1060.0, 1200.0)):
            bearing = bearing_of(target[0] - pos[0], target[1] - pos[1])
            tracker.observe(pos, bearing, 77.0)
        x, y = tracker.estimate(pos, bearing)
        self.assertAlmostEqual(target[0], x, delta=40)
        self.assertAlmostEqual(target[1], y, delta=40)


if __name__ == '__main__':
    unittest.main()
