import time
from collections import deque
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from src.fishing import detect

SIGNATURE_SIZE = (64, 36)


def frame_signature(bgr: np.ndarray) -> np.ndarray:
    """Tiny blurred grey copy of a frame, enough to tell whether the boat now looks at a different view."""
    grey = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(cv2.resize(grey, SIGNATURE_SIZE, interpolation=cv2.INTER_AREA), (5, 5), 0)


def view_changed(previous: Optional[np.ndarray], current: np.ndarray, min_change: float = 4.0) -> bool:
    """True when the mean grey difference to the last saved frame exceeds `min_change` (0 to 255)."""
    if previous is None:
        return True
    return float(np.abs(previous.astype(int) - current.astype(int)).mean()) > min_change


def is_sailing(px: int, full_px: int = detect.FULL_HEARTS_PX) -> bool:
    """The heart row shows only while sailing with no menu open."""
    return px >= full_px * 0.3


def heart_lost(previous_px: Optional[int], px: int) -> bool:
    return previous_px is not None and px < previous_px * 0.9


class RecentFrames:
    """The last few frames, one per `gap` seconds, so a hit can be saved together with the approach to it."""

    def __init__(self, size: int = 4, gap: float = 0.7, clock=time.time):
        self.frames = deque(maxlen=size)
        self.gap = gap
        self.clock = clock
        self.last = float('-inf')

    def push(self, bgr: np.ndarray) -> None:
        now = self.clock()
        if now - self.last >= self.gap:
            self.frames.append(bgr.copy())
            self.last = now

    def take(self) -> list:
        """The kept frames, oldest first; the buffer starts over afterwards."""
        frames = list(self.frames)
        self.frames.clear()
        return frames


class FrameSaver:
    """Writes numbered JPEG frames of one session into `<folder>/<session>/`; a tag in the name marks a hit."""

    def __init__(self, folder, session: Optional[str] = None, quality: int = 92):
        self.session = session or time.strftime('%Y%m%d_%H%M%S')
        self.folder = Path(folder) / self.session
        self.quality = quality
        self.count = 0

    def save(self, bgr: np.ndarray, tag: str = 'ok') -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f'{self.session}_{self.count:05d}_{tag}.jpg'
        if not cv2.imwrite(str(path), bgr, [cv2.IMWRITE_JPEG_QUALITY, self.quality]):
            raise OSError(f'could not write {path}')
        self.count += 1
        return path
