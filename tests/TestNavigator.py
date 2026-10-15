import math
import unittest

from src.fishing.nav import Navigator

STEP = 17.0     # world units sailed per read, about 1.3 s of W


def gap(a, b):
    return abs((a - b + 180) % 360 - 180)


class World:
    """A boat in a plane with rectangular wrecks the minimap cannot see; the minimap is rotated/mirrored."""

    def __init__(self, wrecks, sign=-1, offset=37.0, start=(0.0, 0.0), target=90.0):
        self.wrecks, self.sign, self.offset = wrecks, sign, offset
        self.pos, self.target = start, target
        self.bumps = 0

    def to_minimap(self, world):
        return self.sign * (world - self.offset) % 360

    def to_world(self, minimap):
        return (self.sign * minimap + self.offset) % 360

    def hits(self, x, y):
        return any(x0 - 8 <= x <= x1 + 8 and y0 - 8 <= y <= y1 + 8 for x0, y0, x1, y1 in self.wrecks)

    def sail(self, minimap_aim):
        heading = math.radians(self.to_world(minimap_aim))
        x, y = self.pos[0] + STEP * math.cos(heading), self.pos[1] + STEP * math.sin(heading)
        if self.hits(x, y):
            self.bumps += 1
            return self.pos
        self.pos = (x, y)
        return self.pos


def run(world, steps=140, goal_y=320.0):
    nav = Navigator()
    minimap_target = world.to_minimap(world.target)
    aim, path = minimap_target, []
    nav.update(world.pos, aim, True)           # the position is read once before the boat moves
    for _ in range(steps):
        pos = world.sail(aim)
        path.append(pos)
        heading = aim
        nav.update(pos, heading, True)
        aim = nav.aim(minimap_target)
        if aim is None:
            return None, path, nav
        if pos[1] >= goal_y:
            break
    return world.pos, path, nav


class TestCompass(unittest.TestCase):
    def test_learns_a_mirrored_and_rotated_minimap(self):
        nav = Navigator()
        world = World([], sign=-1, offset=37.0)
        pos = (0.0, 0.0)
        nav.update(pos, world.to_minimap(10), True)
        for heading_world in (10, 10, 40, 70, 100):
            pos = (pos[0] + 17 * math.cos(math.radians(heading_world)), pos[1] + 17 * math.sin(math.radians(heading_world)))
            nav.update(pos, world.to_minimap(heading_world), True)
        sign, offset = nav.mapping()
        self.assertEqual(-1, sign)
        self.assertLess(gap(offset, 37.0), 6)

    def test_no_mapping_before_any_movement(self):
        self.assertIsNone(Navigator().mapping())


class TestBumps(unittest.TestCase):
    def test_stationary_boat_registers_a_bump(self):
        nav = Navigator()
        pos = (0.0, 0.0)
        results = []
        for i in range(6):
            pos = (pos[0], pos[1] + 17)
            results.append(nav.update(pos, 0.0, True))
        results.append(nav.update(pos, 0.0, True))
        results.append(nav.update(pos, 0.0, True))
        self.assertFalse(any(results[:6]))
        self.assertTrue(results[-1])
        self.assertTrue(nav.bumps)

    def test_a_moving_boat_never_bumps(self):
        nav = Navigator()
        pos = (0.0, 0.0)
        for _ in range(20):
            pos = (pos[0] + 17, pos[1])
            self.assertFalse(nav.update(pos, 0.0, True))

    def test_a_damaging_hit_is_remembered_straight_away(self):
        nav = Navigator()
        nav.update((0.0, 0.0), 0.0, True)
        nav.update((17.0, 0.0), 0.0, True)
        self.assertEqual(0.0, nav.aim(0.0))
        nav.mark_hit((17.0, 0.0), 0.0)
        self.assertGreater(gap(nav.aim(0.0), 0.0), 20)

    def test_aim_is_unchanged_without_bumps(self):
        nav = Navigator()
        self.assertEqual(123.0, nav.aim(123.0))


class TestRoundsWrecksTheMinimapCannotSee(unittest.TestCase):
    def check(self, wrecks, max_bumps, sign=-1, offset=37.0):
        world = World(wrecks, sign=sign, offset=offset)
        end, path, nav = run(world)
        self.assertIsNotNone(end, 'boxed in')
        self.assertGreaterEqual(end[1], 300, 'never got past the wreck')
        self.assertLessEqual(world.bumps, max_bumps)

    def test_a_wide_wreck_dead_ahead(self):
        self.check([(-90, 60, 90, 100)], 4)

    def test_the_same_with_an_unmirrored_minimap(self):
        self.check([(-90, 60, 90, 100)], 4, sign=1, offset=0.0)

    def test_a_very_long_wall(self):
        self.check([(-60, 60, 420, 90)], 8)

    def test_a_wreck_met_before_the_minimap_mapping_is_known(self):
        # the very first move ends against it: one motion sample is not enough to learn the mapping
        self.check([(-90, 30, 90, 70)], 8)
        self.check([(-90, 30, 90, 70)], 8, sign=1, offset=0.0)

    def test_a_bay_open_to_the_south(self):
        self.check([(-90, 100, 90, 130), (-90, 40, -60, 130), (60, 40, 90, 130)], 8)


if __name__ == '__main__':
    unittest.main()
