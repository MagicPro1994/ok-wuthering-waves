import re
from typing import Iterable, Optional, Tuple

import cv2
import numpy as np

FULL_HEARTS_PX = 5633
MAX_HEARTS = 8
_PROGRESS = re.compile(r'\(\s*(\d+)\s*/\s*(\d+)\s*\)')


def find_marker(rgb: np.ndarray) -> Optional[Tuple[float, float, int]]:
    """Round purple fish marker in the 3D view, as (x, y, area) in 1920x1080 pixels."""
    r, g, b = [rgb[..., i].astype(int) for i in range(3)]
    mask = ((r > 110) & (r < 200) & (b > 150) & (g < 110) & (b - g > 70)).astype(np.uint8)
    mask[:430, :340] = 0      # minimap and quest tracker
    mask[0:140, :] = 0        # top bar
    mask[600:, 1560:] = 0     # bottom-right action icons
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
    best = None
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if 250 < area < 1500 and 0.75 < w / h < 1.33 and area / (w * h) > 0.55:
            if best is None or area > best[2]:
                best = (float(centroids[i][0]), float(centroids[i][1]), int(area))
    return best


def heart_px(rgb: np.ndarray) -> int:
    row = rgb[1000:1030, 680:1200].astype(int)
    r, g, b = row[..., 0], row[..., 1], row[..., 2]
    return int(((r > 200) & (g < 80) & (b < 90)).sum())


def hearts_from_px(px: int, full_px: int = FULL_HEARTS_PX, max_hearts: int = MAX_HEARTS) -> int:
    return max(0, min(max_hearts, round(px * max_hearts / full_px)))


def marker_error_deg(marker_x: float, centre_x: float = 960.0, px_per_deg: float = 21.0) -> float:
    return (marker_x - centre_x) / px_per_deg


def parse_progress(texts: Iterable[str]) -> Tuple[int, int]:
    done = total = 0
    for text in texts:
        for n, m in _PROGRESS.findall(text):
            done += int(n)
            total += int(m)
    return done, total
