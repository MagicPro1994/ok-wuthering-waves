import random
import unittest

from src.fishing.real_input import RealInput, to_screen, LEFTDOWN, LEFTUP, MOVE


class FakeApi:
    def __init__(self, foreground_after=1):
        self.calls = []
        self.fg = 0
        self.attempts = 0
        self.foreground_after = foreground_after

    def set_cursor(self, x, y): self.calls.append(("cursor", x, y))
    def mouse_event(self, flags, dx=0, dy=0): self.calls.append(("event", flags, dx, dy))
    def foreground(self): return self.fg
    def keybd_alt(self): self.calls.append(("alt",))

    def set_foreground(self, hwnd):
        self.attempts += 1
        if self.attempts >= self.foreground_after:
            self.fg = hwnd

    def client_origin(self, hwnd): return (100, 50)
    def client_size(self, hwnd): return (1920, 1080)


class TestRealInput(unittest.TestCase):
    def test_to_screen(self):
        self.assertEqual((100 + 960, 50 + 540), to_screen((100, 50), (1920, 1080), 0.5, 0.5))

    def test_drag_order(self):
        api = FakeApi()
        RealInput(7, api=api, sleep=lambda s: None, rng=random.Random(3)).drag(0.2, 0.3, 0.6, 0.5, 0.4)
        events = [c for c in api.calls if c[0] == "event"]
        self.assertEqual(LEFTDOWN, events[0][1])
        self.assertEqual(LEFTUP, events[-1][1])
        cursors = [c for c in api.calls if c[0] == "cursor"]
        self.assertAlmostEqual(100 + 0.2 * 1920, cursors[0][1], delta=3)
        self.assertAlmostEqual(100 + 0.6 * 1920, cursors[-1][1], delta=3)
        self.assertGreater(len(cursors), 10)
        down_index = api.calls.index(events[0])
        up_index = api.calls.index(events[-1])
        self.assertTrue(any(c[0] == "cursor" for c in api.calls[down_index:up_index]))

    def test_drag_path_is_not_a_straight_line(self):
        api = FakeApi()
        RealInput(7, api=api, sleep=lambda s: None, rng=random.Random(3)).drag(0.2, 0.5, 0.8, 0.5, 0.5)
        ys = {c[2] for c in api.calls if c[0] == "cursor"}
        self.assertGreater(len(ys), 1)

    def test_focus_retries_then_succeeds(self):
        api = FakeApi(foreground_after=3)
        RealInput(7, api=api, sleep=lambda s: None).focus()
        self.assertEqual(7, api.fg)

    def test_focus_failure_raises(self):
        api = FakeApi(foreground_after=99)
        with self.assertRaises(RuntimeError):
            RealInput(7, api=api, sleep=lambda s: None).focus()

    def test_rel_move(self):
        api = FakeApi()
        RealInput(7, api=api, sleep=lambda s: None).rel_move(40, -1)
        self.assertEqual([("event", MOVE, 40, -1)], api.calls)
