import random
import unittest

from src.fishing import human_input as hi


class TestHumanInput(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(7)

    def test_jitter_hold_range(self):
        for _ in range(200):
            v = hi.jitter_hold(1.0, self.rng)
            self.assertTrue(0.93 <= v <= 1.08)

    def test_camera_steps_sum_and_bounds(self):
        for dx in (300, -300, 41, -90, 1000):
            steps = hi.camera_steps(dx, self.rng)
            self.assertLessEqual(abs(sum(s[0] for s in steps) - dx), 3)
            for sx, sy, delay in steps[:-1]:
                self.assertTrue(25 <= abs(sx) <= 70)
            for sx, sy, delay in steps:
                self.assertTrue(-1 <= sy <= 1)
                self.assertTrue(0.04 <= delay <= 0.11)
                self.assertEqual(dx > 0, sx > 0)

    def test_camera_steps_are_not_uniform(self):
        sizes = {abs(s[0]) for s in hi.camera_steps(2000, self.rng)[:-1]}
        self.assertGreater(len(sizes), 5)

    def test_tiny_turn_is_noop(self):
        self.assertEqual([], hi.camera_steps(3, self.rng))
        self.assertEqual([], hi.camera_steps(-2, self.rng))

    def test_turn_hold_capped(self):
        # the boat turns about 80 degrees per second; a full U-turn is never longer than 2.4 s
        self.assertLessEqual(hi.turn_hold_seconds(500, self.rng), 2.4 * 1.08)
        self.assertAlmostEqual(0.5, hi.turn_hold_seconds(40.0, random.Random(1)), delta=0.04)

    def test_offset_point_clamped_and_close(self):
        for _ in range(200):
            x, y = hi.offset_point(0.001, 0.999, self.rng)
            self.assertTrue(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0)
        x, y = hi.offset_point(0.5, 0.5, self.rng)
        self.assertLess(abs(x - 0.5), 0.0041)
        self.assertLess(abs(y - 0.5), 0.0061)

    def test_sweep_plan_covers_a_turn(self):
        plan = hi.sweep_plan(self.rng)
        self.assertTrue(1500 <= sum(plan) <= 2200)
        self.assertGreater(len(set(plan)), 5)

    def test_sail_press_range(self):
        for _ in range(100):
            self.assertTrue(1.8 <= hi.sail_press(self.rng) <= 2.8)
