import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.fishing import recorder


def frame(value):
    return np.full((1080, 1920, 3), value, np.uint8)


class TestViewChanged(unittest.TestCase):
    def test_first_frame_is_always_new(self):
        self.assertTrue(recorder.view_changed(None, recorder.frame_signature(frame(10))))

    def test_same_view_is_skipped(self):
        sig = recorder.frame_signature(frame(100))
        self.assertFalse(recorder.view_changed(sig, recorder.frame_signature(frame(102))))

    def test_different_view_is_kept(self):
        self.assertTrue(recorder.view_changed(recorder.frame_signature(frame(40)),
                                              recorder.frame_signature(frame(120))))


class TestSailingState(unittest.TestCase):
    def test_hud_hidden_is_not_sailing(self):
        self.assertFalse(recorder.is_sailing(0))
        self.assertTrue(recorder.is_sailing(5633))

    def test_heart_loss_needs_a_previous_reading_and_a_ten_percent_drop(self):
        self.assertFalse(recorder.heart_lost(None, 100))
        self.assertFalse(recorder.heart_lost(5633, 5300))
        self.assertTrue(recorder.heart_lost(5633, 4200))


class TestFrameSaver(unittest.TestCase):
    def test_numbers_frames_and_tags_hits(self):
        with tempfile.TemporaryDirectory() as tmp:
            saver = recorder.FrameSaver(tmp, session='s1')
            first = saver.save(frame(50))
            second = saver.save(frame(60), 'hit')
            self.assertEqual('s1_00000_ok.jpg', first.name)
            self.assertEqual('s1_00001_hit.jpg', second.name)
            self.assertTrue(Path(tmp, 's1', first.name).is_file())
            self.assertEqual(2, saver.count)


class TestRecentFrames(unittest.TestCase):
    def test_keeps_one_frame_per_gap_and_the_newest_ones(self):
        now = [0.0]
        recent = recorder.RecentFrames(size=2, gap=1.0, clock=lambda: now[0])
        for second, value in enumerate([10, 20, 30, 40]):
            now[0] = second * 0.5            # two pushes per second: only every other one is kept
            recent.push(frame(value))
        kept = recent.take()
        self.assertEqual([10, 30], [int(f[0, 0, 0]) for f in kept])
        self.assertEqual([], recent.take())

    def test_a_pushed_frame_is_a_copy(self):
        recent = recorder.RecentFrames()
        original = frame(5)
        recent.push(original)
        original[:] = 99
        self.assertEqual(5, int(recent.take()[0][0, 0, 0]))


class TestRegistered(unittest.TestCase):
    def test_in_config(self):
        from config import config
        self.assertIn(["src.task.SailRecorderTask", "SailRecorderTask"], config["onetime_tasks"])
        self.assertIn(["src.task.SailTestTask", "SailTestTask"], config["onetime_tasks"])
