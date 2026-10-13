import unittest

from src.fishing.cargo_packer import normalize, rotate_cw, orientations, pack, pack_best

L = {(0, 0), (1, 0), (2, 0), (2, 1)}
SQUARE = {(0, 0), (0, 1), (1, 0), (1, 1)}
BAR = {(0, 0), (0, 1), (0, 2), (0, 3)}


def grid(rows, cols, blocked=()):
    return {(r, c) for r in range(rows) for c in range(cols)} - set(blocked)


class TestCargoPacker(unittest.TestCase):
    def test_rotate_four_times_is_identity(self):
        cells = normalize(L)
        r = cells
        for _ in range(4):
            r = rotate_cw(r)
        self.assertEqual(cells, r)

    def test_square_has_one_orientation(self):
        self.assertEqual(1, len(orientations(SQUARE)))

    def test_single_piece_fits_exactly(self):
        out = pack(grid(2, 2), {"sq": SQUARE})
        self.assertEqual(grid(2, 2), out["sq"].cells)
        self.assertEqual((0, 0), out["sq"].origin)

    def test_needs_rotation(self):
        out = pack(grid(2, 3), {"l": L})
        self.assertIsNotNone(out)
        p = out["l"]
        self.assertNotEqual(0, p.rotations)
        expected = dict(orientations(L))[p.rotations]
        self.assertEqual(expected, normalize(p.cells))

    def test_two_pieces_do_not_overlap(self):
        free = grid(2, 6)
        out = pack(free, {"a": SQUARE, "b": BAR})
        self.assertIsNotNone(out)
        self.assertEqual(set(), set(out["a"].cells) & set(out["b"].cells))
        self.assertTrue((set(out["a"].cells) | set(out["b"].cells)) <= free)

    def test_blocked_corners_respected(self):
        free = grid(2, 2, blocked=[(0, 0)])
        self.assertIsNone(pack(free, {"sq": SQUARE}))

    def test_returns_none_when_not_all_fit(self):
        self.assertIsNone(pack(grid(2, 2), {"a": SQUARE, "b": SQUARE}))

    def test_empty_pieces(self):
        self.assertEqual({}, pack(grid(2, 2), {}))

    def test_backtracks_to_find_tight_fit(self):
        # 2x4 free: bar horizontal on one row, then another bar on the other row.
        out = pack(grid(2, 4), {"a": BAR, "b": BAR})
        self.assertIsNotNone(out)
        self.assertEqual(grid(2, 4), out["a"].cells | out["b"].cells)

    def test_best_prefers_higher_value(self):
        out = pack_best(grid(2, 2), {"a": SQUARE, "b": SQUARE}, {"a": 5, "b": 8})
        self.assertEqual({"b"}, set(out))

    def test_best_keeps_required_over_value(self):
        out = pack_best(grid(2, 2), {"a": SQUARE, "b": SQUARE}, {"a": 1, "b": 10}, required=["a"])
        self.assertEqual({"a"}, set(out))

    def test_best_none_when_required_does_not_fit(self):
        self.assertIsNone(pack_best(grid(2, 2), {"a": SQUARE, "b": SQUARE}, {"a": 1, "b": 1}, required=["a", "b"]))

    def test_best_picks_best_subset(self):
        pieces = {"bar": BAR, "s1": SQUARE, "s2": SQUARE}
        out = pack_best(grid(2, 4), pieces, {"bar": 3, "s1": 5, "s2": 5})
        self.assertEqual({"s1", "s2"}, set(out))

    def test_best_no_overlap_and_inside_free(self):
        free = grid(3, 4, blocked=[(0, 0)])
        out = pack_best(free, {"l": L, "sq": SQUARE, "bar": BAR}, {"l": 4, "sq": 6, "bar": 5})
        used = [c for p in out.values() for c in p.cells]
        self.assertEqual(len(used), len(set(used)))
        self.assertTrue(set(used) <= free)

    def test_best_node_limit_still_returns_plan(self):
        out = pack_best(grid(2, 2), {"a": SQUARE}, {"a": 1}, node_limit=1)
        self.assertEqual({"a"}, set(out))

    def test_best_empty(self):
        self.assertEqual({}, pack_best(grid(2, 2), {}, {}))
