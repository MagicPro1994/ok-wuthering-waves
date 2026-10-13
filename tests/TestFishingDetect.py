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
