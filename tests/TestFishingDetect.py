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
        # the pale pier is mostly left to the camera model; the dark structure beside it still counts
        mask = self.mask('mini_dock.png')
        self.assertGreater(max(detect.sector_danger(mask, b) for b in (45, 60, 75)), 0.25)
        self.assertLess(detect.sector_danger(mask, 200), 0.1)

    def test_island_body_is_land_not_just_its_darkest_patches(self):
        # live: the lighter grey-green island north-west of the boat was read as open water, so the route hugged it
        mask = self.mask('mini_island.png')
        self.assertGreater(detect.sector_danger(mask, 90), 0.6)
        self.assertGreater(detect.sector_danger(mask, 120), 0.4)
        self.assertGreater(detect.sector_danger(mask, 180), 0.3)      # the island's west coast, chest on it
        for bearing in (240, 270, 300):
            self.assertLess(detect.sector_danger(mask, bearing), 0.1, bearing)

    def test_night_coast_is_land_in_and_out_of_the_cone(self):
        # live at night land is only a little lighter than the water: a coast to the east and north-east, open sea west
        mask = self.mask('mini_night_coast.png')
        for bearing in (0, 30, 60, 90):
            self.assertGreater(detect.sector_danger(mask, bearing), 0.3, bearing)
        for bearing in (180, 210, 240, 270):
            self.assertLess(detect.sector_danger(mask, bearing), 0.05, bearing)

    def test_night_islet_to_the_south_and_coast_to_the_north(self):
        mask = self.mask('mini_night_islet.png')
        self.assertGreater(detect.sector_danger(mask, 270), 0.15)
        for bearing in (150, 180, 210):
            self.assertLess(detect.sector_danger(mask, bearing), 0.05, bearing)

    def test_the_view_cone_over_open_water_is_not_land(self):
        # the cone fades from the arrow to the rim; it must not be read as land at any radius
        mask = self.mask('mini_west.png')
        self.assertLess(mask.mean(), 0.01)

    def test_the_edge_of_the_view_cone_is_not_land(self):
        # the cone is a soft white blend; its far edge sits halfway between water and land in colour
        mask = self.mask('mini_sea_day.png')
        self.assertLess(mask.mean(), 0.01)


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

    def test_icon_is_found_over_bright_scenery(self):
        # live: the minimap is translucent, over the lit dock the icon's purple is lighter than a fixed RGB
        # window allows and the icon was reported lost, which opened the Set Time dial
        img = frame_with_minimap('mini_dock_lit.png')
        self.assertIsNotNone(detect.minimap_target_bearing(img))
        self.assertLess(angle_gap(detect.minimap_target_bearing(img), 155), 15)   # up and to the left of the arrow
        self.assertTrue(60 < detect.minimap_target_radius(img) < 90)

    def test_a_few_stray_purple_pixels_are_not_an_icon(self):
        img = blank()
        img[100:102, 80:83] = (150, 60, 200)
        self.assertIsNone(detect.minimap_target_bearing(img))

    def test_heading_error_sign_and_wrap(self):
        # positive: the target is anticlockwise of the heading, so turn left (A)
        self.assertAlmostEqual(44.0, detect.heading_error(310, 354), delta=0.01)
        self.assertAlmostEqual(-84.0, detect.heading_error(78, 354), delta=0.01)
        self.assertAlmostEqual(180.0, abs(detect.heading_error(171, 351)), delta=0.01)


class TestHeartsState(unittest.TestCase):
    def test_full_and_damaged(self):
        self.assertEqual('ok', detect.hearts_state(5633, 5633))
        self.assertEqual('ok', detect.hearts_state(3000, 5633))

    def test_low_hearts_abort(self):
        self.assertEqual('low', detect.hearts_state(1400, 5633))   # 2 hearts

    def test_no_red_at_all_means_the_hud_is_not_showing(self):
        # live: a menu left open reads as zero hearts and must not look like a sinking boat
        self.assertEqual('hidden', detect.hearts_state(0, 5633))
        self.assertEqual('hidden', detect.hearts_state(12, 5633))
