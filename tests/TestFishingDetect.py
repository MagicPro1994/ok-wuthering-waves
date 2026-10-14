import unittest

import cv2
import numpy as np

from src.fishing import detect


def blank():
    return np.full((1080, 1920, 3), (20, 40, 80), np.uint8)


class TestMarker(unittest.TestCase):
    def test_finds_round_marker(self):
        img = blank()
        cv2.circle(img, (800, 500), 14, (150, 60, 200), -1)
        x, y, area = detect.find_marker(img)
        self.assertAlmostEqual(800, x, delta=2)
        self.assertAlmostEqual(500, y, delta=2)
        self.assertTrue(250 < area < 1500)

    def test_ignores_sail_shape(self):
        img = blank()
        cv2.fillPoly(img, [np.array([[960, 600], [1000, 780], [920, 780]])], (150, 60, 200))
        self.assertIsNone(detect.find_marker(img))

    def test_ignores_hud_regions(self):
        img = blank()
        cv2.circle(img, (100, 100), 14, (150, 60, 200), -1)   # top-left HUD
        cv2.circle(img, (1700, 800), 14, (150, 60, 200), -1)  # bottom-right HUD
        self.assertIsNone(detect.find_marker(img))

    def test_none_on_empty(self):
        self.assertIsNone(detect.find_marker(blank()))

    def test_error_deg(self):
        self.assertAlmostEqual(0.0, detect.marker_error_deg(960))
        self.assertAlmostEqual(10.0, detect.marker_error_deg(960 + 210))
        self.assertAlmostEqual(-5.0, detect.marker_error_deg(960 - 105))


class TestHearts(unittest.TestCase):
    def _hearts(self, n):
        img = blank()
        for i in range(n):
            cv2.rectangle(img, (690 + i * 60, 1005), (690 + i * 60 + 28, 1025), (230, 40, 40), -1)
        return img

    def test_px_scales_with_hearts(self):
        self.assertGreater(detect.heart_px(self._hearts(8)), detect.heart_px(self._hearts(4)))
        self.assertEqual(0, detect.heart_px(blank()))

    def test_hearts_from_px(self):
        self.assertEqual(8, detect.hearts_from_px(5633))
        self.assertEqual(4, detect.hearts_from_px(2817))
        self.assertEqual(2, detect.hearts_from_px(1400))
        self.assertEqual(0, detect.hearts_from_px(0))
        self.assertEqual(8, detect.hearts_from_px(9000))


class TestProgress(unittest.TestCase):
    def test_sums_fractions(self):
        self.assertEqual((1, 2), detect.parse_progress(["Catch Giant Gulper Mutant (1/1)", "Catch Sob Blob Mutant (0/1)"]))

    def test_done(self):
        self.assertEqual((2, 2), detect.parse_progress(["x (1/1)", "y (1/1)"]))

    def test_none_found(self):
        self.assertEqual((0, 0), detect.parse_progress(["Special: One Last Tear"]))

    def test_ocr_spacing(self):
        self.assertEqual((0, 1), detect.parse_progress(["Catch Sob Blob ( 0 / 1 )"]))


def frame_with_minimap(name):
    from pathlib import Path
    crop = cv2.cvtColor(cv2.imread(str(Path(__file__).parent / 'images' / 'fishing' / name)), cv2.COLOR_BGR2RGB)
    img = blank()
    img[:crop.shape[0], :crop.shape[1]] = crop
    return img


def angle_gap(a, b):
    return abs((a - b + 180) % 360 - 180)


class TestLandAvoidance(unittest.TestCase):
    def mask(self, name):
        return detect.minimap_danger(frame_with_minimap(name))

    def test_open_sea_is_clear_in_every_direction(self):
        for name in ('mini_west.png', 'mini_sea_day.png', 'mini_north.png'):
            mask = self.mask(name)
            for bearing in range(0, 360, 30):
                self.assertLess(detect.sector_danger(mask, bearing), 0.3, (name, bearing))

    def test_dock_is_dangerous_to_the_north_east(self):
        mask = self.mask('mini_dock.png')
        self.assertGreater(detect.sector_danger(mask, 45), 0.4)
        self.assertLess(detect.sector_danger(mask, 200), 0.1)

    def test_steers_around_land(self):
        mask = self.mask('mini_dock.png')
        bearing, offset = detect.steer_bearing(mask, 45)
        self.assertGreaterEqual(abs(offset), 30)
        self.assertLess(detect.sector_danger(mask, bearing), 0.3)

    def test_keeps_the_target_bearing_when_clear(self):
        mask = self.mask('mini_sea_day.png')
        self.assertEqual((200, 0), detect.steer_bearing(mask, 200))

    @staticmethod
    def blocked_between(lo, hi):
        """Mask with land across the minimap angles lo..hi (degrees, east 0, anticlockwise)."""
        _, ang = detect._minimap_grid()
        return ((ang - lo) % 360) <= ((hi - lo) % 360)

    def test_equal_options_keep_the_side_already_taken(self):
        mask = self.blocked_between(-40, 40)
        self.assertEqual(-60, detect.steer_bearing(mask, 0, prefer=-1)[1])
        self.assertEqual(60, detect.steer_bearing(mask, 0, prefer=1)[1])

    def test_stays_on_the_committed_side_when_it_is_only_a_little_longer(self):
        # left needs 60, right needs 80 plus the switch cost of 30: keep going right would be 80 < 90
        mask = self.blocked_between(-40, 60)
        self.assertEqual(80, detect.steer_bearing(mask, 0, prefer=1)[1])

    def test_switches_side_when_the_committed_side_is_much_longer(self):
        mask = self.blocked_between(-100, 40)
        self.assertEqual(60, detect.steer_bearing(mask, 0, prefer=-1)[1])

    def test_boxed_in_gives_none(self):
        full = np.ones((260, 260), bool)
        self.assertIsNone(detect.steer_bearing(full, 90))


class TestMinimap(unittest.TestCase):
    def test_arrow_points_west(self):
        self.assertLess(angle_gap(detect.arrow_heading(frame_with_minimap('mini_west.png')), 180), 20)

    def test_arrow_points_north(self):
        self.assertLess(angle_gap(detect.arrow_heading(frame_with_minimap('mini_north.png')), 90), 20)

    def test_arrow_points_south_east(self):
        self.assertLess(angle_gap(detect.arrow_heading(frame_with_minimap('mini_southeast.png')), 305), 20)

    def test_no_arrow_gives_none(self):
        self.assertIsNone(detect.arrow_heading(blank()))

    def test_target_bearing_is_east(self):
        for name in ('mini_west.png', 'mini_north.png', 'mini_southeast.png'):
            self.assertLess(angle_gap(detect.minimap_target_bearing(frame_with_minimap(name)), 358), 8, name)

    def test_target_radius_is_at_the_rim_when_far(self):
        # live: a far target is pinned to the minimap edge
        self.assertTrue(60 < detect.minimap_target_radius(frame_with_minimap('mini_west.png')) < 90)
        self.assertIsNone(detect.minimap_target_radius(blank()))

    def test_no_target_gives_none(self):
        self.assertIsNone(detect.minimap_target_bearing(blank()))

    def test_heading_error_sign_and_wrap(self):
        # positive: the target is anticlockwise of the heading, so turn left (A)
        self.assertAlmostEqual(44.0, detect.heading_error(310, 354), delta=0.01)
        self.assertAlmostEqual(-84.0, detect.heading_error(78, 354), delta=0.01)
        self.assertAlmostEqual(180.0, abs(detect.heading_error(171, 351)), delta=0.01)
