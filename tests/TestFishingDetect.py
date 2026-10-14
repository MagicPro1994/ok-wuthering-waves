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

    def test_no_target_gives_none(self):
        self.assertIsNone(detect.minimap_target_bearing(blank()))

    def test_heading_error_sign_and_wrap(self):
        # positive: the target is anticlockwise of the heading, so turn left (A)
        self.assertAlmostEqual(44.0, detect.heading_error(310, 354), delta=0.01)
        self.assertAlmostEqual(-84.0, detect.heading_error(78, 354), delta=0.01)
        self.assertAlmostEqual(180.0, abs(detect.heading_error(171, 351)), delta=0.01)
