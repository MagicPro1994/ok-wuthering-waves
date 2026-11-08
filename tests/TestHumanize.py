import random
import unittest

from src import humanize as hz


class TestHumanize(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(11)

    def test_taps_become_human_length(self):
        for base in (0.0, 0.01, 0.02, 0.03):
            for _ in range(100):
                self.assertTrue(0.035 <= hz.hold_time(base, self.rng) <= 0.07)

    def test_long_holds_keep_their_length(self):
        for _ in range(200):
            self.assertTrue(0.19 <= hz.hold_time(0.2, self.rng) <= 0.2 * 1.12)

    def test_hold_times_vary(self):
        self.assertGreater(len({hz.hold_time(0.01, self.rng) for _ in range(20)}), 15)

    def test_sleep_never_shorter_and_capped(self):
        for base in (0.01, 0.5, 2):
            for _ in range(200):
                v = hz.sleep_time(base, self.rng)
                self.assertTrue(base <= v <= base * 1.2 + 1e-9)

    def test_sleep_zero_or_negative_is_unchanged(self):
        self.assertEqual(0, hz.sleep_time(0, self.rng))
        self.assertEqual(-1, hz.sleep_time(-1, self.rng))

    def test_point_in_box_stays_near_aim(self):
        points = set()
        for _ in range(300):
            x, y = hz.point_in_box(100, 200, 80, 40, rng=self.rng)
            self.assertTrue(140 - 24 - 1 <= x <= 140 + 24 + 1)
            self.assertTrue(220 - 12 - 1 <= y <= 220 + 12 + 1)
            points.add((x, y))
        self.assertGreater(len(points), 50)

    def test_point_in_box_aim_outside_box(self):
        # BaseCombatTask clicks at relative_x=1.5, to the right of the box
        for _ in range(100):
            x, _ = hz.point_in_box(100, 200, 80, 40, rel_x=1.5, rng=self.rng)
            self.assertTrue(220 - 24 - 1 <= x <= 220 + 24 + 1)

    def test_point_near_is_a_few_pixels(self):
        for _ in range(300):
            x, y = hz.point_near(500, 500, 1080, self.rng)
            self.assertLessEqual(abs(x - 500), 5)
            self.assertLessEqual(abs(y - 500), 5)

    def test_glide_ends_on_target(self):
        path = hz.glide_path((0, 0), (400, 300), self.rng)
        self.assertEqual((400, 300), path[-1][:2])
        self.assertTrue(6 <= len(path) <= 30)
        self.assertTrue(0.05 <= sum(p[2] for p in path) <= 0.35)

    def test_glide_tiny_distance(self):
        self.assertEqual([(10, 10, 0.0)], hz.glide_path((10, 10), (10, 10), self.rng))


if __name__ == '__main__':
    unittest.main()
