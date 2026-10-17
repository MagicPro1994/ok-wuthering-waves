import unittest

from src.fishing.obstacles import Obstacle, to_obstacles, verdict


def ob(name, x1, y1, x2, y2):
    return Obstacle(name, x1, y1, x2, y2)


class TestVerdict(unittest.TestCase):
    def test_open_water_is_clear(self):
        self.assertEqual('clear', verdict([]).action)

    def test_far_shore_at_the_horizon_is_ignored(self):
        self.assertEqual('clear', verdict([ob('land', 0.0, 0.25, 1.0, 0.42)]).action)

    def test_close_wall_ahead_turns_to_the_emptier_side(self):
        # wall over the right and centre: the left is open, so turn left (positive, A)
        v = verdict([ob('rock', 0.4, 0.2, 1.0, 0.8)])
        self.assertEqual('turn', v.action)
        self.assertGreater(v.error_deg, 0)

    def test_wall_on_the_left_turns_right(self):
        v = verdict([ob('rock', 0.0, 0.2, 0.62, 0.8)])
        self.assertEqual('turn', v.action)
        self.assertLess(v.error_deg, 0)

    def test_obstacle_beside_the_corridor_does_not_stop_the_boat(self):
        self.assertEqual('clear', verdict([ob('rock', 0.0, 0.2, 0.30, 0.8)]).action)

    def test_walled_in_on_both_sides(self):
        v = verdict([ob('rock', 0.0, 0.2, 1.0, 0.8)])
        self.assertEqual('blocked', v.action)

    def test_shallows_reaching_in_front_of_the_bow_count(self):
        self.assertEqual('turn', verdict([ob('shallows', 0.3, 0.30, 0.7, 0.95)]).action)

    def test_shallows_only_under_the_boat_are_not_ahead(self):
        self.assertEqual('clear', verdict([ob('shallows', 0.0, 0.70, 1.0, 1.0)]).action)

    def test_overlapping_boxes_are_not_counted_twice(self):
        v = verdict([ob('rock', 0.0, 0.2, 0.4, 0.8), ob('land', 0.1, 0.2, 0.5, 0.8)])
        self.assertAlmostEqual(1.0, v.left, places=3)


class TestConversion(unittest.TestCase):
    def test_pixels_to_fractions(self):
        class Box:
            name, x, y, width, height = 'rock', 960, 540, 480, 270

        o = to_obstacles([Box()], 1920, 1080)[0]
        self.assertEqual(('rock', 0.5, 0.5, 0.75, 0.75), (o.name, o.x1, o.y1, o.x2, o.y2))


class TestMissingModel(unittest.TestCase):
    def test_no_weights_means_no_avoidance(self):
        from src.fishing.obstacles import ObstacleDetector
        detector = ObstacleDetector('does/not/exist.onnx')
        self.assertFalse(detector.ready)
        self.assertIsNone(detector.look(None))
