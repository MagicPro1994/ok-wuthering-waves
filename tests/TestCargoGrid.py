import unittest

import cv2
import numpy as np

from src.fishing import cargo_grid as cg


def fixture(name):
    return cv2.cvtColor(cv2.imread(f"tests/images/fishing/{name}"), cv2.COLOR_BGR2RGB)


def paint(img, cells, colour=(90, 160, 230)):
    out = img.copy()
    for r, c in cells:
        x, y = cg.cell_center(r, c)
        cx, cy = int(x * 1920), int(y * 1080)
        cv2.rectangle(out, (cx - 30, cy - 30), (cx + 30, cy + 30), colour, -1)
    return out


class TestGeometry(unittest.TestCase):
    def test_usable_cells_are_52(self):
        self.assertEqual(52, len(cg.free_cells(set())))

    def test_blocked_corners(self):
        self.assertEqual({(0, 0), (0, 7), (6, 0), (6, 7)}, set(cg.BLOCKED))

    def test_free_cells_exclude_occupied(self):
        self.assertNotIn((3, 3), cg.free_cells({(3, 3)}))
        self.assertEqual(51, len(cg.free_cells({(3, 3)})))

    def test_cell_center_is_inside_the_cell(self):
        x, y = cg.cell_center(1, 1)
        self.assertAlmostEqual(1062.5 / 1920, x, places=3)
        self.assertAlmostEqual(320.5 / 1080, y, places=3)

    def test_real_fixture_free_cell_centres_are_empty_grey(self):
        img = fixture("cargo_empty.png")
        for r, c in cg.free_cells(set()):
            x, y = cg.cell_center(r, c)
            pixel = img[int(y * 1080), int(x * 1920)].astype(int)
            self.assertTrue(all(abs(v - 52) < 8 for v in pixel), (r, c, pixel))


class TestPreview(unittest.TestCase):
    def test_reads_painted_cells(self):
        before = fixture("cargo_empty.png")
        cells = [(2, 2), (3, 2), (4, 2), (4, 3)]
        self.assertEqual(frozenset(cells), cg.read_preview(before, paint(before, cells)))

    def test_identical_frames_have_no_preview(self):
        img = fixture("cargo_empty.png")
        self.assertEqual(frozenset(), cg.read_preview(img, img))


class TestOccupied(unittest.TestCase):
    def test_empty_cargo_has_no_occupied_cells(self):
        self.assertEqual(frozenset(), cg.occupied_cells(fixture("cargo_empty.png")))

    def test_painted_cells_are_occupied(self):
        img = paint(fixture("cargo_empty.png"), [(1, 1), (5, 6)])
        self.assertEqual(frozenset({(1, 1), (5, 6)}), cg.occupied_cells(img))


class TestParseValue(unittest.TestCase):
    def test_values(self):
        self.assertEqual(1240, cg.parse_value(["Price", "1,240"]))
        self.assertEqual(95, cg.parse_value(["Price 95"]))
        self.assertIsNone(cg.parse_value(["Size", "Micro"]))


class TestCards(unittest.TestCase):
    def test_card_slots_are_inside_the_left_panel_and_distinct(self):
        centres = [cg.card_center(i) for i in range(cg.MAX_CARDS)]
        self.assertEqual(len(centres), len(set(centres)))
        for x, y in centres:
            self.assertTrue(0 < x < 0.5 and 0 < y < 1)

    def test_card_box_contains_its_centre(self):
        x, y = cg.card_center(0)
        x0, y0, x1, y1 = cg.card_box(0)
        self.assertTrue(x0 < x < x1 and y0 < y < y1)
